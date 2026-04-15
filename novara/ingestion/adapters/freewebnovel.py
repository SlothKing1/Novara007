"""FreeWebNovel source adapter (freewebnovel.com).

FreeWebNovel is a large aggregator with CN and KR translations.

Selectors from lncrawl:
- Title: .m-desc h1.tit
- Cover: .m-imgtxt img
- Author: .m-imgtxt a[href*='/authors/']
- Chapter list: #idData li > a
- Content: .m-read .txt
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

_SLUG_RE = re.compile(r"freewebnovel\.com/([^/?#]+?)(?:\.html)?/?$")


@register
class FreeWebNovelAdapter(BaseAdapter):
    SITE_KEY = "freewebnovel"
    SITE_NAME = "FreeWebNovel"
    BASE_URL = "https://freewebnovel.com"
    REQUESTS_PER_SECOND = 1.0

    def extract_source_id(self, source_url: str) -> str:
        m = _SLUG_RE.search(source_url.rstrip("/"))
        return m.group(1) if m else source_url

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title = text(soup.select_one(".m-desc h1.tit, h1"))
        cover = find_cover(soup, ".m-imgtxt img", ".book-cover img")
        author = text(soup.select_one(".m-imgtxt a[href*='/authors/'], .author a"))
        status_el = soup.select_one(".m-desc .txt span, .status")
        status = normalise_status(text(status_el))
        genres = [text(a) for a in soup.select("a[href*='/genre/']") if text(a)]
        synopsis = inner_text(soup.select_one(".m-desc .txt, .description"))

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
        page_url: str | None = source_url
        page_num = 1

        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            while page_url:
                resp = await fetch_with_retry(client, page_url)
                soup = BeautifulSoup(resp.text, "lxml")

                for link in soup.select("#idData li > a, .chapter-list li a"):
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

                page_url = find_next_page(soup, page_url)
                page_num += 1
                if page_num > 200:
                    break

        return chapters

    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, chapter_url)

        soup = BeautifulSoup(resp.text, "lxml")
        title = text(soup.select_one("h1, .chapter-title"))
        content_el = soup.select_one(".m-read .txt, .chapter-content")
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
