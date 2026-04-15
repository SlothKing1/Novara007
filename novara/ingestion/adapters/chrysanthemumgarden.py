"""Chrysanthemum Garden source adapter (chrysanthemumgarden.com).

CG is a BL/danmei-focused translation group site. Clean structure, good
metadata, professional quality translations.

Characteristics:
- Good metadata: title, author, cover, genres
- Content uses a text descrambling system (span.jum elements contain scrambled
  characters — lncrawl handles this; we capture raw HTML and let the cleaner
  handle what it can)
- Chapter list in .chapter-item a
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from novara.ingestion.adapter_utils import (
    absolute_url,
    attr,
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

_SLUG_RE = re.compile(r"chrysanthemumgarden\.com/novel/([^/?#]+)")


@register
class ChrysanthemumGardenAdapter(BaseAdapter):
    SITE_KEY = "chrysanthemumgarden"
    SITE_NAME = "Chrysanthemum Garden"
    BASE_URL = "https://chrysanthemumgarden.com"
    REQUESTS_PER_SECOND = 0.5

    def extract_source_id(self, source_url: str) -> str:
        m = _SLUG_RE.search(source_url)
        return m.group(1) if m else source_url

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title = text(soup.select_one("h1.novel-title"))
        cover = find_cover(soup, ".novel-cover img")
        if cover is None:
            # CG uses data-breeze for lazy loading
            img = soup.select_one(".novel-cover img")
            if isinstance(img, Tag):
                cover = attr(img, "data-breeze", "data-src", "src")

        # Author: look for "Author: <name>" in .novel-info
        author = None
        for el in soup.select(".novel-info li, .novel-details li"):
            t = text(el) or ""
            if t.lower().startswith("author"):
                author = t.split(":", 1)[-1].strip() if ":" in t else None
                break

        # Translator group
        translator = None
        for el in soup.select(".novel-info li, .novel-details li"):
            t = text(el) or ""
            if "translat" in t.lower():
                translator = t.split(":", 1)[-1].strip() if ":" in t else None
                break

        genres = [text(a) for a in soup.select(".genres a, .tags a") if text(a)]
        synopsis = inner_text(soup.select_one(".summary, .description, .entry-content"))
        status_el = soup.select_one(".status, [class*='status']")
        status = normalise_status(text(status_el))

        return RawMetadata(
            title=title,
            synopsis=synopsis,
            author=author,
            translator_group=translator,
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

        for idx, link in enumerate(soup.select(".chapter-item a"), start=1):
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
        content_el = soup.select_one("#novel-content, .entry-content, .chapter-content")

        # Remove hidden zero-width spans used for text scrambling
        if content_el:
            for span in content_el.select("span[style*='width:0'], span.jum"):
                span.decompose()

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
