"""FimFiction source adapter (fimfiction.net).

FimFiction is the primary archive for My Little Pony fanfiction and has a
large catalogue of original fiction as well.  It is a well-maintained,
modern platform with a stable HTML structure.

Selectors from WebToEpub FimfictionParser.js:
- Title:    a.story_name
- Author:   div.info-container a  (first link)
- Cover:    div.story_container__story_image img
- Synopsis: span.description-text
- Chapters: ul.chapters a.chapter-title
- Content:  div#chapter
  (remove h1.chapter-title div[style='float:right'] — word-count badge)
"""

from __future__ import annotations

import re

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

_STORY_ID_RE = re.compile(r"/story/(\d+)")
_CHAPTER_ID_RE = re.compile(r"/(\d+)/")


@register
class FimFictionAdapter(BaseAdapter):
    SITE_KEY = "fimfiction"
    SITE_NAME = "FimFiction"
    BASE_URL = "https://www.fimfiction.net"
    REQUESTS_PER_SECOND = 1.0

    def extract_source_id(self, source_url: str) -> str:
        m = _STORY_ID_RE.search(source_url)
        return m.group(1) if m else source_url

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title = text(soup.select_one("a.story_name"))

        # Author: first <a> inside .info-container
        author = text(soup.select_one("div.info-container a"))

        cover = find_cover(soup, "div.story_container__story_image img")

        synopsis = inner_text(soup.select_one("span.description-text"))

        # Status: FimFiction shows "Complete" or "Incomplete" badge
        status = None
        for badge in soup.select(".story_status, .completion-status"):
            raw = (text(badge) or "").lower()
            if "complete" in raw and "incomplete" not in raw:
                status = "completed"
            elif "incomplete" in raw or "in progress" in raw:
                status = "ongoing"
            elif "hiatus" in raw or "on hold" in raw:
                status = "hiatus"
            if status:
                break

        # Tags: content warnings, genres, and character tags
        tags = [text(t) for t in soup.select(".story-tag, .tag") if text(t)]
        genres = [text(a) for a in soup.select("a[href*='/stories?genre=']") if text(a)]

        # Total chapter count from word/chapter count row
        total = None
        chap_count_el = soup.select_one("span.chapter-count, .chapters span")
        if chap_count_el:
            raw = text(chap_count_el) or ""
            m = re.search(r"(\d+)", raw)
            if m:
                try:
                    total = int(m.group(1))
                except ValueError:
                    pass

        return RawMetadata(
            title=title,
            synopsis=synopsis,
            author=author,
            status=status,
            language="en",
            genres=genres,
            tags=tags,
            cover_url=cover,
            total_chapters=total,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")
        chapters: list[RawChapterListing] = []

        for idx, link in enumerate(soup.select("ul.chapters a.chapter-title"), start=1):
            if not isinstance(link, Tag):
                continue
            href = str(link.get("href", ""))
            if not href:
                continue
            chapter_url = absolute_url(self.BASE_URL, href)
            chapter_title = text(link)
            # FimFiction hrefs look like /story/12345/1/story-name/chapter-name
            m = re.search(r"/story/\d+/(\d+)/", href)
            chapter_id = m.group(1) if m else str(idx)
            chapter_num = float(chapter_id) if chapter_id.isdigit() else float(idx)
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

        # Chapter title: h1.chapter-title (remove the floating word-count badge)
        title_el = soup.select_one("h1.chapter-title")
        if title_el:
            badge = title_el.select_one("div[style*='float:right']")
            if badge:
                badge.decompose()
        title = text(title_el) or text(soup.select_one("a.story_name"))

        content_el = soup.select_one("div#chapter")
        raw_html = str(content_el) if content_el else ""

        m = re.search(r"/story/\d+/(\d+)/", chapter_url)
        chapter_id = m.group(1) if m else chapter_url.rstrip("/").split("/")[-1]
        chapter_num = float(chapter_id) if chapter_id.isdigit() else (
            parse_chapter_number(title, chapter_url) or 0.0
        )

        return RawChapterContent(
            source_chapter_id=chapter_id,
            source_url=chapter_url,
            chapter_number=chapter_num,
            title=title,
            raw_content=raw_html,
            content_format="html",
        )
