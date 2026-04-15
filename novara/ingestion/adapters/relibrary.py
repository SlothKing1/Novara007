"""Re:Library source adapter (re-library.com).

Re:Library is a professional translation group focused on fantasy and
gender-bender light novels, primarily from Japanese sources.

Characteristics:
- Good metadata: title, cover, author
- Chapter list via .page_item > a (WordPress page hierarchy)
- Content in .entry-content
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from novara.ingestion.adapter_utils import (
    absolute_url,
    find_cover,
    inner_text,
    parse_chapter_number,
    text,
)
from novara.ingestion.base_adapter import (
    BaseAdapter,
    RawChapterContent,
    RawChapterListing,
    RawMetadata,
)
from novara.ingestion.http_client import fetch_with_retry, rate_limited_client
from novara.ingestion.registry import register

_SLUG_RE = re.compile(r"re-library\.com/(?:translations|novels)/([^/?#]+)")


@register
class ReLibraryAdapter(BaseAdapter):
    SITE_KEY = "relibrary"
    SITE_NAME = "Re:Library"
    BASE_URL = "https://re-library.com"
    REQUESTS_PER_SECOND = 0.5

    def extract_source_id(self, source_url: str) -> str:
        m = _SLUG_RE.search(source_url)
        return m.group(1) if m else source_url

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title = text(soup.select_one(".entry-title, h1"))
        cover = find_cover(soup, ".entry-content table img", ".featured-image img")

        # Author: linked from /nauthor/ path
        author_el = soup.select_one("a[href*='/nauthor/']")
        author = text(author_el)

        # Translator
        trans_el = soup.select_one("a[href*='/ntranslator/']")
        translator = text(trans_el)

        # Synopsis: first few paragraphs of entry-content before the chapter list
        synopsis_el = soup.select_one(".entry-content")
        synopsis = inner_text(synopsis_el)
        if synopsis and len(synopsis) > 1000:
            synopsis = synopsis[:1000] + "…"

        genres = [text(a) for a in soup.select("a[href*='/genre/'], a[href*='/ngenre/']") if text(a)]

        return RawMetadata(
            title=title,
            synopsis=synopsis,
            author=author,
            translator_group=translator,
            language="en",
            original_language="ja",
            genres=genres or [],
            cover_url=cover,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")
        chapters: list[RawChapterListing] = []

        for idx, link in enumerate(soup.select(".page_item > a, .entry-content a[href]"), start=1):
            if not isinstance(link, Tag):
                continue
            href = str(link.get("href", ""))
            # Only chapter links (filter out external, author, tag links)
            if not href or "re-library.com" not in href:
                continue
            chapter_title = text(link)
            chapter_num = parse_chapter_number(chapter_title, href) or float(idx)
            chapter_id = href.rstrip("/").split("/")[-1] or str(idx)
            chapters.append(RawChapterListing(
                source_chapter_id=chapter_id,
                source_url=href,
                chapter_number=chapter_num,
                title=chapter_title,
            ))

        return chapters

    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, chapter_url)

        soup = BeautifulSoup(resp.text, "lxml")
        title = text(soup.select_one(".entry-title, h1"))
        content_el = soup.select_one(".entry-content")

        # Remove navigation and share buttons
        if content_el:
            for el in content_el.select(".sharedaddy, .navigation, nav, .wpcnt"):
                el.decompose()

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
