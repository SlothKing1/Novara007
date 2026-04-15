"""IngestionRunner — orchestrates a full ingest cycle for one SourceTitle."""

from __future__ import annotations

import hashlib
import traceback
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novara.ingestion.base_adapter import BaseAdapter, RawChapterContent, RawMetadata
from novara.ingestion.registry import get_adapter
from novara.models import (
    CoverCandidate,
    IngestionJob,
    MetadataClaim,
    SourceChapter,
    SourceTitle,
)

log = structlog.get_logger(__name__)

CLEANER_VERSION = "1.0"


class IngestionRunner:
    """Drives a full ingest for a single SourceTitle.

    Responsibilities:
    - Creates / updates the IngestionJob audit record.
    - Calls the adapter to fetch metadata, chapter list, and chapter content.
    - Persists raw data without normalisation or resolution.
    - Records MetadataClaims and CoverCandidates.
    - Does NOT resolve conflicts or run the cleaning pipeline —
      those are separate passes triggered by Celery tasks.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ingest(
        self,
        source_title: SourceTitle,
        *,
        scrape_chapters: bool = True,
        scrape_content: bool = True,
    ) -> IngestionJob:
        """Run a full ingestion cycle for source_title.

        Args:
            source_title: The SourceTitle row to ingest.
            scrape_chapters: If True, fetch the chapter listing and new chapters.
            scrape_content: If True, download the content of unseen chapters.

        Returns:
            The completed (or failed) IngestionJob record.
        """
        adapter_cls = get_adapter(source_title.source_site)
        adapter: BaseAdapter = adapter_cls()

        job = IngestionJob(
            source_site=source_title.source_site,
            source_url=source_title.source_url,
            source_title_id=source_title.id,
            job_type="full" if scrape_content else "chapters",
            status="running",
            started_at=datetime.now(tz=timezone.utc),
        )
        self.session.add(job)
        await self.session.flush()

        try:
            await self._ingest_metadata(adapter, source_title)

            chapters_new = 0
            chapters_updated = 0

            if scrape_chapters:
                listing = await adapter.scrape_chapter_listing(source_title.source_url)
                job.chapters_found = len(listing)

                for entry in listing:
                    is_new = await self._upsert_source_chapter_stub(
                        source_title, entry
                    )
                    if is_new:
                        chapters_new += 1

                if scrape_content:
                    # Only fetch content for chapters with no raw_content yet
                    unseen = await self._get_chapters_without_content(source_title)
                    for sc in unseen:
                        try:
                            content = await adapter.scrape_chapter(sc.source_url)
                            await self._save_chapter_content(sc, content)
                            chapters_updated += 1
                        except Exception:
                            log.warning(
                                "chapter_scrape_failed",
                                url=sc.source_url,
                                exc_info=True,
                            )

            job.chapters_new = chapters_new
            job.chapters_updated = chapters_updated
            job.status = "completed"

        except Exception as exc:
            log.exception(
                "ingestion_failed",
                site=source_title.source_site,
                url=source_title.source_url,
            )
            job.status = "failed"
            job.error_message = str(exc)
            job.error_detail = traceback.format_exc()

        job.completed_at = datetime.now(tz=timezone.utc)
        source_title.last_scraped_at = datetime.now(tz=timezone.utc)
        return job

    # ── private helpers ──────────────────────────────────────────────────────

    async def _ingest_metadata(
        self, adapter: BaseAdapter, source_title: SourceTitle
    ) -> None:
        raw: RawMetadata = await adapter.scrape_title(source_title.source_url)

        # Preserve raw blob on the SourceTitle
        import dataclasses

        source_title.raw_metadata = dataclasses.asdict(raw)

        # Emit one MetadataClaim per non-null field
        field_map = {
            "title": raw.title,
            "original_title": raw.original_title,
            "synopsis": raw.synopsis,
            "author": raw.author,
            "artist": raw.artist,
            "status": raw.status,
            "original_language": raw.original_language,
            "translator_group": raw.translator_group,
            "publisher": raw.publisher,
            "genres": ", ".join(raw.genres) if raw.genres else None,
            "tags": ", ".join(raw.tags) if raw.tags else None,
            "cover_url": raw.cover_url,
            "total_chapters": str(raw.total_chapters) if raw.total_chapters else None,
            "release_year": str(raw.release_year) if raw.release_year else None,
        }

        # Source-level quality score is needed for confidence; default to 0.5
        base_confidence = source_title.quality_score or 0.5

        for field_name, raw_value in field_map.items():
            if raw_value is None:
                continue
            await self._upsert_claim(
                source_title=source_title,
                field_name=field_name,
                raw_value=raw_value,
                confidence=base_confidence,
            )

        # Cover candidate
        if raw.cover_url:
            await self._upsert_cover_candidate(source_title, raw.cover_url)

    async def _upsert_claim(
        self,
        source_title: SourceTitle,
        field_name: str,
        raw_value: str,
        confidence: float,
    ) -> None:
        claim_hash = hashlib.md5(raw_value.encode()).hexdigest()

        existing = await self.session.scalar(
            select(MetadataClaim).where(
                MetadataClaim.source_title_id == source_title.id,
                MetadataClaim.field_name == field_name,
                MetadataClaim.claim_hash == claim_hash,
            )
        )
        if existing:
            return  # Identical claim already recorded

        claim = MetadataClaim(
            source_title_id=source_title.id,
            field_name=field_name,
            raw_value=raw_value,
            claim_hash=claim_hash,
            confidence=confidence,
        )
        self.session.add(claim)

    async def _upsert_cover_candidate(
        self, source_title: SourceTitle, cover_url: str
    ) -> None:
        existing = await self.session.scalar(
            select(CoverCandidate).where(
                CoverCandidate.source_title_id == source_title.id,
                CoverCandidate.source_url == cover_url,
            )
        )
        if not existing:
            self.session.add(
                CoverCandidate(
                    source_title_id=source_title.id,
                    source_url=cover_url,
                )
            )

    async def _upsert_source_chapter_stub(
        self, source_title: SourceTitle, entry: object
    ) -> bool:
        """Insert a SourceChapter stub if it doesn't exist yet.

        Returns True if a new row was created.
        """
        from novara.ingestion.base_adapter import RawChapterListing

        assert isinstance(entry, RawChapterListing)

        existing = await self.session.scalar(
            select(SourceChapter).where(
                SourceChapter.source_title_id == source_title.id,
                SourceChapter.source_chapter_id == entry.source_chapter_id,
            )
        )
        if existing:
            return False

        sc = SourceChapter(
            source_title_id=source_title.id,
            source_url=entry.source_url,
            source_chapter_id=entry.source_chapter_id,
            chapter_number=entry.chapter_number,
            source_title_text=entry.title,
        )
        self.session.add(sc)
        return True

    async def _get_chapters_without_content(
        self, source_title: SourceTitle
    ) -> list[SourceChapter]:
        result = await self.session.scalars(
            select(SourceChapter).where(
                SourceChapter.source_title_id == source_title.id,
                SourceChapter.raw_content.is_(None),
            )
        )
        return list(result.all())

    async def _save_chapter_content(
        self, sc: SourceChapter, content: RawChapterContent
    ) -> None:
        sc.raw_content = content.raw_content
        sc.source_title_text = content.title or sc.source_title_text
        sc.chapter_number = content.chapter_number
        sc.last_scraped_at = datetime.now(tz=timezone.utc)
