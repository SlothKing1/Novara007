"""Shared async HTTP client with rate limiting, retry, and cloudscraper fallback.

Fetch strategy per request:
  1. httpx (fast, async)              — works for most sites
  2. cloudscraper fallback            — for Cloudflare-protected sites (403/blocked)
  3. CamoFox (future)                 — for heavy JS-challenge sites (not yet wired)

Adapters never call requests or cloudscraper directly. They always go through
rate_limited_client() + fetch_with_retry() so rate limiting and fallback logic
is applied consistently.
"""

from __future__ import annotations

import asyncio
import functools
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from novara.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

# Status codes that indicate bot/Cloudflare blocking — trigger fallback
_BLOCKED_CODES = {403, 429, 503}

# Per-site rate limiters
_rate_lock: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_last_request_time: dict[str, float] = defaultdict(float)


@asynccontextmanager
async def rate_limited_client(
    site_key: str,
    requests_per_second: float | None = None,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async context manager yielding an httpx client with per-site rate limiting.

    Args:
        site_key: Unique key for the source site (used to bucket rate limits).
        requests_per_second: Override the global default from settings.
    """
    rps = requests_per_second or settings.ingestion_rate_limit
    min_interval = 1.0 / rps

    async with httpx.AsyncClient(
        headers={"User-Agent": settings.http_user_agent},
        timeout=httpx.Timeout(settings.http_timeout),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=settings.http_max_connections),
    ) as client:
        yield client

    # Enforce rate limit after the request block exits
    async with _rate_lock[site_key]:
        now = asyncio.get_event_loop().time()
        elapsed = now - _last_request_time[site_key]
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        _last_request_time[site_key] = asyncio.get_event_loop().time()


async def fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_attempts: int = 3,
    use_cloudscraper: bool = False,
    **kwargs: object,
) -> httpx.Response:
    """GET url with retry and optional cloudscraper fallback.

    Strategy:
    - On 403/429/503: automatically retry via cloudscraper (runs in threadpool
      so it doesn't block the event loop).
    - On network errors: standard exponential-backoff retry via httpx.

    Args:
        client: httpx client from rate_limited_client().
        url: URL to fetch.
        max_attempts: Max retry attempts for transient network errors.
        use_cloudscraper: Force cloudscraper even on first attempt (for known
            Cloudflare sites — set in the adapter with NEEDS_CLOUDSCRAPER = True).

    Returns:
        httpx.Response-compatible object (or CloudscraperResponse wrapper).

    Raises:
        httpx.HTTPStatusError / CloudflareBlocked after all fallbacks exhausted.
    """
    if use_cloudscraper:
        return await _fetch_cloudscraper(url)

    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type(
            (httpx.TransportError, httpx.TimeoutException)
        ),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    ):
        with attempt:
            log.debug("http_fetch", url=url, attempt=attempt.retry_state.attempt_number)
            response = await client.get(url, **kwargs)  # type: ignore[arg-type]

            if response.status_code in _BLOCKED_CODES:
                log.info(
                    "http_blocked_falling_back",
                    url=url,
                    status=response.status_code,
                )
                # Tier 2: cloudscraper
                cs_response = await _fetch_cloudscraper(url)
                if cs_response.status_code not in _BLOCKED_CODES:
                    return cs_response
                # Tier 3: curl_cffi (stronger TLS fingerprint)
                log.info("cloudscraper_blocked_trying_curl_cffi", url=url)
                return await _fetch_curl_cffi(url)

            response.raise_for_status()
            return response

    raise RuntimeError("Unreachable — tenacity should have raised")


# ── cloudscraper fallback ────────────────────────────────────────────────────

class _CloudscraperResponse:
    """Minimal httpx.Response-compatible wrapper around a cloudscraper response."""

    def __init__(self, cs_response: object) -> None:
        self._r = cs_response

    @property
    def text(self) -> str:
        return self._r.text  # type: ignore[attr-defined]

    @property
    def content(self) -> bytes:
        return self._r.content  # type: ignore[attr-defined]

    @property
    def status_code(self) -> int:
        return self._r.status_code  # type: ignore[attr-defined]

    def json(self) -> object:
        return self._r.json()  # type: ignore[attr-defined]

    def raise_for_status(self) -> None:
        self._r.raise_for_status()  # type: ignore[attr-defined]


async def _fetch_cloudscraper(url: str) -> _CloudscraperResponse:
    """Run cloudscraper in a threadpool executor (it's synchronous).

    cloudscraper handles Cloudflare challenges by solving JS challenges
    and managing cookies automatically.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(_cs_get, url))


def _cs_get(url: str) -> _CloudscraperResponse:
    """Synchronous cloudscraper fetch — called from threadpool."""
    try:
        import cloudscraper  # type: ignore[import]
    except ImportError as e:
        raise ImportError(
            "cloudscraper is not installed. Run: pip install cloudscraper"
        ) from e

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    scraper.headers.update({"User-Agent": settings.http_user_agent})
    resp = scraper.get(url, timeout=settings.http_timeout)
    log.debug("cloudscraper_fetch", url=url, status=resp.status_code)
    return _CloudscraperResponse(resp)


# ── curl_cffi fallback (tier 3) ──────────────────────────────────────────────

async def _fetch_curl_cffi(url: str) -> _CloudscraperResponse:
    """Run curl_cffi in a threadpool executor.

    curl_cffi impersonates a real browser's TLS fingerprint, bypassing
    Cloudflare protections that defeat cloudscraper.  Only attempted when
    cloudscraper itself returns a blocked status code.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(_ccffi_get, url))


def _ccffi_get(url: str) -> _CloudscraperResponse:
    """Synchronous curl_cffi fetch — called from threadpool."""
    try:
        from curl_cffi import requests as curl_req  # type: ignore[import]
    except ImportError as e:
        raise ImportError(
            "curl_cffi is not installed. Run: pip install curl-cffi"
        ) from e

    resp = curl_req.get(
        url,
        timeout=settings.http_timeout,
        impersonate="chrome120",
        headers={"User-Agent": settings.http_user_agent},
    )
    log.debug("curl_cffi_fetch", url=url, status=resp.status_code)
    return _CloudscraperResponse(resp)
