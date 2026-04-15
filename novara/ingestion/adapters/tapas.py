"""Tapas source adapter (tapas.io).

Tapas is a major webcomic and web fiction platform with a large catalogue
of original English fiction and manhwa.  It uses a REST API for episode
listings and serves chapter content as HTML.

Chapter list: GET /api/tapas-api/v2/series/{seriesId}/episodes
  - Paginated (page=0, size=20, sort=ASC)
  - Response: JSON { episodes: [ {id, title, thumbnailUrl, free} ] }
  - Only free (unlocked) episodes are scraped

Series ID: embedded in page HTML as data-series-id or in a <script> block.

Selectors confirmed from WebToEpub TapasParser.js:
- Title:   (from API: series.title)
- Cover:   (from API: series.thumbnailUrl)
- Content: div.episode-viewer-wrap, div.content-viewer, p
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from novara.ingestion.adapter_utils import (
    absolute_url,
    inner_text,
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

_SERIES_ID_RE = re.compile(r'(?:data-series-id|seriesId)[=:\s"\']+(\d+)')
_SERIES_SLUG_RE = re.compile(r"tapas\.io/series/([^/?#]+)")


@register
class TapasAdapter(BaseAdapter):
    SITE_KEY = "tapas"
    SITE_NAME = "Tapas"
    BASE_URL = "https://tapas.io"
    REQUESTS_PER_SECOND = 0.5

    def extract_source_id(self, source_url: str) -> str:
        m = _SERIES_SLUG_RE.search(source_url)
        return m.group(1) if m else source_url.rstrip("/").split("/")[-1]

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        # Most stable metadata from Open Graph / meta tags
        def _og(prop: str) -> str | None:
            el = soup.select_one(f"meta[property='og:{prop}']")
            return attr(el, "content") if isinstance(el, Tag) else None

        def _meta(name: str) -> str | None:
            el = soup.select_one(f"meta[name='{name}']")
            return attr(el, "content") if isinstance(el, Tag) else None

        title = (
            text(soup.select_one("h2.series-info__title, .series-title"))
            or _og("title")
        )
        author = text(soup.select_one(".creator-info a, .creator a, a[href*='/profile/']"))
        cover = (
            attr(soup.select_one(".series-header__cover img, .cover-image img"), "src", "data-src")
            or _og("image")
        )
        synopsis = (
            inner_text(soup.select_one(".series-info__description, .description p"))
            or _og("description")
            or _meta("description")
        )
        genres = [text(a) for a in soup.select("a.genre-label, a[href*='/genre/']") if text(a)]
        tags = [text(a) for a in soup.select("a.tag-label, .tags a") if text(a)]

        return RawMetadata(
            title=title,
            synopsis=synopsis,
            author=author,
            status=None,
            language="en",
            genres=genres,
            tags=tags,
            cover_url=cover,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        html = resp.text
        soup = BeautifulSoup(html, "lxml")

        # Extract series ID
        series_id: str | None = None
        series_data = soup.select_one("[data-series-id]")
        if isinstance(series_data, Tag):
            series_id = str(series_data.get("data-series-id", ""))
        if not series_id:
            m = _SERIES_ID_RE.search(html)
            series_id = m.group(1) if m else None

        chapters: list[RawChapterListing] = []

        if series_id:
            # Fetch all free episodes via the Tapas API
            async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
                page = 0
                while True:
                    api_url = (
                        f"{self.BASE_URL}/api/tapas-api/v2/series/{series_id}/episodes"
                        f"?page={page}&size=20&sort=ASC"
                    )
                    api_resp = await fetch_with_retry(client, api_url)
                    try:
                        data = api_resp.json()
                    except Exception:
                        break

                    episodes = data.get("data", {}).get("episodes", [])
                    if not episodes:
                        break

                    for ep in episodes:
                        if not ep.get("free", True):
                            continue  # skip locked episodes
                        ep_id = str(ep.get("id", ""))
                        ep_title = ep.get("title") or f"Episode {len(chapters) + 1}"
                        ep_url = f"{self.BASE_URL}/episode/{ep_id}"
                        chapter_num = parse_chapter_number(ep_title, ep_url) or float(len(chapters) + 1)
                        chapters.append(RawChapterListing(
                            source_chapter_id=ep_id,
                            source_url=ep_url,
                            chapter_number=chapter_num,
                            title=ep_title,
                        ))

                    # Check if more pages exist
                    pagination = data.get("data", {}).get("pagination", {})
                    if not pagination.get("hasNext", False):
                        break
                    page += 1
                    if page > 500:
                        break

            if chapters:
                return chapters

        # API fallback: HTML episode list
        for idx, link in enumerate(
            soup.select("li.episode__item a[href*='/episode/'], .episode-list a"),
            start=1,
        ):
            if not isinstance(link, Tag):
                continue
            href = str(link.get("href", ""))
            if not href:
                continue
            chapter_url = absolute_url(self.BASE_URL, href)
            chapter_title = text(link)
            ep_id = href.rstrip("/").split("/")[-1]
            chapter_num = parse_chapter_number(chapter_title, href) or float(idx)
            chapters.append(RawChapterListing(
                source_chapter_id=ep_id,
                source_url=chapter_url,
                chapter_number=chapter_num,
                title=chapter_title,
            ))

        return chapters

    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, chapter_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title = text(soup.select_one("h2.episode-viewer__title, h1"))

        content_el = soup.select_one(
            "div.episode-viewer-wrap, div.content-viewer, div.viewer-content"
        )
        raw_html = str(content_el) if content_el else ""

        ep_id = chapter_url.rstrip("/").split("/")[-1]
        chapter_num = parse_chapter_number(title, chapter_url) or 0.0

        return RawChapterContent(
            source_chapter_id=ep_id,
            source_url=chapter_url,
            chapter_number=chapter_num,
            title=title,
            raw_content=raw_html,
            content_format="html",
        )
