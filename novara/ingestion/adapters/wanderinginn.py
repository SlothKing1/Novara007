"""WanderingInn source adapter (wanderinginn.com).

The Wandering Inn is a single-author original English web serial by Pirateaba.
It is one of the longest-running and most popular web novels in English.

Characteristics:
- Excellent content quality — clean WordPress entry-content divs
- No translator (original English)
- Author is always "Pirateaba" (hardcoded)
- TOC organised into volumes with nested chapter links
- Very long chapters (5,000–20,000 words each)
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from novara.ingestion.adapter_utils import (
    absolute_url,
    attr,
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

_TOC_URL = "https://wanderinginn.com/table-of-contents/"


@register
class WanderingInnAdapter(BaseAdapter):
    SITE_KEY = "wanderinginn"
    SITE_NAME = "The Wandering Inn"
    BASE_URL = "https://wanderinginn.com"
    REQUESTS_PER_SECOND = 0.5  # be respectful to solo author site

    def extract_source_id(self, source_url: str) -> str:
        return "wanderinginn"  # single work

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title_el = soup.select_one("meta[property='og:site_name']")
        title = attr(title_el, "content") or "The Wandering Inn"

        cover_el = soup.select_one("meta[property='og:image']")
        cover = attr(cover_el, "content") or find_cover(soup, ".entry-content img")

        return RawMetadata(
            title=title,
            author="Pirateaba",
            language="en",
            original_language="en",
            version_type="original",  # type: ignore[call-arg]  # extra field ignored
            cover_url=cover,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, _TOC_URL)

        soup = BeautifulSoup(resp.text, "lxml")
        chapters: list[RawChapterListing] = []

        # TOC is structured as div blocks per volume containing chapter links
        toc = soup.select_one("div#table-of-contents, .entry-content")
        if not toc:
            return chapters

        for idx, link in enumerate(
            toc.select("a[href*='wanderinginn.com']"),
            start=1,
        ):
            if not isinstance(link, Tag):
                continue
            href = str(link.get("href", ""))
            if not href or "table-of-contents" in href:
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
        title = text(soup.select_one("h1.entry-title, h1"))
        content_el = soup.select_one("div.entry-content")

        # Remove navigation links at bottom
        if content_el:
            for nav in content_el.select("nav, .navigation, .sharedaddy, .wpcnt"):
                nav.decompose()

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
