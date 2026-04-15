"""Ranobes source adapter (ranobes.net / ranobes.top).

Ranobes is a Russian-origin aggregator with a large catalog of CN and KR
light novel translations in English and Russian.

Characteristics:
- Good cover and basic metadata
- Synopsis from JSON embedded in page (window.__DATA__)
- Chapter list via paginated /chapters/ endpoint
- Content in div#arrticle
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup, Tag

from novara.ingestion.adapter_utils import (
    absolute_url,
    find_cover,
    find_next_page,
    inner_text,
    normalise_status,
    parse_chapter_number,
    text,
    attr,
)
from novara.ingestion.base_adapter import (
    BaseAdapter,
    RawChapterContent,
    RawChapterListing,
    RawMetadata,
)
from novara.ingestion.http_client import fetch_with_retry, rate_limited_client
from novara.ingestion.registry import register

_NOVEL_ID_RE = re.compile(r"/(\d+)-[^/]+\.html")
_WINDOW_DATA_RE = re.compile(r"window\.__DATA__\s*=\s*(\{.+?\});", re.DOTALL)


@register
class RanobesAdapter(BaseAdapter):
    SITE_KEY = "ranobes"
    SITE_NAME = "Ranobes"
    BASE_URL = "https://ranobes.net"
    REQUESTS_PER_SECOND = 0.5

    def extract_source_id(self, source_url: str) -> str:
        m = _NOVEL_ID_RE.search(source_url)
        return m.group(1) if m else source_url

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title = text(soup.select_one("h1.title, h1"))
        cover = find_cover(soup, ".r-fullstory-poster .poster a img", ".cover img")
        author_el = soup.select_one(".tag_list a[href*='/authors/'], a[href*='/author/']")
        author = text(author_el)

        # Synopsis: try JSON data first, fall back to HTML
        synopsis = _extract_synopsis_from_json(resp.text)
        if not synopsis:
            synopsis = inner_text(soup.select_one(".r-fullstory-description, .description"))

        status_el = soup.select_one(".r-fullstory-pageinfo, .status")
        status = None
        if status_el:
            for span in status_el.select("span, li"):
                t = text(span) or ""
                if any(word in t.lower() for word in ("ongoing", "completed", "hiatus", "active")):
                    status = normalise_status(t)
                    break

        genres = [text(a) for a in soup.select(".tag_list a[href*='/genre/']") if text(a)]

        return RawMetadata(
            title=title,
            synopsis=synopsis,
            author=author,
            status=status,
            language="en",
            genres=genres or [],
            cover_url=cover,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        novel_id = self.extract_source_id(source_url)
        chapters: list[RawChapterListing] = []
        page_num = 1

        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            while True:
                chapters_url = f"{self.BASE_URL}/chapters/{novel_id}/page/{page_num}/"
                resp = await fetch_with_retry(client, chapters_url)
                if resp.status_code == 404:
                    break
                soup = BeautifulSoup(resp.text, "lxml")

                links = soup.select(".cat_line a, .chapter-row a")
                if not links:
                    break

                for link in links:
                    if not isinstance(link, Tag):
                        continue
                    href = str(link.get("href", ""))
                    if not href:
                        continue
                    chapter_url = absolute_url(self.BASE_URL, href)
                    chapter_title = text(link)
                    chapter_num = parse_chapter_number(chapter_title, href) or float(len(chapters) + 1)
                    chapter_id = href.rstrip("/").split("/")[-1] or str(len(chapters) + 1)
                    chapters.append(RawChapterListing(
                        source_chapter_id=chapter_id,
                        source_url=chapter_url,
                        chapter_number=chapter_num,
                        title=chapter_title,
                    ))

                if not find_next_page(soup, chapters_url):
                    break
                page_num += 1
                if page_num > 200:
                    break

        return chapters

    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, chapter_url)

        soup = BeautifulSoup(resp.text, "lxml")
        title = text(soup.select_one("h1, .chapter-title"))
        content_el = soup.select_one("div#arrticle, div.chapter-content")
        raw_html = str(content_el) if content_el else ""
        chapter_id = chapter_url.rstrip("/").split("/")[-1]
        chapter_num = parse_chapter_number(title, chapter_url) or 0.0

        return RawChapterContent(
            source_chapter_id=chapter_id,
            source_url=chapter_url,
            chapter_number=chapter_num,
            title=title,
            raw_content=raw_html,
            content_format="html",
        )


def _extract_synopsis_from_json(html: str) -> str | None:
    m = _WINDOW_DATA_RE.search(html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
        return data.get("description") or data.get("summary")
    except (json.JSONDecodeError, KeyError):
        return None
