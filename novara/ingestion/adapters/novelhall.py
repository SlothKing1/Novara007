"""NovelHall source adapter (novelhall.com).

NovelHall is a CN TL aggregator with a good chapter volume.

Selectors from lncrawl:
- Title: div.book-info h1
- Synopsis: .js-close-wrap (remove nested .blue)
- Cover: div.book-img img[src]
- Author: .booktag span.blue (search for "Author：")
- Chapter list: #morelist.book-catalog ul li a[href]
- Content: div#htmlContent.entry-content
"""

from __future__ import annotations

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
)
from novara.ingestion.base_adapter import (
    BaseAdapter,
    RawChapterContent,
    RawChapterListing,
    RawMetadata,
)
from novara.ingestion.http_client import fetch_with_retry, rate_limited_client
from novara.ingestion.registry import register

_NOVEL_ID_RE = re.compile(r"/novel/(\d+)\.html")


@register
class NovelHallAdapter(BaseAdapter):
    SITE_KEY = "novelhall"
    SITE_NAME = "Novel Hall"
    BASE_URL = "https://www.novelhall.com"
    REQUESTS_PER_SECOND = 1.0

    def extract_source_id(self, source_url: str) -> str:
        m = _NOVEL_ID_RE.search(source_url)
        return m.group(1) if m else source_url

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title = text(soup.select_one("div.book-info h1, h1"))
        cover = find_cover(soup, "div.book-img img[src]", ".cover img")

        # Author: find span.blue inside .booktag that's after an "Author" label
        author = None
        for span in soup.select(".booktag span.blue"):
            prev = span.find_previous_sibling()
            prev_text = (text(prev) or "").lower()  # type: ignore[arg-type]
            if "author" in prev_text:
                author = text(span)
                break

        # Status: same pattern
        status = None
        for span in soup.select(".booktag span.blue"):
            prev = span.find_previous_sibling()
            prev_text = (text(prev) or "").lower()  # type: ignore[arg-type]
            if "status" in prev_text:
                status = normalise_status(text(span))
                break

        # Synopsis: .js-close-wrap, remove nested .blue (which is "Read more")
        synopsis_el = soup.select_one(".js-close-wrap, .description")
        if synopsis_el:
            for blue in synopsis_el.select(".blue"):
                blue.decompose()
        synopsis = inner_text(synopsis_el)

        genres = [text(a) for a in soup.select("a[href*='/genre/'], a[href*='/category/']") if text(a)]

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
        chapters: list[RawChapterListing] = []

        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        for link in soup.select("#morelist.book-catalog ul li a[href], .chapter-list li a"):
            if not isinstance(link, Tag):
                continue
            href = str(link.get("href", ""))
            if not href:
                continue
            chapter_url = absolute_url(self.BASE_URL, href)
            chapter_title = text(link)
            chapter_num = parse_chapter_number(chapter_title, href) or float(len(chapters) + 1)
            chapter_id = href.rstrip("/").split("/")[-1]
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
        content_el = soup.select_one("div#htmlContent.entry-content, div.chapter-content")
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
