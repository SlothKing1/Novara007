# Adding a New Source Adapter

This guide walks through onboarding a new source site to Novara.

## Overview

Each source site has exactly one adapter module in:

```
novara/ingestion/adapters/<site_key>.py
```

Adapters are auto-discovered at startup. You do not need to register them
anywhere else — just create the file and use the `@register` decorator.

---

## Step 1: Assess the Source

Before writing any code, characterise the source:

1. **What does the title page look like?**
   - Is it server-rendered HTML or a SPA/API?
   - What selectors contain title, author, synopsis, status, cover, genres?

2. **How is the chapter list served?**
   - Paginated? Infinite scroll? JSON API?
   - What is the chapter URL format?

3. **What does the chapter page look like?**
   - Where is the content div?
   - Does it include repeated headings, boilerplate, or ads?

4. **What is the source's metadata quality?**
   - Strong on: title, synopsis, genres, status?
   - Weak on: translator attribution, original language, cover quality?

5. **Does the site use rate limiting or bot protection?**
   - Set `REQUESTS_PER_SECOND` accordingly (default: 1.0).

---

## Step 2: Create the Adapter Module

Create `novara/ingestion/adapters/<your_site_key>.py`.

```python
from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from novara.ingestion.base_adapter import (
    BaseAdapter,
    RawChapterContent,
    RawChapterListing,
    RawMetadata,
)
from novara.ingestion.http_client import fetch_with_retry, rate_limited_client
from novara.ingestion.registry import register


@register
class MySourceAdapter(BaseAdapter):
    SITE_KEY = "mysource"           # Stable, lowercase, no spaces
    SITE_NAME = "My Source"         # Human-readable name
    BASE_URL = "https://mysource.com"

    REQUESTS_PER_SECOND = 1.0

    def extract_source_id(self, source_url: str) -> str:
        # Return the stable internal ID for this source (e.g. numeric ID from URL)
        # Default: return the URL itself
        return source_url

    def normalise_status(self, raw: str) -> str:
        # Map site-specific status strings to canonical values:
        # ongoing | completed | hiatus | dropped
        mapping = {"active": "ongoing", "finished": "completed"}
        return mapping.get(raw.lower().strip(), raw.lower().strip())

    async def scrape_title(self, source_url: str) -> RawMetadata:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")

        # Fill in what this source provides. Use None for missing fields.
        return RawMetadata(
            title=...,
            synopsis=...,
            author=...,
            status=self.normalise_status(...) if ... else None,
            language="en",
            original_language=None,
            translator_group=None,
            genres=[...],
            tags=[],
            cover_url=...,
            total_chapters=...,
        )

    async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, source_url)

        soup = BeautifulSoup(resp.text, "lxml")
        chapters = []

        for i, link in enumerate(soup.select("a.chapter-link"), start=1):
            chapters.append(RawChapterListing(
                source_chapter_id=...,
                source_url=...,
                chapter_number=float(i),
                title=link.get_text(strip=True),
            ))

        return chapters

    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        async with rate_limited_client(self.SITE_KEY, self.REQUESTS_PER_SECOND) as client:
            resp = await fetch_with_retry(client, chapter_url)

        soup = BeautifulSoup(resp.text, "lxml")
        content_el = soup.select_one("div.chapter-content")

        return RawChapterContent(
            source_chapter_id=...,
            source_url=chapter_url,
            chapter_number=...,
            title=...,
            raw_content=str(content_el) if content_el else "",
            content_format="html",
        )
```

---

## Step 3: Do NOT clean content in the adapter

The adapter's job is to return **raw HTML exactly as served**.

Do not:
- Strip tags
- Remove headings
- Clean whitespace
- Remove boilerplate

The shared `CleaningPipeline` handles all of that.

---

## Step 4: Write tests

Create `tests/test_ingestion/test_<site_key>_adapter.py`.

Use `respx` to mock HTTP responses:

```python
import respx
import httpx
import pytest

from novara.ingestion.adapters.mysource import MySourceAdapter

@pytest.mark.asyncio
@respx.mock
async def test_scrape_title() -> None:
    url = "https://mysource.com/novel/1234"
    respx.get(url).mock(return_value=httpx.Response(200, text=FIXTURE_HTML))

    adapter = MySourceAdapter()
    metadata = await adapter.scrape_title(url)

    assert metadata.title == "Expected Title"
    assert metadata.status == "ongoing"
```

Put the HTML fixture in `tests/fixtures/<site_key>_title.html`.

---

## Step 5: Characterise source quality

After the adapter is working, configure the expected quality level.
This affects confidence scores on MetadataClaims:

- Sources with rich, accurate metadata: expected high quality score (0.8+)
- Aggregator/mirror sites with thin metadata: expected low quality score (0.3–0.5)
- MTL sources: mark as low quality on content, may still be good for metadata

The `QualityScorer.score_metadata_completeness()` method computes the actual
score from the scraped data, so you do not need to configure it manually.
The score is computed automatically after each scrape.

---

## Step 6: Test end-to-end locally

```bash
# Start the stack
docker compose up db redis -d
docker compose run --rm migrate

# Trigger a test ingestion via the API
curl -X POST http://localhost:8000/api/v1/ingestion/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "source_site": "mysource",
    "source_url": "https://mysource.com/novel/1234",
    "scrape_chapters": true,
    "scrape_content": false
  }'

# Check the job result
curl http://localhost:8000/api/v1/ingestion/jobs?source_site=mysource
```

---

## Common Patterns

### Pagination

If the chapter list is paginated:

```python
async def scrape_chapter_listing(self, source_url: str) -> list[RawChapterListing]:
    chapters = []
    page = 1
    while True:
        url = f"{source_url}?page={page}"
        async with rate_limited_client(self.SITE_KEY) as client:
            resp = await fetch_with_retry(client, url)
        soup = BeautifulSoup(resp.text, "lxml")
        page_chapters = self._parse_chapter_page(soup)
        if not page_chapters:
            break
        chapters.extend(page_chapters)
        page += 1
    return chapters
```

### JSON API sources

Some sites (e.g. apps with REST APIs) return JSON instead of HTML:

```python
async def scrape_title(self, source_url: str) -> RawMetadata:
    api_url = f"https://api.mysource.com/novels/{self.extract_source_id(source_url)}"
    async with rate_limited_client(self.SITE_KEY) as client:
        resp = await fetch_with_retry(client, api_url)
    data = resp.json()
    return RawMetadata(
        title=data.get("name"),
        synopsis=data.get("description"),
        ...
    )
```

### WordPress blogs

Many fan translation sites run WordPress. Common patterns:

- Posts indexed at `/?cat=<id>` or `/?tag=<slug>`
- Chapter content in `div.entry-content` or `div.post-content`
- No chapter listing page — must paginate through post index

---

## Checklist

- [ ] Adapter registered with `@register`
- [ ] `SITE_KEY` is lowercase, URL-safe, stable
- [ ] `extract_source_id()` returns a stable ID
- [ ] `normalise_status()` maps site vocabulary to canonical values
- [ ] `scrape_title()` returns raw HTML — no cleaning
- [ ] `scrape_chapter_listing()` returns chapters sorted by number ascending
- [ ] `scrape_chapter()` returns raw HTML in `raw_content`
- [ ] Tests written with `respx` mocks
- [ ] HTML fixtures committed to `tests/fixtures/`
- [ ] Rate limit configured appropriately for the source
