"""LightNovelWorld source adapter (lightnovelworld.com).

Characteristics:
- Good metadata: title, author, cover, status
- Chapter list in div#chapter_content
- Content in div#content_detail
- Paginated chapter list
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from novara.ingestion.adapter_utils import (
    absolute_url,
    find_cover,
    find_next_page,
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

_NOVEL_SLUG_RE = re.compile(r"lightnovelworld\.com/novel/([^/?#]+)")


@register
class LightNovelWorldAdapter(BaseAdapter):
    SITE_KEY = "lightnovelworld"
    SITE_NAME = "LightNovelWorld"
    BASE_URL = "https://www.lightnovelworld.com"
    REQUESTS_PER_SECOND = 1.0

    def extract_source_id(self, source_url: str) -> str:
        m = _NOVEL_SLUG_RE.search(source_url)
        return m.group(1) if m else source_url

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        # Title: inside li.text1, strip any nested spans
        title_el = soup.select_one("li.text1")
        if title_el:
            for span in title_el.find_all("span"):
                span.decompose()
        title = text(title_el)

        cover = find_cover(soup, ".book_info_l img", ".cover img")
        author = text(soup.select_one("span.textC999, .author a"))
        status_el = soup.select_one(".status, span[class*='status']")
        status = normalise_status(text(status_el))
        genres = [text(a) for a in soup.select(".genre a, .tag a") if text(a)]
        synopsis = inner_text(soup.select_one(".summary, .description, .content"))

        return RawMetadata(
            title=title,
            synopsis=synopsis,
            author=author,
            status=status,
            language="en",
            genres=genres or [],
            cover_url=cover,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        chapters: list[RawChapterListing] = []
        slug = self.extract_source_id(source_url)
        page_url: str | None = f"{self.BASE_URL}/novel/{slug}/chapters"
        page_num = 1

        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            while page_url:
                resp = await fetch_with_retry(client, page_url)
                soup = BeautifulSoup(resp.text, "lxml")

                for link in soup.select("div#chapter_content ul li a, .chapter-list li a"):
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

                page_url = find_next_page(soup, page_url)
                page_num += 1
                if page_num > 200:
                    break

        return chapters

    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, chapter_url)

        soup = BeautifulSoup(resp.text, "lxml")
        title = text(soup.select_one("h1, .chapter-title"))
        content_el = soup.select_one("div#content_detail, div.chapter-content")

        # Remove any nested navigation divs
        if content_el:
            for div in content_el.select("div[class*='nav'], .nav-buttons, .chapter-nav"):
                div.decompose()

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
