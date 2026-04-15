"""Madara WordPress theme base adapter.

The Madara theme (madara.co) is used by dozens of web novel and manga
translation sites.  This template captures the shared HTML structure so
individual site adapters only need to override class-level constants.

Supported sites (adapter files extend this class):
  boxnovel.com, novelbuddy.com, mangasushi.net, noveltrench.com,
  morenovel.net, readwebnovel.xyz, webnovel.live, and 50+ others.

Key Madara characteristics:
- Novel metadata in div.post-title / div.summary_image / div.post-status
- Full chapter list via AJAX POST to ``{novel_url}ajax/chapters/``
  (falls back to parsing static HTML when AJAX is unavailable)
- Chapter content in div.reading-content (with lazy-loaded images)
- Genres/tags from .genres-content a[rel='tag']

Selectors confirmed against:
  WebToEpub MadaraParser.js  (github.com/dteviot/WebToEpub)
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

_SLUG_RE = re.compile(r"/(?:novel|manga)/([^/?#]+)")


class MadaraTemplate(BaseAdapter):
    """Shared scraping logic for WordPress Madara theme sites.

    Subclasses must set SITE_KEY, SITE_NAME, BASE_URL.
    Override SEL_* constants for sites that differ from standard Madara.
    """

    REQUESTS_PER_SECOND = 1.0

    # ── selectors (standard Madara) ──────────────────────────────────────────
    SEL_TITLE = "div.post-title h1, h1.post-title"
    SEL_COVER = "div.summary_image img, .summary_image img"
    SEL_AUTHOR = "div.author-content a, .author-content a"
    SEL_ARTIST = "div.artist-content a, .artist-content a"
    SEL_DESCRIPTION = ".summary__content, .description-summary, .summary__content p"
    # Each post-content_item is a label+value pair (Status, Type, Release, …)
    SEL_STATUS_ITEMS = "div.post-status .post-content_item, div.post-content_item"
    SEL_GENRES = "div .genres-content [rel='tag'], .genres-content a"
    # a:not([title]) filters out "Teaser/Sponsor" premium chapter links
    SEL_CHAPTER_LIST = "li.wp-manga-chapter > a:not([title]), ul.main.version-chap li a"
    SEL_CONTENT = "div.reading-content .text-left, div.reading-content, div.chapter-content"
    SEL_CHAPTER_TITLE = "ol.breadcrumb li.active, h1"

    def extract_source_id(self, source_url: str) -> str:
        m = _SLUG_RE.search(source_url)
        return m.group(1) if m else source_url.rstrip("/").split("/")[-1]

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title = text(soup.select_one(self.SEL_TITLE))
        cover = find_cover(soup, self.SEL_COVER)
        author = text(soup.select_one(self.SEL_AUTHOR))
        artist = text(soup.select_one(self.SEL_ARTIST))
        synopsis = inner_text(soup.select_one(self.SEL_DESCRIPTION))
        genres = [text(a) for a in soup.select(self.SEL_GENRES) if text(a)]

        # Status: Madara stores each item as heading + value inside .post-content_item
        status = None
        for item in soup.select(self.SEL_STATUS_ITEMS):
            heading = item.select_one(".summary-heading, h5, .post-content_item-head")
            if heading and "status" in (text(heading) or "").lower():
                value_el = item.select_one(".summary-content, .post-content_item-value")
                status = normalise_status(text(value_el))
                break

        return RawMetadata(
            title=title,
            synopsis=synopsis,
            author=author,
            artist=artist,
            status=status,
            language="en",
            original_language="zh",
            genres=genres or [],
            cover_url=cover,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        """Fetch chapter list via Madara's AJAX endpoint with static HTML fallback."""
        base = source_url.rstrip("/") + "/"
        ajax_url = base + "ajax/chapters/"

        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            soup: BeautifulSoup | None = None

            # Madara AJAX: POST returns HTML fragment with full chapter list
            try:
                ajax_resp = await client.post(
                    ajax_url,
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
                if ajax_resp.status_code == 200 and ajax_resp.text.strip():
                    soup = BeautifulSoup(ajax_resp.text, "lxml")
            except Exception:
                pass

            # Fall back to static HTML if AJAX failed or returned no chapters
            if not soup or not soup.select(self.SEL_CHAPTER_LIST):
                resp = await fetch_with_retry(client, source_url)
                soup = BeautifulSoup(resp.text, "lxml")

        chapters: list[RawChapterListing] = []
        for link in soup.select(self.SEL_CHAPTER_LIST):
            if not isinstance(link, Tag):
                continue
            href = str(link.get("href", ""))
            if not href:
                continue
            chapter_url = absolute_url(self.BASE_URL, href)
            chapter_title = text(link)
            chapter_num = parse_chapter_number(chapter_title, href) or float(len(chapters) + 1)
            chapter_id = href.rstrip("/").split("/")[-1] or str(len(chapters) + 1)
            chapters.append(RawChapterListing(
                source_chapter_id=chapter_id,
                source_url=chapter_url,
                chapter_number=chapter_num,
                title=chapter_title,
            ))

        # Madara AJAX returns chapters newest-first; sort ascending
        chapters.sort(key=lambda c: c.chapter_number)
        return chapters

    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, chapter_url)

        soup = BeautifulSoup(resp.text, "lxml")
        title = text(soup.select_one(self.SEL_CHAPTER_TITLE))
        content_el = soup.select_one(self.SEL_CONTENT)

        # Materialise lazy-loaded images so the HTML we store is self-contained
        if content_el:
            for img in content_el.select("img[data-src]"):
                if isinstance(img, Tag) and not img.get("src"):
                    img["src"] = img.get("data-src", "")  # type: ignore[index]

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
