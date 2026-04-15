"""ReadNovelFull source adapter (readnovelfull.com).

ReadNovelFull is a high-volume CN TL aggregator that shares the NovelFull
HTML structure.  It adds a server-side AJAX endpoint for the full chapter
archive which we prefer over paginating through TOC pages.

AJAX chapter archive: GET /ajax/chapter-archive?novelId={id}
Novel ID: data-novel-id attribute on div#rating (or div.rating)

Selectors from WebToEpub ReadNovelFullParser.js:
- Title:   h3.title
- Cover:   div.book img
- Author:  ul.info li:nth-of-type(2) a
- Desc:    div.desc-text
- Chapters (AJAX): returns HTML with ul.list-chapter li a
- Content: div#chr-content
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
from novara.ingestion.adapters._novelfull_template import NovelFullTemplate
from novara.ingestion.base_adapter import (
    RawChapterListing,
    RawMetadata,
)
from novara.ingestion.http_client import fetch_with_retry, rate_limited_client
from novara.ingestion.registry import register

_NOVEL_ID_RE = re.compile(r'data-novel-id=["\'](\d+)["\']')


@register
class ReadNovelFullAdapter(NovelFullTemplate):
    SITE_KEY = "readnovelfull"
    SITE_NAME = "Read Novel Full"
    BASE_URL = "https://readnovelfull.com"
    REQUESTS_PER_SECOND = 1.0

    # ReadNovelFull deviates slightly from vanilla NovelFull
    SEL_TITLE = "h3.title"
    SEL_AUTHOR = "ul.info li:nth-of-type(2) a"
    SEL_CHAPTER_LIST = "ul.list-chapter li a, #list-chapter li a"
    SEL_CONTENT = "div#chr-content, div#chapter-content"

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        """Use the AJAX chapter archive when available; fall back to pagination."""
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        html = resp.text
        soup = BeautifulSoup(html, "lxml")

        # Extract novel ID from data attribute on #rating or .rating
        novel_id: str | None = None
        rating_el = soup.select_one("div#rating, div.rating")
        if isinstance(rating_el, Tag):
            novel_id = str(rating_el.get("data-novel-id", "") or "")
        if not novel_id:
            m = _NOVEL_ID_RE.search(html)
            novel_id = m.group(1) if m else None

        chapters: list[RawChapterListing] = []

        if novel_id:
            async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
                ajax_url = f"{self.BASE_URL}/ajax/chapter-archive?novelId={novel_id}"
                archive_resp = await fetch_with_retry(client, ajax_url)
            archive_soup = BeautifulSoup(archive_resp.text, "lxml")
            for link in archive_soup.select(self.SEL_CHAPTER_LIST):
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
            if chapters:
                return chapters

        # AJAX failed — fall back to NovelFullTemplate pagination
        return await super().scrape_chapter_listing(source_url)
