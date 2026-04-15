"""RoyalRoad source adapter.

RoyalRoad (royalroad.com) is a major English-language web fiction platform.
It uses a consistent HTML structure and provides good metadata.

Characteristics:
- Strong metadata: title, author, status, tags, cover
- Good chapter structure: clean HTML with one content div
- Chapters paginated in a single table on the title page
- Chapter IDs are numeric (/fiction/<fid>/chapter/<cid>/...)
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

_CHAPTER_ID_RE = re.compile(r"/chapter/(\d+)/")
_FICTION_ID_RE = re.compile(r"/fiction/(\d+)")


@register
class RoyalRoadAdapter(BaseAdapter):
    SITE_KEY = "royalroad"
    SITE_NAME = "Royal Road"
    BASE_URL = "https://www.royalroad.com"

    # RoyalRoad is lenient with crawlers — 1 req/s is safe
    REQUESTS_PER_SECOND = 1.0

    def extract_source_id(self, source_url: str) -> str:
        m = _FICTION_ID_RE.search(source_url)
        return m.group(1) if m else source_url

    def normalise_status(self, raw: str) -> str:
        mapping = {
            "ongoing": "ongoing",
            "complete": "completed",
            "hiatus": "hiatus",
            "dropped": "dropped",
            "stub": "dropped",
        }
        return mapping.get(raw.lower().strip(), raw.lower().strip())

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title = _text(soup.select_one("h1.font-white"))
        author = _text(soup.select_one("span[property='name']"))

        # Synopsis: the div with class "description" or the first .synopsis
        synopsis_el = soup.select_one(".description .description-content") or soup.select_one(
            ".description"
        )
        synopsis = _inner_text(synopsis_el)

        # Status tag
        status_raw = None
        for label in soup.select(".label"):
            t = label.get_text(strip=True).lower()
            if t in {"ongoing", "complete", "hiatus", "dropped", "stub"}:
                status_raw = self.normalise_status(t)
                break

        # Genres and tags
        genres: list[str] = []
        tags: list[str] = []
        for a in soup.select("a.label"):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if "genre" in str(href):
                genres.append(text)
            elif "tag" in str(href):
                tags.append(text)

        # Cover image
        cover = None
        img = soup.select_one(".thumbnail img") or soup.select_one("img.thumbnail")
        if isinstance(img, Tag):
            cover = str(img.get("src", "") or img.get("data-src", ""))

        # Total chapters from the chapter table row count
        chapter_rows = soup.select("table#chapters tbody tr")
        total = len(chapter_rows) if chapter_rows else None

        return RawMetadata(
            title=title,
            synopsis=synopsis,
            author=author,
            status=status_raw,
            language="en",
            original_language=None,  # RoyalRoad hosts original English fiction
            genres=genres,
            tags=tags,
            cover_url=cover,
            total_chapters=total,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")
        rows = soup.select("table#chapters tbody tr")

        chapters: list[RawChapterListing] = []
        for idx, row in enumerate(rows, start=1):
            link = row.select_one("a[href*='/chapter/']")
            if not isinstance(link, Tag):
                continue
            href = str(link.get("href", ""))
            chapter_url = href if href.startswith("http") else self.BASE_URL + href

            m = _CHAPTER_ID_RE.search(href)
            chapter_id = m.group(1) if m else href

            title = link.get_text(strip=True) or None

            # Parse chapter number from title or fall back to index
            chapter_number = _parse_chapter_number(title) or float(idx)

            # Release date (data-content attribute on a time element)
            time_el = row.select_one("time")
            release_date: str | None = None
            if isinstance(time_el, Tag):
                release_date = str(time_el.get("datetime", "") or "")

            chapters.append(
                RawChapterListing(
                    source_chapter_id=chapter_id,
                    source_url=chapter_url,
                    chapter_number=chapter_number,
                    title=title,
                    release_date=release_date or None,
                )
            )

        return chapters

    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, chapter_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title_el = soup.select_one("h1") or soup.select_one(".chapter-title")
        title = _text(title_el)

        # RoyalRoad puts chapter content in div.chapter-content
        content_el = soup.select_one("div.chapter-content")
        raw_html = str(content_el) if content_el else ""

        m = _CHAPTER_ID_RE.search(chapter_url)
        chapter_id = m.group(1) if m else chapter_url
        chapter_number = _parse_chapter_number(title) or 0.0

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
    t = el.get_text(separator="\n", strip=True)
    return t or None


_CHAPTER_NUM_RE = re.compile(r"chapter\s+(\d+(?:\.\d+)?)", re.IGNORECASE)


def _parse_chapter_number(title: str | None) -> float | None:
    if not title:
        return None
    m = _CHAPTER_NUM_RE.search(title)
    if m:
        return float(m.group(1))
    return None
