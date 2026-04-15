"""NovelFull template — shared base for novelfull.com and its mirrors.

Many aggregator sites (novelfull.com, novelbin.com, allnovelfull.com, etc.)
use nearly identical HTML structure. This base class captures that shared
structure so individual adapters only need to override constants.
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
    find_next_page,
)
from novara.ingestion.base_adapter import (
    BaseAdapter,
    RawChapterContent,
    RawChapterListing,
    RawMetadata,
)
from novara.ingestion.http_client import fetch_with_retry, rate_limited_client

_NOVEL_ID_RE = re.compile(r"/([^/?#]+?)(?:\.html)?/?$")


class NovelFullTemplate(BaseAdapter):
    """Shared scraping logic for NovelFull-family sites.

    Subclasses set SITE_KEY, SITE_NAME, BASE_URL.
    Override selectors dict to customise per-site.
    """

    REQUESTS_PER_SECOND = 1.0

    # Selectors — override in subclass if a mirror differs
    SEL_TITLE = "h3.title"
    SEL_COVER = ".book img"
    SEL_AUTHOR = "div.info a[href*='author']"
    SEL_STATUS = "div.info a[href*='status']"
    SEL_GENRES = "div.info a[href*='genre']"
    SEL_SYNOPSIS = "div.desc-text"
    SEL_CHAPTER_LIST = "ul.list-chapter li a"
    SEL_CONTENT = "div#chapter-content"

    def extract_source_id(self, source_url: str) -> str:
        m = _NOVEL_ID_RE.search(source_url.rstrip("/"))
        return m.group(1) if m else source_url

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title = text(soup.select_one(self.SEL_TITLE))
        cover = find_cover(soup, self.SEL_COVER)
        author_el = soup.select_one(self.SEL_AUTHOR)
        author = text(author_el)
        status_el = soup.select_one(self.SEL_STATUS)
        status = normalise_status(text(status_el))
        genres = [text(a) for a in soup.select(self.SEL_GENRES) if text(a)]
        synopsis = inner_text(soup.select_one(self.SEL_SYNOPSIS))

        # Total chapters from "X chapters" badge
        total = None
        for el in soup.select("li, span"):
            t = text(el) or ""
            m = re.search(r"([\d,]+)\s+chapters?", t, re.IGNORECASE)
            if m:
                try:
                    total = int(m.group(1).replace(",", ""))
                    break
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
            cover_url=cover,
            total_chapters=total,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        chapters: list[RawChapterListing] = []
        page_url: str | None = source_url
        page_num = 1

        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            while page_url:
                resp = await fetch_with_retry(client, page_url)
                soup = BeautifulSoup(resp.text, "lxml")

                for link in soup.select(self.SEL_CHAPTER_LIST):
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
                if page_num > 200:  # safety cap
                    break

        return chapters

    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, chapter_url)

        soup = BeautifulSoup(resp.text, "lxml")
        title_el = soup.select_one("h2, .chapter-title, h1")
        title = text(title_el)
        content_el = soup.select_one(self.SEL_CONTENT)
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
