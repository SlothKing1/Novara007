"""FanFiction.net source adapter (fanfiction.net / fictionpress.com).

FanFiction.net is one of the largest fanfiction archives.  FictionPress is its
sister site for original fiction — both share the same HTML structure.

Selectors from WebToEpub FanFictionParser.js:
- Title: div#profile_top b
- Author: div#profile_top a (first link)
- Cover: div#img_large img[data-original]
- Synopsis: div#profile_top div.xcontrast_txt
- Chapter list: select#chap_select option  (dropdown; single-chapter has none)
- Content: div.storytext

Story URL format: /s/{story_id}/{chapter_num}/{title_slug}
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

_STORY_ID_RE = re.compile(r"/s/(\d+)")
_CHAPTER_URL_RE = re.compile(r"/s/(\d+)/(\d+)/([^/?#]*)")


@register
class FanFictionAdapter(BaseAdapter):
    SITE_KEY = "fanfiction"
    SITE_NAME = "FanFiction.net"
    BASE_URL = "https://www.fanfiction.net"
    REQUESTS_PER_SECOND = 0.5  # be polite; FF.net is volunteer-run

    def extract_source_id(self, source_url: str) -> str:
        m = _STORY_ID_RE.search(source_url)
        return m.group(1) if m else source_url

    async def scrape_title(self, source_url: str) -> RawMetadata:
        # Force to chapter 1 of the story for the metadata page
        story_url = _story_base_url(source_url)
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, story_url)

        soup = BeautifulSoup(resp.text, "lxml")
        profile = soup.select_one("div#profile_top")

        title = text(profile.select_one("b")) if profile else None

        # Author: first <a> link inside #profile_top
        author = None
        if profile:
            first_link = profile.select_one("a[href*='/u/']")
            author = text(first_link)

        # Cover: data-original on img inside #img_large
        cover = None
        img_el = soup.select_one("div#img_large img")
        if isinstance(img_el, Tag):
            cover = attr(img_el, "data-original", "src")

        # Synopsis: the xcontrast_txt div (skip the title and author divs)
        synopsis_el = soup.select_one("div#profile_top div.xcontrast_txt")
        synopsis = inner_text(synopsis_el)

        # Tags / fandom info from xgray span
        tags: list[str] = []
        xgray = soup.select_one("div#profile_top span.xgray")
        if xgray:
            raw = xgray.get_text(" ", strip=True)
            # Typical: "Rated: T - English - Romance/Drama - Words: 45k - Chapters: 12"
            tags = [p.strip() for p in raw.split("-") if p.strip()]

        return RawMetadata(
            title=title,
            synopsis=synopsis,
            author=author,
            status=None,  # FF.net has "Complete" in xgray but parsing is fragile
            language="en",
            genres=[],
            tags=tags,
            cover_url=cover,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        story_url = _story_base_url(source_url)
        story_id = self.extract_source_id(source_url)

        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, story_url)

        soup = BeautifulSoup(resp.text, "lxml")

        # Chapter dropdown: select#chap_select options hold chapter titles
        select_el = soup.select_one("select#chap_select")
        if select_el:
            chapters: list[RawChapterListing] = []
            for opt in select_el.select("option"):
                if not isinstance(opt, Tag):
                    continue
                num_str = str(opt.get("value", ""))
                if not num_str.isdigit():
                    continue
                chapter_num = float(num_str)
                chapter_title = text(opt)
                chapter_url = f"{self.BASE_URL}/s/{story_id}/{num_str}/"
                chapters.append(RawChapterListing(
                    source_chapter_id=num_str,
                    source_url=chapter_url,
                    chapter_number=chapter_num,
                    title=chapter_title,
                ))
            return chapters

        # Single-chapter story — no dropdown
        m = _STORY_ID_RE.search(story_url)
        story_id_val = m.group(1) if m else "1"
        chapter_url = f"{self.BASE_URL}/s/{story_id_val}/1/"
        title_el = soup.select_one("div#profile_top b")
        return [RawChapterListing(
            source_chapter_id="1",
            source_url=chapter_url,
            chapter_number=1.0,
            title=text(title_el),
        )]

    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, chapter_url)

        soup = BeautifulSoup(resp.text, "lxml")

        # Chapter title from the dropdown (selected option) or story title
        title = None
        sel = soup.select_one("select#chap_select option[selected]")
        if sel:
            title = text(sel)
        if not title:
            title = text(soup.select_one("div#profile_top b"))

        content_el = soup.select_one("div.storytext")
        raw_html = str(content_el) if content_el else ""

        m = _CHAPTER_URL_RE.search(chapter_url)
        chapter_id = m.group(2) if m else chapter_url.rstrip("/").split("/")[-1]
        chapter_num = float(chapter_id) if chapter_id.isdigit() else 0.0

        return RawChapterContent(
            source_chapter_id=chapter_id,
            source_url=chapter_url,
            chapter_number=chapter_num,
            title=title,
            raw_content=raw_html,
            content_format="html",
        )


def _story_base_url(url: str) -> str:
    """Normalise any FF.net story URL to chapter 1 (the metadata page)."""
    m = _STORY_ID_RE.search(url)
    if not m:
        return url
    story_id = m.group(1)
    return f"https://www.fanfiction.net/s/{story_id}/1/"
