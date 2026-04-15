"""ChapterResolver — promotes the best SourceChapter to each VersionChapter.

Resolution strategy:
1. For each VersionChapter, find all linked SourceChapters.
2. Pick the one with the highest quality_score.
3. Copy its cleaned_content and word_count to VersionChapter.
4. Record which SourceChapter was promoted.

If a VersionChapter has no SourceChapters linked yet, this resolver also
creates VersionChapter stubs from SourceChapter data (the chapter mapping step).
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novara.cleaning.pipeline import PIPELINE_VERSION, CleaningPipeline, default_pipeline
from novara.cleaning.quality_scorer import QualityScorer
from novara.models import SourceChapter, SourceTitle, Version, VersionChapter
from novara.models.source_title import SourceTitle

log = structlog.get_logger(__name__)


@dataclass
class ChapterResolutionReport:
    version_id: str
    chapters_mapped: int
    chapters_promoted: int
    chapters_skipped: int


class ChapterResolver:
    """Maps SourceChapters to VersionChapters and promotes best content."""

    def __init__(
        self,
        session: AsyncSession,
        pipeline: CleaningPipeline | None = None,
    ) -> None:
        self.session = session
        self._pipeline = pipeline or default_pipeline
        self._scorer = QualityScorer()

    async def resolve(self, version: Version) -> ChapterResolutionReport:
        """Run full chapter resolution for a Version.

        Steps:
        1. Ensure VersionChapter stubs exist for all SourceChapters.
        2. Run cleaning on any SourceChapters with raw but no cleaned content.
        3. Promote the best cleaned content to each VersionChapter.

        Args:
            version: The Version to resolve chapters for.

        Returns:
            ChapterResolutionReport with counts.
        """
        # Load all SourceChapters for this version
        source_chapters = await self._load_source_chapters(version)

        mapped = 0
        for sc in source_chapters:
            created = await self._ensure_version_chapter(version, sc)
            if created:
                mapped += 1

        # Reload to pick up newly created VersionChapters
        source_chapters = await self._load_source_chapters(version)

        # Clean any unseen raw content
        for sc in source_chapters:
            if sc.raw_content and not sc.cleaned_content:
                await self._clean_source_chapter(sc)

        # Promote best content per VersionChapter
        version_chapters = await self._load_version_chapters(version)
        promoted = 0
        skipped = 0

        for vc in version_chapters:
            best = await self._pick_best_source_chapter(vc)
            if best and best.cleaned_content:
                vc.content = best.cleaned_content
                vc.word_count = best.word_count
                vc.promoted_from_id = best.id
                if not vc.title and best.source_title_text:
                    vc.title = best.source_title_text
                promoted += 1
            else:
                skipped += 1

        log.info(
            "chapters_resolved",
            version_id=str(version.id),
            mapped=mapped,
            promoted=promoted,
            skipped=skipped,
        )

        return ChapterResolutionReport(
            version_id=str(version.id),
            chapters_mapped=mapped,
            chapters_promoted=promoted,
            chapters_skipped=skipped,
        )

    # ── private ───────────────────────────────────────────────────────────────

    async def _load_source_chapters(self, version: Version) -> list[SourceChapter]:
        stmt = (
            select(SourceChapter)
            .join(SourceTitle, SourceChapter.source_title_id == SourceTitle.id)
            .where(SourceTitle.version_id == version.id)
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def _load_version_chapters(self, version: Version) -> list[VersionChapter]:
        result = await self.session.scalars(
            select(VersionChapter).where(VersionChapter.version_id == version.id)
        )
        return list(result.all())

    async def _ensure_version_chapter(
        self, version: Version, sc: SourceChapter
    ) -> bool:
        """Create a VersionChapter stub if none exists for sc.chapter_number."""
        if sc.chapter_number is None:
            return False

        existing = await self.session.scalar(
            select(VersionChapter).where(
                VersionChapter.version_id == version.id,
                VersionChapter.chapter_number == sc.chapter_number,
            )
        )
        if existing:
            # Link the SourceChapter to the existing VersionChapter
            if sc.version_chapter_id != existing.id:
                sc.version_chapter_id = existing.id
            return False

        vc = VersionChapter(
            version_id=version.id,
            chapter_number=sc.chapter_number,
            title=sc.source_title_text,
        )
        self.session.add(vc)
        await self.session.flush()  # get vc.id
        sc.version_chapter_id = vc.id
        return True

    async def _clean_source_chapter(self, sc: SourceChapter) -> None:
        """Run the cleaning pipeline on a SourceChapter's raw content."""
        if not sc.raw_content:
            return
        try:
            result = self._pipeline.run(
                sc.raw_content,
                content_format="html",
                chapter_title=sc.source_title_text,
            )
            sc.cleaned_content = result.content
            sc.word_count = result.word_count
            sc.paragraph_count = result.paragraph_count
            sc.cleaner_version = PIPELINE_VERSION

            signals = self._scorer.score_chapter(result.paragraphs, result.word_count)
            sc.quality_score = signals.final_score

            from datetime import datetime, timezone
            sc.last_cleaned_at = datetime.now(tz=timezone.utc)

        except Exception:
            log.exception(
                "chapter_cleaning_failed",
                source_chapter_id=str(sc.id),
            )

    async def _pick_best_source_chapter(
        self, vc: VersionChapter
    ) -> SourceChapter | None:
        result = await self.session.scalars(
            select(SourceChapter).where(
                SourceChapter.version_chapter_id == vc.id,
                SourceChapter.cleaned_content.is_not(None),
            )
        )
        candidates = list(result.all())
        if not candidates:
            return None
        return max(candidates, key=lambda sc: sc.quality_score or 0.0)
