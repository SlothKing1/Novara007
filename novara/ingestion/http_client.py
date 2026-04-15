"""Shared async HTTP client with rate limiting and retry logic."""

from __future__ import annotations

import asyncio
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

# Per-site rate limiters: maps site_key → asyncio.Lock + last_request_time
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
    **kwargs: object,
) -> httpx.Response:
    """GET url with exponential-backoff retry on transient errors.

    Raises:
        httpx.HTTPStatusError: on 4xx/5xx after all retries exhausted.
        httpx.RequestError: on network errors after all retries exhausted.
    """
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
            response.raise_for_status()
            return response

    raise RuntimeError("Unreachable — tenacity should have raised")
