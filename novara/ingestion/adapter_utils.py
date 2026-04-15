"""Shared utilities for source adapters.

All adapters import from here rather than duplicating helper code.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag


# ── Text extraction ───────────────────────────────────────────────────────────

def text(el: Tag | None) -> str | None:
    """Return stripped text of a BeautifulSoup element, or None if missing."""
    if el is None:
        return None
    t = el.get_text(strip=True)
    return t or None


def inner_text(el: Tag | None, separator: str = "\n") -> str | None:
    """Multi-line text extraction preserving paragraph breaks."""
    if el is None:
        return None
    t = el.get_text(separator=separator, strip=True)
    return t or None


def attr(el: Tag | None, *attrs: str) -> str | None:
    """Return the first non-empty attribute value from a list of candidates."""
    if el is None:
        return None
    for a in attrs:
        val = el.get(a)
        if val and str(val).strip():
            return str(val).strip()
    return None


# ── URL helpers ───────────────────────────────────────────────────────────────

def absolute_url(base: str, href: str) -> str:
    """Resolve a potentially relative URL against a base URL."""
    if not href:
        return ""
    if href.startswith(("http://", "https://")):
        return href
    return urljoin(base, href)


def domain(url: str) -> str:
    """Extract the netloc (e.g. 'www.royalroad.com') from a URL."""
    return urlparse(url).netloc


# ── Chapter number parsing ────────────────────────────────────────────────────

_CHAPTER_NUM_PATTERNS = [
    re.compile(r"chapter\s+(\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"\bch\.?\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE),
    re.compile(r"#\s*(\d+(?:\.\d+)?)"),
    re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[:\-–—]"),  # "42: Title" or "42 - Title"
    re.compile(r"(\d+(?:\.\d+)?)\s*$"),             # trailing number
]


def parse_chapter_number(text: str | None, url: str = "") -> float | None:
    """Extract a chapter number from a title string or URL.

    Tries multiple patterns in order of specificity.
    Returns None if no number can be reliably extracted.
    """
    for source in (text or "", url):
        if not source:
            continue
        for pattern in _CHAPTER_NUM_PATTERNS:
            m = pattern.search(source)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    continue
    return None


# ── Status normalisation ──────────────────────────────────────────────────────

_STATUS_MAP = {
    "ongoing": "ongoing",
    "on-going": "ongoing",
    "active": "ongoing",
    "updating": "ongoing",
    "new": "ongoing",
    "hot": "ongoing",
    "completed": "completed",
    "complete": "completed",
    "finished": "completed",
    "end": "completed",
    "ended": "completed",
    "full": "completed",
    "hiatus": "hiatus",
    "on hiatus": "hiatus",
    "on hold": "hiatus",
    "pause": "hiatus",
    "paused": "hiatus",
    "dropped": "dropped",
    "cancelled": "dropped",
    "canceled": "dropped",
    "discontinued": "dropped",
    "abandoned": "dropped",
}


def normalise_status(raw: str | None) -> str | None:
    """Map any source status string to the canonical set.

    Canonical: ongoing | completed | hiatus | dropped
    Returns None if the string doesn't map to anything known.
    """
    if not raw:
        return None
    key = raw.lower().strip()
    return _STATUS_MAP.get(key)


# ── Cover extraction helpers ──────────────────────────────────────────────────

def find_cover(soup: BeautifulSoup, *selectors: str) -> str | None:
    """Try a list of CSS selectors to find a cover image URL.

    Each selector should target an <img> element. Falls back through the
    list until a non-empty src/data-src is found.
    """
    for selector in selectors:
        img = soup.select_one(selector)
        if isinstance(img, Tag):
            url = attr(img, "src", "data-src", "data-lazy-src", "data-original")
            if url and not url.startswith("data:"):
                return url
    return None


# ── Pagination helpers ────────────────────────────────────────────────────────

def find_next_page(soup: BeautifulSoup, base_url: str) -> str | None:
    """Find a 'next page' link for paginated chapter lists.

    Looks for common pagination patterns: rel=next, text='Next', '›', '»'.
    Returns the absolute URL of the next page, or None if on the last page.
    """
    # rel="next" is the most reliable
    next_link = soup.find("a", rel=lambda r: r and "next" in r)
    if isinstance(next_link, Tag):
        href = attr(next_link, "href")
        if href:
            return absolute_url(base_url, href)

    # Text-based next buttons
    for text_hint in ("next", "›", "»", "next page", "next »"):
        for a in soup.find_all("a"):
            if not isinstance(a, Tag):
                continue
            t = a.get_text(strip=True).lower()
            if t == text_hint:
                href = attr(a, "href")
                if href and href != "#":
                    return absolute_url(base_url, href)

    return None
