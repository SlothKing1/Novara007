"""Archive of Our Own source adapter (archiveofourown.org).

AO3 is the largest fanfiction/original fiction archive.  It has strict
rate-limiting (requests must be throttled) and requires appending
``?view_adult=true`` to access works rated Mature/Explicit.

Selectors from WebToEpub ArchiveOfOurOwnParser.js:
- Title: h2.heading
- Author: a[rel='author']
- Language: meta[name='language']
- Synopsis: div.summary blockquote
- Tags/Fandoms: .meta .tags a
- Chapter list: ol.chapter a  (multi-chapter) or dl.stats dd.chapters
- Content: div#chapters

Work URL format: /works/{id}
Chapter URL format: /works/{id}/chapters/{chapter_id}
Navigate URL (full TOC): /works/{id}/navigate
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from novara.ingestion.adapter_utils import (
    absolute_url,
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

_WORK_ID_RE = re.compile(r"/works/(\d+)")
_CHAPTER_ID_RE = re.compile(r"/chapters/(\d+)")


@register
class ArchiveOfOurOwnAdapter(BaseAdapter):
    SITE_KEY = "archiveofourown"
    SITE_NAME = "Archive of Our Own"
    BASE_URL = "https://archiveofourown.org"
    # AO3 has a strict crawl policy — 429 if you go faster than 1 req/2s
    REQUESTS_PER_SECOND = 0.5

    def extract_source_id(self, source_url: str) -> str:
        m = _WORK_ID_RE.search(source_url)
        return m.group(1) if m else source_url

    async def scrape_title(self, source_url: str) -> RawMetadata:
        work_url = _work_url(source_url) + "?view_adult=true"
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, work_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title = text(soup.select_one("h2.heading"))
        author = text(soup.select_one("a[rel='author']"))

        # Language from meta tag (BCP-47 code, e.g. "en")
        language = None
        lang_meta = soup.select_one("meta[name='language']")
        if isinstance(lang_meta, Tag):
            language = str(lang_meta.get("content", "")) or None

        synopsis = inner_text(soup.select_one("div.summary blockquote"))

        # Tags: split into fandoms, characters, relationships, freeform
        tags: list[str] = []
        genres: list[str] = []
        for a in soup.select(".meta .tags a"):
            t = text(a)
            if t:
                tags.append(t)

        # Fandoms as genres
        for a in soup.select(".fandoms a"):
            t = text(a)
            if t:
                genres.append(t)

        # Status from dl.stats dd.status
        status = None
        for dt in soup.select("dl.stats dt"):
            if "status" in (text(dt) or "").lower():
                dd = dt.find_next_sibling("dd")
                if dd:
                    raw = (text(dd) or "").lower()  # type: ignore[arg-type]
                    if "complete" in raw:
                        status = "completed"
                    elif "progress" in raw or "update" in raw:
                        status = "ongoing"

        # Total chapters from "dd.chapters": "12/?" (ongoing) or "12/12" (done)
        total: int | None = None
        chap_dd = soup.select_one("dd.chapters")
        if chap_dd:
            raw_chap = text(chap_dd) or ""
            m = re.match(r"(\d+)/(\d+|\?)", raw_chap)
            if m and m.group(2) != "?":
                try:
                    total = int(m.group(2))
                except ValueError:
                    pass

        # Cover: AO3 doesn't typically have cover images; skip
        return RawMetadata(
            title=title,
            synopsis=synopsis,
            author=author,
            status=status,
            language=language or "en",
            genres=genres,
            tags=tags,
            cover_url=None,
            total_chapters=total,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        work_id = self.extract_source_id(source_url)
        nav_url = f"{self.BASE_URL}/works/{work_id}/navigate?view_adult=true"

        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, nav_url)

        soup = BeautifulSoup(resp.text, "lxml")
        chapters: list[RawChapterListing] = []

        for idx, link in enumerate(soup.select("ol.chapter a[href*='/chapters/']"), start=1):
            if not isinstance(link, Tag):
                continue
            href = str(link.get("href", ""))
            chapter_url = absolute_url(self.BASE_URL, href) + "?view_adult=true"
            chapter_title = text(link)
            m = _CHAPTER_ID_RE.search(href)
            chapter_id = m.group(1) if m else str(idx)
            chapter_num = parse_chapter_number(chapter_title, href) or float(idx)
            chapters.append(RawChapterListing(
                source_chapter_id=chapter_id,
                source_url=chapter_url,
                chapter_number=chapter_num,
                title=chapter_title,
            ))

        # Single-chapter work: navigate page has no chapter list
        if not chapters:
            work_url = f"{self.BASE_URL}/works/{work_id}?view_adult=true"
            async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
                resp = await fetch_with_retry(client, work_url)
            soup = BeautifulSoup(resp.text, "lxml")
            title = text(soup.select_one("h2.heading"))
            chapters.append(RawChapterListing(
                source_chapter_id=work_id,
                source_url=work_url,
                chapter_number=1.0,
                title=title,
            ))

        return chapters

    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        url = chapter_url if "view_adult" in chapter_url else chapter_url + "?view_adult=true"
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, url)

        soup = BeautifulSoup(resp.text, "lxml")

        # Chapter title: h3.title inside the chapter div, or work title
        title = text(soup.select_one("h3.title, h2.heading"))

        content_el = soup.select_one("div#chapters")
        # Remove navigation, kudos, and other non-content elements
        if content_el:
            for unwanted in content_el.select(
                "div#feedback, div.end.notes, .chapter.preface.group nav"
            ):
                unwanted.decompose()

        raw_html = str(content_el) if content_el else ""

        m = _CHAPTER_ID_RE.search(chapter_url)
        chapter_id = m.group(1) if m else self.extract_source_id(chapter_url)
        chapter_num = parse_chapter_number(title, chapter_url) or 0.0

        return RawChapterContent(
            source_chapter_id=chapter_id,
            source_url=chapter_url,
            chapter_number=chapter_num,
            title=title,
            raw_content=raw_html,
            content_format="html",
        )


def _work_url(url: str) -> str:
    """Normalise any AO3 URL to the canonical work URL."""
    m = _WORK_ID_RE.search(url)
    if not m:
        return url
    return f"https://archiveofourown.org/works/{m.group(1)}"
