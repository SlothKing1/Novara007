"""BaseAdapter — the contract every source adapter must implement."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawMetadata:
    """Scraped metadata from a title page.

    All fields are optional — the adapter fills what it can find.
    None means "not available from this source", not "unknown value".
    """

    title: str | None = None
    original_title: str | None = None
    synopsis: str | None = None
    author: str | None = None
    artist: str | None = None
    # "ongoing" | "completed" | "hiatus" | "dropped" — adapter should normalise
    status: str | None = None
    # BCP-47 language code of the translated text
    language: str | None = None
    # BCP-47 language code of the original work
    original_language: str | None = None
    translator_group: str | None = None
    publisher: str | None = None
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    cover_url: str | None = None
    total_chapters: int | None = None
    release_year: int | None = None
    # Everything else the adapter captures, unstructured
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawChapterListing:
    """A chapter entry from the table-of-contents page."""

    source_chapter_id: str
    source_url: str
    chapter_number: float
    title: str | None = None
    # Optional: release date string as seen on the site
    release_date: str | None = None


@dataclass
class RawChapterContent:
    """Scraped content of one chapter page."""

    source_chapter_id: str
    source_url: str
    chapter_number: float
    title: str | None
    # Raw HTML or plain text — never stripped by the adapter itself.
    # The cleaning pipeline handles all normalisation.
    raw_content: str
    # Format hint: "html" | "text"
    content_format: str = "html"


class BaseAdapter(abc.ABC):
    """Abstract base class for all source adapters.

    Concrete adapters live in novara/ingestion/adapters/<site>.py.
    They must implement the three abstract methods below and declare
    the class-level SITE_KEY matching the source_site DB field.

    The runner (novara.ingestion.runner) calls these methods and
    persists results using shared infrastructure — adapters never
    write to the database directly.
    """

    # Unique identifier for this source.  Must be stable across deployments.
    SITE_KEY: str

    # Human-readable name for UI / admin displays.
    SITE_NAME: str

    # Base URL of the source site.
    BASE_URL: str

    # Requests per second for this source (overrides global setting).
    REQUESTS_PER_SECOND: float = 1.0

    # Set True for sites that require cloudscraper on the first request
    # (known Cloudflare sites). For most sites leave False — the HTTP client
    # will fall back automatically on 403/503.
    NEEDS_CLOUDSCRAPER: bool = False

    @abc.abstractmethod
    async def scrape_title(self, source_url: str) -> RawMetadata:
        """Scrape and return the metadata from a novel's title page.

        The returned RawMetadata is NOT normalised — the caller handles
        normalisation and claim creation.  Return None fields for anything
        the source does not provide.

        Args:
            source_url: Full URL of the novel's listing / title page.

        Returns:
            RawMetadata with whatever fields this source provides.
        """

    @abc.abstractmethod
    async def scrape_chapter_listing(
        self, source_url: str
    ) -> list[RawChapterListing]:
        """Scrape and return the chapter listing for a title.

        Args:
            source_url: Full URL of the novel's title or TOC page.

        Returns:
            List of RawChapterListing ordered by chapter_number ascending.
            May be incomplete if the source paginates the TOC.
        """

    @abc.abstractmethod
    async def scrape_chapter(self, chapter_url: str) -> RawChapterContent:
        """Scrape and return the raw content of one chapter.

        The adapter must NOT clean, strip, or reformat the content.
        It should return raw HTML or text exactly as served.

        Args:
            chapter_url: Full URL of the chapter page.

        Returns:
            RawChapterContent with raw_content populated.
        """

    # ── optional hooks ───────────────────────────────────────────────────────

    def extract_source_id(self, source_url: str) -> str:
        """Derive the stable site-internal ID from the URL.

        Override this if the source has a non-URL ID scheme (e.g. numeric IDs
        from the URL path).  Default implementation returns the URL itself.
        """
        return source_url

    def normalise_status(self, raw: str) -> str:
        """Map a source-specific status string to the canonical set.

        Canonical values: ongoing | completed | hiatus | dropped
        Override to handle site-specific wording.
        """
        mapping = {
            "ongoing": "ongoing",
            "active": "ongoing",
            "updating": "ongoing",
            "completed": "completed",
            "complete": "completed",
            "finished": "completed",
            "hiatus": "hiatus",
            "on hold": "hiatus",
            "dropped": "dropped",
            "cancelled": "dropped",
        }
        return mapping.get(raw.lower().strip(), raw.lower().strip())
