"""Tests for source adapter contracts (unit tests with mocked HTTP)."""

from __future__ import annotations

import pytest
import respx
import httpx

from novara.ingestion.adapters.royalroad import RoyalRoadAdapter, _parse_chapter_number
from novara.ingestion.adapters.wuxiaworld import WuxiaWorldAdapter


# ── RoyalRoad ─────────────────────────────────────────────────────────────────

ROYALROAD_TITLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test Novel</title></head>
<body>
  <h1 class="font-white">The Great Adventure</h1>
  <span property="name">John Author</span>
  <div class="description">
    <div class="description-content">A story about adventure and magic.</div>
  </div>
  <span class="label">Ongoing</span>
  <div class="thumbnail"><img src="https://cdn.royalroad.com/covers/1234.jpg"></div>
  <table id="chapters">
    <tbody>
      <tr><td><a href="/fiction/1234/chapter/1/the-first-chapter">Chapter 1: The First Chapter</a>
          <td><time datetime="2024-01-01T00:00:00Z">Jan 1</time>
      </tr>
      <tr><td><a href="/fiction/1234/chapter/2/the-second-chapter">Chapter 2: The Second Chapter</a>
          <td><time datetime="2024-01-08T00:00:00Z">Jan 8</time>
      </tr>
    </tbody>
  </table>
</body>
</html>
"""

ROYALROAD_CHAPTER_HTML = """
<!DOCTYPE html>
<html>
<body>
  <h1>Chapter 1: The First Chapter</h1>
  <div class="chapter-content">
    <p>The hero woke up.</p>
    <p>Light flooded the room.</p>
    <p>Adventure awaited.</p>
  </div>
</body>
</html>
"""


def test_royalroad_extract_source_id() -> None:
    adapter = RoyalRoadAdapter()
    url = "https://www.royalroad.com/fiction/12345/some-title"
    assert adapter.extract_source_id(url) == "12345"


def test_royalroad_normalise_status() -> None:
    adapter = RoyalRoadAdapter()
    assert adapter.normalise_status("Ongoing") == "ongoing"
    assert adapter.normalise_status("Complete") == "completed"
    assert adapter.normalise_status("Hiatus") == "hiatus"
    assert adapter.normalise_status("Dropped") == "dropped"


def test_parse_chapter_number_from_title() -> None:
    assert _parse_chapter_number("Chapter 42: The Battle") == 42.0
    assert _parse_chapter_number("Chapter 5.5 — Interlude") == 5.5
    assert _parse_chapter_number("Prologue") is None
    assert _parse_chapter_number(None) is None


@pytest.mark.asyncio
@respx.mock
async def test_royalroad_scrape_title() -> None:
    url = "https://www.royalroad.com/fiction/1234/the-great-adventure"
    respx.get(url).mock(return_value=httpx.Response(200, text=ROYALROAD_TITLE_HTML))

    adapter = RoyalRoadAdapter()
    metadata = await adapter.scrape_title(url)

    assert metadata.title == "The Great Adventure"
    assert metadata.author == "John Author"
    assert metadata.synopsis == "A story about adventure and magic."
    assert metadata.status == "ongoing"
    assert metadata.cover_url == "https://cdn.royalroad.com/covers/1234.jpg"
    assert metadata.total_chapters == 2
    assert metadata.language == "en"


@pytest.mark.asyncio
@respx.mock
async def test_royalroad_scrape_chapter_listing() -> None:
    url = "https://www.royalroad.com/fiction/1234/the-great-adventure"
    respx.get(url).mock(return_value=httpx.Response(200, text=ROYALROAD_TITLE_HTML))

    adapter = RoyalRoadAdapter()
    listing = await adapter.scrape_chapter_listing(url)

    assert len(listing) == 2
    assert listing[0].chapter_number == 1.0
    assert listing[0].title == "Chapter 1: The First Chapter"
    assert "chapter/1" in listing[0].source_url
    assert listing[0].release_date == "2024-01-01T00:00:00Z"


@pytest.mark.asyncio
@respx.mock
async def test_royalroad_scrape_chapter() -> None:
    url = "https://www.royalroad.com/fiction/1234/chapter/1/the-first-chapter"
    respx.get(url).mock(return_value=httpx.Response(200, text=ROYALROAD_CHAPTER_HTML))

    adapter = RoyalRoadAdapter()
    content = await adapter.scrape_chapter(url)

    assert content.title == "Chapter 1: The First Chapter"
    assert content.content_format == "html"
    assert "chapter-content" in content.raw_content
    assert content.chapter_number == 1.0


# ── WuxiaWorld ────────────────────────────────────────────────────────────────

def test_wuxiaworld_extract_source_id() -> None:
    adapter = WuxiaWorldAdapter()
    url = "https://www.wuxiaworld.com/novel/the-legendary-mechanic"
    assert adapter.extract_source_id(url) == "the-legendary-mechanic"


def test_wuxiaworld_normalise_status() -> None:
    adapter = WuxiaWorldAdapter()
    assert adapter.normalise_status("Active") == "ongoing"
    assert adapter.normalise_status("Completed") == "completed"
