"""WuxiaWorld source adapter.

WuxiaWorld (wuxiaworld.com) is a major Chinese web novel translation platform.
It uses a modern SPA-style site with JSON API endpoints for chapter data.

Characteristics:
- Rich metadata: title, author, translator, genres, status, cover
- Chapters served via an internal REST API (/api/novels/<slug>/chapters)
- Chapter content is clean HTML inside a single wrapper div
- Source is authoritative for translator attribution
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from novara.ingestion.base_adapter import (
    BaseAdapter,
    RawChapterContent,
    RawChapterListing,
    RawMetadata,
)
from novara.ingestion.http_client import fetch_with_retry, rate_limited_client
from novara.ingestion.registry import register

_SLUG_RE = re.compile(r"wuxiaworld\.com/novel/([^/?#]+)")
_CHAPTER_NUM_RE = re.compile(r"chapter[- _](\d+(?:\.\d+)?)", re.IGNORECASE)


@register
class WuxiaWorldAdapter(BaseAdapter):
    SITE_KEY = "wuxiaworld"
    SITE_NAME = "WuxiaWorld"
    BASE_URL = "https://www.wuxiaworld.com"

    REQUESTS_PER_SECOND = 0.5  # be polite to WW

    def extract_source_id(self, source_url: str) -> str:
        m = _SLUG_RE.search(source_url)
        return m.group(1) if m else source_url

    def normalise_status(self, raw: str) -> str:
        mapping = {
            "ongoing": "ongoing",
            "active": "ongoing",
            "completed": "completed",
            "complete": "completed",
            "hiatus": "hiatus",
            "dropped": "dropped",
        }
        return mapping.get(raw.lower().strip(), raw.lower().strip())

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title = _text(soup.select_one("h1.novel-name") or soup.select_one("h1"))
        author = _text(soup.select_one(".author span") or soup.select_one(".author"))

        # Translator group: "Translated by" label
        translator = None
        for label in soup.select(".novel-info li"):
            text = label.get_text(" ", strip=True)
            if "translated" in text.lower():
                translator = text.split(":")[-1].strip() if ":" in text else None
                break

        # Synopsis
        synopsis_el = soup.select_one(".novel-desc .fr-view") or soup.select_one(
            ".description"
        )
        synopsis = _inner_text(synopsis_el)

        # Status
        status_raw = None
        for li in soup.select(".novel-info li"):
            if "status" in li.get_text().lower():
                status_span = li.select_one("span:last-child")
                if status_span:
                    status_raw = self.normalise_status(status_span.get_text(strip=True))
                break

        # Genres
        genres = [a.get_text(strip=True) for a in soup.select("a.tag")]

        # Cover
        cover = None
        img = soup.select_one(".novel-cover img") or soup.select_one(".cover img")
        if isinstance(img, Tag):
            cover = str(img.get("src", "") or img.get("data-src", ""))

        return RawMetadata(
            title=title,
            synopsis=synopsis,
            author=author,
            status=status_raw,
            language="en",
            original_language="zh",
            translator_group=translator,
            genres=genres,
            cover_url=cover,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        """Fetch the chapter list from the novel's HTML page.

        WuxiaWorld renders the chapter list server-side in a <ul> element.
        Falls back to pagination if needed.
        """
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        chapters: list[RawChapterListing] = []
        seen_ids: set[str] = set()

        for idx, link in enumerate(soup.select("a[href*='/chapter-']"), start=1):
            if not isinstance(link, Tag):
                continue
            href = str(link.get("href", ""))
            if not href:
                continue
            chapter_url = href if href.startswith("http") else self.BASE_URL + href

            # Derive stable ID from the URL slug after /chapter-
            chapter_id = href.rstrip("/").split("/")[-1]
            if chapter_id in seen_ids:
                continue
            seen_ids.add(chapter_id)

            title = link.get_text(strip=True) or None
            chapter_number = _parse_chapter_number(title, href) or float(idx)

            chapters.append(
                RawChapterListing(
                    source_chapter_id=chapter_id,
                    source_url=chapter_url,
                    chapter_number=chapter_number,
                    title=title,
                )
            )

        return chapters

    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, chapter_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title_el = (
            soup.select_one("h4.chapter-title")
            or soup.select_one(".chapter-title")
            or soup.select_one("h1")
        )
        title = _text(title_el)

        # WuxiaWorld wraps chapter content in div.fr-view
        content_el = soup.select_one("div.fr-view") or soup.select_one(
            ".chapter-content"
        )
        raw_html = str(content_el) if content_el else ""

        chapter_id = chapter_url.rstrip("/").split("/")[-1]
        chapter_number = _parse_chapter_number(title, chapter_url) or 0.0

        return RawChapterContent(
            source_chapter_id=chapter_id,
            source_url=chapter_url,
            chapter_number=chapter_number,
            title=title,
            raw_content=raw_html,
            content_format="html",
        )


# ── helpers ───────────────────────────────────────────────────────────────────

def _text(el: Tag | None) -> str | None:
    if el is None:
        return None
    t = el.get_text(strip=True)
    return t or None


def _inner_text(el: Tag | None) -> str | None:
    if el is None:
        return None
    return el.get_text(separator="\n", strip=True) or None


def _parse_chapter_number(title: str | None, url: str = "") -> float | None:
    for text in (title or "", url):
        m = _CHAPTER_NUM_RE.search(text)
        if m:
            return float(m.group(1))
    return None
