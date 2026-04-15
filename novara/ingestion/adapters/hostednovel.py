"""HostedNovel source adapter (hostednovel.com).

HostedNovel is a clean platform for original English web fiction.

Characteristics:
- Good metadata: title, author, cover via section[aria-labelledby]
- Chapter list in #chapters ul[role="list"] li a
- Content in .chapter div
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

_SLUG_RE = re.compile(r"hostednovel\.com/novels/([^/?#]+)")


@register
class HostedNovelAdapter(BaseAdapter):
    SITE_KEY = "hostednovel"
    SITE_NAME = "Hosted Novel"
    BASE_URL = "https://hostednovel.com"
    REQUESTS_PER_SECOND = 1.0

    def extract_source_id(self, source_url: str) -> str:
        m = _SLUG_RE.search(source_url)
        return m.group(1) if m else source_url

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title = text(soup.select_one(".text-center h1.font-extrabold, h1"))

        # Details section
        details = soup.select_one('section[aria-labelledby="novel-details-heading"]')
        cover = None
        author = None
        status = None

        if details:
            img = details.select_one("img[src]")
            if isinstance(img, Tag):
                cover = attr(img, "src", "data-src")

            # Author: dt/dd pairs
            for dt in details.select("dt"):
                if "author" in (text(dt) or "").lower():
                    dd = dt.find_next_sibling("dd")
                    if dd:
                        author = text(dd)  # type: ignore[arg-type]
                if "status" in (text(dt) or "").lower():
                    dd = dt.find_next_sibling("dd")
                    if dd:
                        status = normalise_status(text(dd))  # type: ignore[arg-type]

        synopsis = inner_text(soup.select_one(".synopsis, .description, .summary"))
        genres = [text(a) for a in soup.select("a[href*='/genres/']") if text(a)]

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
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")
        chapters: list[RawChapterListing] = []

        for idx, link in enumerate(
            soup.select('#chapters ul[role="list"] li a[href]'),
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
            chapter_id = href.rstrip("/").split("/")[-1] or str(idx)
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
        content_el = soup.select_one(".chapter, .chapter-content, article")
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
