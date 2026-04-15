"""Wattpad source adapter (wattpad.com).

Wattpad hosts over 1 billion story parts from 90M+ users.  It's primarily
user-generated fiction across all genres.

The site has a React/Next.js frontend; most metadata is in the HTML but
multi-page chapters require fetching all pages.  We use:
  - REST API (/api/v3/stories/{id}) for chapter listing (stable, no JS needed)
  - HTML scraping for chapter content (p[data-p-id] paragraphs)

Selectors from WebToEpub WattpadParser.js + Wattpad API docs:
- Title:    div.story-info span.sr-only  (or og:title meta)
- Author:   a[href*='/user/'] near story info
- Cover:    div[data-testid='cover'] img  (or og:image meta)
- Synopsis: div.glL-c  (dynamic class — og:description is the fallback)
- TOC:      ul.table-of-contents a  (HTML) or /api/v3/stories/{id}/parts
- Content:  p[data-p-id]  inside div[data-page-number]
- ChTitle:  h1.h2 on chapter page

Note: Wattpad uses generated CSS class names that change over time.
The adapter prefers data attributes and stable semantic selectors with
Open Graph meta fallbacks for fragile fields.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from novara.ingestion.adapter_utils import (
    absolute_url,
    attr,
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

_STORY_ID_RE = re.compile(r"/story/(\d+)")
_PART_ID_RE = re.compile(r"wattpad\.com/(\d+)-")


@register
class WattpadAdapter(BaseAdapter):
    SITE_KEY = "wattpad"
    SITE_NAME = "Wattpad"
    BASE_URL = "https://www.wattpad.com"
    REQUESTS_PER_SECOND = 0.5  # Wattpad rate-limits aggressively

    def extract_source_id(self, source_url: str) -> str:
        m = _STORY_ID_RE.search(source_url)
        return m.group(1) if m else source_url

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        # Prefer Open Graph meta for the most stable extraction
        def _og(prop: str) -> str | None:
            el = soup.select_one(f"meta[property='og:{prop}']")
            return attr(el, "content") if isinstance(el, Tag) else None

        title = (
            text(soup.select_one("div.story-info span.sr-only"))
            or text(soup.select_one("h1"))
            or _og("title")
        )

        # Author: look for user profile link
        author = text(soup.select_one("a[href*='/user/']"))

        cover = (
            attr(soup.select_one("div[data-testid='cover'] img"), "src", "data-src")
            or _og("image")
        )

        # Synopsis: try known selector, fall back to og:description
        synopsis_el = soup.select_one("pre.description, .description-text, .synopsis")
        synopsis = inner_text(synopsis_el) or _og("description")

        # Tags/genres from tag links
        tags = [text(a) for a in soup.select("ul.tag-items a, a[href*='/stories/']") if text(a)]

        return RawMetadata(
            title=title,
            synopsis=synopsis,
            author=author,
            status=None,
            language="en",
            genres=[],
            tags=tags,
            cover_url=cover,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        story_id = self.extract_source_id(source_url)

        # Wattpad v3 API returns structured chapter data
        api_url = f"{self.BASE_URL}/api/v3/stories/{story_id}?fields=parts(id,title,url)"
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            api_resp = await fetch_with_retry(client, api_url)

        try:
            data = api_resp.json()
            parts = data.get("parts", [])
        except Exception:
            parts = []

        if parts:
            chapters: list[RawChapterListing] = []
            for idx, part in enumerate(parts, start=1):
                part_id = str(part.get("id", idx))
                part_title = part.get("title") or f"Chapter {idx}"
                part_url = part.get("url") or f"{self.BASE_URL}/{part_id}"
                if not part_url.startswith("http"):
                    part_url = absolute_url(self.BASE_URL, part_url)
                chapter_num = parse_chapter_number(part_title, part_url) or float(idx)
                chapters.append(RawChapterListing(
                    source_chapter_id=part_id,
                    source_url=part_url,
                    chapter_number=chapter_num,
                    title=part_title,
                ))
            return chapters

        # API fallback: scrape the HTML table of contents
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)
        soup = BeautifulSoup(resp.text, "lxml")

        chapters = []
        for idx, link in enumerate(
            soup.select("ul.table-of-contents a[href], .table-of-contents a"),
            start=1,
        ):
            if not isinstance(link, Tag):
                continue
            href = str(link.get("href", ""))
            if not href:
                continue
            chapter_url = absolute_url(self.BASE_URL, href)
            chapter_title = text(link)
            m = _PART_ID_RE.search(href)
            chapter_id = m.group(1) if m else str(idx)
            chapter_num = parse_chapter_number(chapter_title, href) or float(idx)
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

        # Chapter title
        title = text(soup.select_one("h1.h2, h1"))

        # Content: collect all p[data-p-id] — these are the canonical story paragraphs
        # Wattpad splits long chapters across multiple pages; page 1 is the default.
        # Each page URL is chapter_url?page=N
        paras = soup.select("p[data-p-id]")
        content_parts = [str(p) for p in paras]

        # Check for additional pages (Wattpad shows "Page X of Y")
        page_info = soup.select_one(".page-info, [class*='pageInfo']")
        if page_info:
            raw = text(page_info) or ""
            m = re.search(r"of\s+(\d+)", raw)
            if m:
                total_pages = int(m.group(1))
                async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
                    for page_num in range(2, total_pages + 1):
                        page_url = f"{chapter_url.split('?')[0]}?page={page_num}"
                        page_resp = await fetch_with_retry(client, page_url)
                        page_soup = BeautifulSoup(page_resp.text, "lxml")
                        content_parts.extend(
                            str(p) for p in page_soup.select("p[data-p-id]")
                        )

        raw_html = "\n".join(content_parts)

        m = _PART_ID_RE.search(chapter_url)
        chapter_id = m.group(1) if m else chapter_url.rstrip("/").split("/")[-1]
        chapter_num = parse_chapter_number(title, chapter_url) or 0.0

        return RawChapterContent(
            source_chapter_id=chapter_id,
            source_url=chapter_url,
            chapter_number=chapter_num,
            title=title,
            raw_content=raw_html,
            content_format="html",
        )
