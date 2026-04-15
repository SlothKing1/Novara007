"""ScribbleHub source adapter.

ScribbleHub (scribblehub.com) is a popular original English web fiction platform.

Characteristics:
- Excellent metadata: title, synopsis, author, tags, cover, genres
- Clean chapter structure: content in #chp_raw
- Chapter list via form POST (AJAX) or direct TOC page
- Source IDs are numeric fiction IDs in the URL
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
from novara.ingestion.base_adapter import (
    BaseAdapter,
    RawChapterContent,
    RawChapterListing,
    RawMetadata,
)
from novara.ingestion.http_client import fetch_with_retry, rate_limited_client
from novara.ingestion.registry import register

_FICTION_ID_RE = re.compile(r"scribblehub\.com/series/(\d+)/")


@register
class ScribbleHubAdapter(BaseAdapter):
    SITE_KEY = "scribblehub"
    SITE_NAME = "ScribbleHub"
    BASE_URL = "https://www.scribblehub.com"
    REQUESTS_PER_SECOND = 1.0

    def extract_source_id(self, source_url: str) -> str:
        m = _FICTION_ID_RE.search(source_url)
        return m.group(1) if m else source_url

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        title = text(soup.select_one(".fic_title"))
        synopsis = inner_text(soup.select_one(".wi_fic_desc"))
        cover = find_cover(soup, ".fic_image img")

        # Author: may be multiple
        authors = [text(a) for a in soup.select(".auth_name_fic") if text(a)]
        author = ", ".join(authors) if authors else None

        # Status
        status_el = soup.select_one(".fic_state")
        status = normalise_status(text(status_el))

        # Genres and tags
        genres = [text(a) for a in soup.select(".fic_genre a") if text(a)]
        tags = [text(a) for a in soup.select(".wi_fic_showtags a") if text(a)]

        # Total chapters from the chapter count badge
        total = None
        count_el = soup.select_one(".cnt_toc .cnt")
        if count_el:
            try:
                total = int(text(count_el).replace(",", ""))
            except (ValueError, AttributeError):
                pass

        return RawMetadata(
            title=title,
            synopsis=synopsis,
            author=author,
            status=status,
            language="en",
            genres=genres or [],
            tags=tags or [],
            cover_url=cover,
            total_chapters=total,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        """Fetch chapter list via the TOC AJAX endpoint."""
        fiction_id = self.extract_source_id(source_url)
        chapters: list[RawChapterListing] = []
        page = 1

        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            while True:
                toc_url = (
                    f"{self.BASE_URL}/wp-admin/admin-ajax.php"
                )
                data = {
                    "action": "wi_getreleases_pagination",
                    "pagenum": str(page),
                    "mypostid": fiction_id,
                }
                resp = await client.post(toc_url, data=data)
                if resp.status_code != 200:
                    break
                soup = BeautifulSoup(resp.text, "lxml")
                links = soup.select(".toc_ol a.toc_a, .main .toc li a")
                if not links:
                    break
                for idx, link in enumerate(links, start=(page - 1) * 100 + 1):
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
                # ScribbleHub returns all chapters on one AJAX call — stop
                break

        # Reverse if site returns newest-first
        if len(chapters) > 1 and chapters[0].chapter_number > chapters[-1].chapter_number:
            chapters.reverse()

        return chapters

    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, chapter_url)

        soup = BeautifulSoup(resp.text, "lxml")
        title_el = soup.select_one(".chapter-title, .bi_t, h1")
        title = text(title_el)
        content_el = soup.select_one("#chp_raw")
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
