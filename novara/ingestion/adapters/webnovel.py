"""WebNovel source adapter (webnovel.com / m.webnovel.com).

WebNovel is Qidian International's platform — the largest CN TL catalog.

Characteristics:
- Strong metadata via HTML meta tags and structured data
- Chapter list requires login for premium content; free chapters are accessible
- Content requires JS rendering for some chapters — free chapters work with httpx
- NEEDS_CLOUDSCRAPER: False (basic anti-bot, httpx + correct headers works)
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from novara.ingestion.adapter_utils import (
    absolute_url,
    find_cover,
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

_BOOK_ID_RE = re.compile(r"webnovel\.com/book/[^/]+_(\d+)")
_CHAPTER_ID_RE = re.compile(r"/(\d+)$")


@register
class WebNovelAdapter(BaseAdapter):
    SITE_KEY = "webnovel"
    SITE_NAME = "WebNovel"
    BASE_URL = "https://www.webnovel.com"
    REQUESTS_PER_SECOND = 0.5  # polite to Qidian

    def extract_source_id(self, source_url: str) -> str:
        m = _BOOK_ID_RE.search(source_url)
        return m.group(1) if m else source_url

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        # Title from og:title or h1
        og_title = attr(soup.select_one("meta[property='og:title']"), "content")
        title = og_title or text(soup.select_one("h1"))

        # Cover from og:image
        og_image = attr(soup.select_one("meta[property='og:image']"), "content")
        cover = og_image or find_cover(soup, ".g_thumb img", ".book-cover img")

        # Synopsis from og:description or description div
        og_desc = attr(soup.select_one("meta[property='og:description']"), "content")
        synopsis = og_desc or inner_text(soup.select_one(
            "p.detail, .description, div[class*='Desc']"
        ))

        # Author
        author = text(soup.select_one("address a, .author-name a, span.name"))

        # Status
        status_el = soup.select_one("span[class*='Status'], .tag-status")
        status = normalise_status(text(status_el))

        # Genres / tags
        genres = [text(a) for a in soup.select("a[href*='/genre/']") if text(a)]
        tags = [text(a) for a in soup.select("a[href*='/tags/']") if text(a)]

        # Chapter count
        total = None
        count_el = soup.select_one("span[class*='chapter'] strong, [class*='chapterTotal']")
        if count_el:
            try:
                total = int(re.sub(r"[^\d]", "", text(count_el) or ""))
            except ValueError:
                pass

        return RawMetadata(
            title=title,
            synopsis=synopsis,
            author=author,
            status=status,
            language="en",
            original_language="zh",
            genres=genres or [],
            tags=tags or [],
            cover_url=cover,
            total_chapters=total,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        """Fetch free chapter list from the catalog page."""
        chapters: list[RawChapterListing] = []

        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        # Chapter links are in the catalog — free chapters have data-id
        for idx, link in enumerate(
            soup.select(".j_catalog_list li a, .catalog-list li a, .chapter-list li a"),
            start=1,
        ):
            if not isinstance(link, Tag):
                continue
            href = str(link.get("href", ""))
            if not href:
                continue
            chapter_url = absolute_url(self.BASE_URL, href)
            chapter_title = text(link)
            chapter_num = parse_chapter_number(chapter_title, href) or float(idx)
            m = _CHAPTER_ID_RE.search(href)
            chapter_id = m.group(1) if m else str(idx)
            chapters.append(RawChapterListing(
                source_chapter_id=chapter_id,
                source_url=chapter_url,
                chapter_number=chapter_num,
                title=chapter_title,
            ))

        return chapters

    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, chapter_url)

        soup = BeautifulSoup(resp.text, "lxml")
        title = text(soup.select_one("h1, .chapter-title, [class*='chapterTitle']"))
        content_el = (
            soup.select_one("div[class*='chapter-content'], div.content, div[class*='Content']")
        )
        raw_html = str(content_el) if content_el else ""
        m = _CHAPTER_ID_RE.search(chapter_url)
        chapter_id = m.group(1) if m else chapter_url
        chapter_num = parse_chapter_number(title, chapter_url) or 0.0

        return RawChapterContent(
            source_chapter_id=chapter_id,
            source_url=chapter_url,
            chapter_number=chapter_num,
            title=title,
            raw_content=raw_html,
            content_format="html",
        )
