"""Wuxia.city source adapter (wuxia.city).

Wuxia.city is a wuxia-focused CN TL aggregator with a clean interface.

Selectors from lncrawl:
- Title: h1.book-name
- Cover: div.book-img img
- Author: dl.author dd
- Chapter list: ul.chapters li.oneline
- Content: div.chapter-content
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
)
from novara.ingestion.base_adapter import (
    BaseAdapter,
    RawChapterContent,
    RawChapterListing,
    RawMetadata,
)
from novara.ingestion.http_client import fetch_with_retry, rate_limited_client
from novara.ingestion.registry import register

_SLUG_RE = re.compile(r"wuxia\.city/book/([^/?#]+)")


@register
class WuxiaCityAdapter(BaseAdapter):
    SITE_KEY = "wuxiacity"
    SITE_NAME = "Wuxia.city"
    BASE_URL = "https://wuxia.city"
    REQUESTS_PER_SECOND = 1.0

    def extract_source_id(self, source_url: str) -> str:
        m = _SLUG_RE.search(source_url)
        return m.group(1) if m else source_url

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title = text(soup.select_one("h1.book-name, h1"))
        cover = find_cover(soup, "div.book-img img", ".cover img")
        author = text(soup.select_one("dl.author dd, .author a"))
        status_el = soup.select_one("dl.status dd, .status")
        status = normalise_status(text(status_el))
        genres = [text(a) for a in soup.select("a[href*='/genre/'], .genres a") if text(a)]
        synopsis = inner_text(soup.select_one(".description, .summary, .book-desc"))

        return RawMetadata(
            title=title,
            synopsis=synopsis,
            author=author,
            status=status,
            language="en",
            original_language="zh",
            genres=genres or [],
            cover_url=cover,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")
        chapters: list[RawChapterListing] = []

        for li in soup.select("ul.chapters li.oneline"):
            if not isinstance(li, Tag):
                continue
            link = li.select_one("a[href]")
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

        return chapters

    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, chapter_url)

        soup = BeautifulSoup(resp.text, "lxml")
        title = text(soup.select_one("h1, .chapter-title"))
        content_el = soup.select_one("div.chapter-content, .chapter-text")
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
