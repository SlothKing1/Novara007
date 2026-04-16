"""Tier detector — auto-detects the fetch strategy a novel site requires.

Novel sites range from simple HTML (tier 1) to heavy Cloudflare-protected
pages that need headless browsing (tier 4).  This module tries each tier in
sequence and reports the lowest tier that works for a given URL.

Tiers
-----
1  basic httpx          — fast, works for most sites
2  cloudscraper         — solves simple Cloudflare JS challenges
3  curl_cffi            — TLS fingerprint impersonation; bypasses modern CF
4  scrapling/playwright — full headless Chromium; last resort

Usage
-----
    from novara.ingestion.tier_detector import detect_tier, probe_site

    # Quick check: what tier does this site need?
    result = detect_tier("https://some-novel-site.com/novel/some-novel")
    print(result["tier"], result["name"])

    # Full site probe with BFS novel discovery:
    report = await probe_site_async("https://some-novel-site.com")
    print(report["tier"], report["confidence"], report["novel_count"])

Ported and adapted from the original Novara v1 (Max-System-novara-project-1)
with minor changes to integrate with Novara's settings and logging.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urljoin, urlparse

import structlog

from novara.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

# ── Tier config ──────────────────────────────────────────────────────────────

TIER_CONFIGS: dict[int, dict[str, Any]] = {
    1: {"name": "httpx",        "fetcher": "httpx",        "delay": 1.0},
    2: {"name": "cloudscraper", "fetcher": "cloudscraper", "delay": 2.0},
    3: {"name": "curl_cffi",    "fetcher": "curl_cffi",    "delay": 3.0},
    4: {"name": "scrapling",    "fetcher": "scrapling",    "delay": 5.0},
}

# URL path patterns that indicate a novel/series page
_NOVEL_PATH_RE = [
    re.compile(r"^/novel/([^/]+)",  re.IGNORECASE),
    re.compile(r"^/series/([^/]+)", re.IGNORECASE),
    re.compile(r"^/book/([^/]+)",   re.IGNORECASE),
    re.compile(r"^/books/([^/]+)",  re.IGNORECASE),
    re.compile(r"^/story/([^/]+)",  re.IGNORECASE),
    re.compile(r"^/read/([^/]+)",   re.IGNORECASE),
    re.compile(r"/novel/([^/]+)",   re.IGNORECASE),
    re.compile(r"/series/([^/]+)",  re.IGNORECASE),
    re.compile(r"/book/([^/]+)",    re.IGNORECASE),
    re.compile(r"/story/([^/]+)",   re.IGNORECASE),
]

# URL path fragments that indicate a listing/browse page
_LISTING_FRAGS = frozenset({
    "/novels", "/series", "/books", "/stories", "/all",
    "/browse", "/category", "/genres", "/library",
})

_UA = settings.http_user_agent


# ── Low-level fetchers (synchronous, run in executor) ────────────────────────

def _fetch_httpx(url: str, timeout: int = 15) -> tuple[int, str]:
    import httpx
    with httpx.Client(
        headers={"User-Agent": _UA},
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        r = client.get(url)
        return r.status_code, r.text


def _fetch_cloudscraper(url: str, timeout: int = 15) -> tuple[int, str]:
    import cloudscraper  # type: ignore[import]
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    scraper.headers.update({"User-Agent": _UA})
    r = scraper.get(url, timeout=timeout)
    return r.status_code, r.text


def _fetch_curl_cffi(url: str, timeout: int = 15) -> tuple[int, str]:
    try:
        from curl_cffi import requests as curl_req  # type: ignore[import]
    except ImportError:
        raise ImportError("curl_cffi not installed. Run: pip install curl-cffi")
    r = curl_req.get(url, timeout=timeout, impersonate="chrome120")
    return r.status_code, r.text


def _fetch_scrapling(url: str, timeout: int = 15) -> tuple[int, str]:
    try:
        from scrapling.fetchers import AsyncFetcher  # type: ignore[import]
    except ImportError:
        return 0, "scrapling_not_installed"
    try:
        import asyncio as _asyncio
        result = _asyncio.run(AsyncFetcher.fetch(url))
        return 200, result.html
    except Exception as exc:
        err = str(exc)
        if any(kw in err.lower() for kw in ("libnspr", "playwright", "targetclosed")):
            return 0, "playwright_browser_unavailable"
        return 0, err


_FETCHERS: dict[int, Any] = {
    1: _fetch_httpx,
    2: _fetch_cloudscraper,
    3: _fetch_curl_cffi,
    4: _fetch_scrapling,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalise_url(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}{p.path.rstrip('/')}"


def _has_novel_links(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _NOVEL_PATH_RE)


def _extract_hrefs(text: str, base: str) -> list[str]:
    return [urljoin(base, h) for h in re.findall(r'href=["\']([^"\']+)["\']', text)]


def _parse_sitemap(text: str) -> list[str]:
    try:
        root = ET.fromstring(text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = root.findall(".//sm:loc", ns) or root.findall(".//loc")
        return [loc.text.strip() for loc in locs if loc.text]
    except Exception:
        return re.findall(r"<loc>\s*(https?://[^<]+)\s*</loc>", text)


def _is_listing_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.startswith(frag) or frag in path for frag in _LISTING_FRAGS)


# ── Core tier detection ───────────────────────────────────────────────────────

def detect_tier(url: str) -> dict[str, Any]:
    """Synchronously try each tier in order; return the first that works.

    "Works" = HTTP 200 with at least one novel-pattern link in the response.

    Returns a dict with keys: tier, name, fetcher, delay, status, note, url.
    tier is None if all fetchers failed.
    """
    for tier, cfg in TIER_CONFIGS.items():
        try:
            status, text = _FETCHERS[tier](url)
            if status == 200 and _has_novel_links(text):
                log.info("tier_detected", url=url, tier=tier, name=cfg["name"])
                return {
                    "tier": tier,
                    "name": cfg["name"],
                    "fetcher": cfg["fetcher"],
                    "delay": cfg["delay"],
                    "status": status,
                    "note": "success",
                    "url": url,
                }
            note = f"HTTP {status}" if status != 200 else "200 but no novel links"
        except Exception as exc:
            note = str(exc)
        log.debug("tier_failed", url=url, tier=tier, note=note)

    return {
        "tier": None, "name": "unknown", "fetcher": None, "delay": None,
        "status": None, "note": "all fetchers failed", "url": url,
    }


# ── Async wrappers ────────────────────────────────────────────────────────────

async def _fetch_async(
    url: str,
    tier: int,
    semaphore: asyncio.Semaphore,
) -> tuple[str, int, str]:
    async with semaphore:
        loop = asyncio.get_event_loop()
        status, text = await loop.run_in_executor(
            None, _FETCHERS[tier], url
        )
        return url, status, text


# ── Novel discovery ───────────────────────────────────────────────────────────

async def discover_novels_async(
    base_url: str,
    *,
    max_novels: int = 10,
    max_pages: int = 30,
) -> list[dict[str, Any]]:
    """BFS crawl from base_url to discover novel page URLs on the site.

    Strategy:
    1. Try sitemap.xml for a fast seed list.
    2. BFS through listing/browse pages up to max_pages.
    3. For each URL that matches a novel path pattern, record it.

    Returns a list of dicts: {url, slug, source, tier, tier_name, fetcher, delay}.
    """
    base = base_url.rstrip("/")
    seen: set[str] = set()
    queue: list[tuple[str, str, int]] = [(base, "homepage", 0)]
    results: list[dict[str, Any]] = []
    working_tier = 1
    sem = asyncio.Semaphore(5)

    # Seed from sitemap
    sitemap_url = urljoin(base, "/sitemap.xml")
    try:
        _, sm_text = await _fetch_async(sitemap_url, working_tier, sem)
        for u in _parse_sitemap(sm_text):
            nu = _normalise_url(u)
            if nu not in seen:
                seen.add(nu)
                queue.append((nu, "sitemap", 0))
    except Exception:
        pass

    while queue and len(results) < max_novels:
        url, source, depth = queue.pop(0)
        if depth >= 3:
            continue

        _, status, text = await _fetch_async(url, working_tier, sem)
        if status != 200:
            continue

        for link in _extract_hrefs(text, url):
            nu = _normalise_url(link)
            if nu not in seen and len(seen) < max_pages:
                seen.add(nu)
                src = "listing" if _is_listing_url(link) else source
                queue.append((nu, src, depth + 1))

        path = urlparse(url).path
        for pat in _NOVEL_PATH_RE:
            m = pat.search(path)
            if m:
                tier_info = await asyncio.get_event_loop().run_in_executor(
                    None, detect_tier, url
                )
                results.append({
                    "url": url,
                    "slug": m.group(1),
                    "source": source,
                    "tier": tier_info["tier"],
                    "tier_name": tier_info["name"],
                    "fetcher": tier_info["fetcher"],
                    "delay": tier_info["delay"],
                })
                break

    return results


# ── Full site probe ───────────────────────────────────────────────────────────

async def probe_site_async(base_url: str) -> dict[str, Any]:
    """Probe a site: detect tier, check sitemap, discover novel URLs.

    Useful when adding a new source that doesn't have a dedicated adapter yet.

    Returns::

        {
            "base_url": str,
            "tier": int | None,
            "name": str,
            "fetcher": str | None,
            "delay": float | None,
            "confidence": "high" | "medium" | "low" | "none",
            "has_sitemap": bool,
            "sitemap_url_count": int,
            "novel_count": int,
            "novels_discovered": [...],
        }
    """
    base = base_url.rstrip("/")
    loop = asyncio.get_event_loop()

    home_tier = await loop.run_in_executor(None, detect_tier, base)

    # Sitemap check
    sitemap_url = urljoin(base, "/sitemap.xml")
    sitemap_urls: list[str] = []
    has_sitemap = False
    try:
        _, sm_text = _FETCHERS[1](sitemap_url)
        if sm_text and ("<url>" in sm_text or "<loc>" in sm_text):
            sitemap_urls = _parse_sitemap(sm_text)
            has_sitemap = True
    except Exception:
        pass

    novels = await discover_novels_async(base, max_novels=8, max_pages=20)

    t = home_tier["tier"]
    if t is not None:
        confidence = "high" if len(novels) >= 3 else ("medium" if novels else "low")
    else:
        confidence = "none"

    return {
        "base_url": base,
        "tier": t,
        "name": home_tier.get("name"),
        "fetcher": home_tier.get("fetcher"),
        "delay": home_tier.get("delay"),
        "confidence": confidence,
        "has_sitemap": has_sitemap,
        "sitemap_url_count": len(sitemap_urls),
        "novel_count": len(novels),
        "novels_discovered": novels,
    }


def probe_site(base_url: str) -> dict[str, Any]:
    """Sync wrapper around probe_site_async."""
    return asyncio.run(probe_site_async(base_url))


# ── NovelDetector — multi-URL tier voting ─────────────────────────────────────

class NovelDetector:
    """Detect the required fetch tier from multiple sample URLs.

    Tries all URL candidates and takes a majority vote on tier, which is
    more reliable than testing a single URL (which may be cached or CDN-served).

    Example::

        detector = NovelDetector([
            "https://site.com/novel/foo/chapter-1",
            "https://site.com/novel/bar/chapter-5",
        ])
        config = detector.as_json_config()
        # {"fetcher": "cloudscraper", "tier": 2, "delay": 2.0}
    """

    def __init__(self, url_candidates: list[str]) -> None:
        self.url_candidates = url_candidates
        self.result: dict[str, Any] | None = None

    def detect(self) -> dict[str, Any]:
        tier_votes: dict[int, int] = {}
        tier_info_map: dict[int, dict[str, Any]] = {}

        for url in self.url_candidates:
            info = detect_tier(url)
            t = info["tier"]
            if t is not None:
                tier_votes[t] = tier_votes.get(t, 0) + 1
                tier_info_map[t] = info

        if not tier_votes:
            self.result = {
                "tier": None, "fetcher": None, "delay": None,
                "note": "no working fetcher found",
                "candidates_checked": len(self.url_candidates),
            }
            return self.result

        best_tier = max(tier_votes, key=lambda k: tier_votes[k])
        info = tier_info_map[best_tier]
        self.result = {
            "tier": best_tier,
            "name": info["name"],
            "fetcher": info["fetcher"],
            "delay": info["delay"],
            "note": f"detected from {tier_votes[best_tier]}/{len(self.url_candidates)} candidates",
            "tier_votes": tier_votes,
            "candidates_checked": len(self.url_candidates),
        }
        return self.result

    def as_json_config(self) -> dict[str, Any]:
        if self.result is None:
            self.detect()
        r = self.result
        return {
            "fetcher": r["fetcher"],
            "tier": r["tier"],
            "delay": r["delay"],
            "note": r.get("note", ""),
        }


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://royalroad.com"
    report = probe_site(url)
    print(json.dumps(report, indent=2, default=str))
