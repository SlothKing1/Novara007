"""VersionMatcher — determines whether a new SourceTitle belongs to an existing Version.

Key distinction:
- Same work + same translator group → same Version (even on different sites).
- Same work + different translator group → different Version.
- Same work + unclear translator attribution → conservative: create new Version.

This matcher is called after WorkMatcher has identified (or created) a Work.
It then decides which Version within that Work this SourceTitle belongs to.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from rapidfuzz import fuzz
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novara.models import Version, Work

log = structlog.get_logger(__name__)

# Threshold for considering two translator group names the same
TRANSLATOR_MATCH_THRESHOLD = 85.0


@dataclass
class VersionMatchResult:
    """Result of a version match attempt."""

    version_id: str
    is_new: bool
    confidence: float
    match_reason: str  # "translator_exact" | "translator_fuzzy" | "language_only" | "new"


class VersionMatcher:
    """Matches a set of version signals to an existing Version within a Work.

    This is used in cases where the WorkMatcher has already resolved the Work
    but the version assignment needs finer logic (e.g. a new source claims to
    be the same translator as an existing Version but has a slightly different
    group name).
    """

    def __init__(
        self,
        session: AsyncSession,
        translator_threshold: float = TRANSLATOR_MATCH_THRESHOLD,
    ) -> None:
        self.session = session
        self.translator_threshold = translator_threshold

    async def find_best_version(
        self,
        work: Work,
        language: str,
        translator_group: str | None,
        version_type: str,
    ) -> VersionMatchResult | None:
        """Find the best matching existing Version, or return None to create one.

        Args:
            work: The Work to search within.
            language: Language code of the version.
            translator_group: Translator group name (may be None).
            version_type: "official" | "fan" | "mtl" | "original" | "revised".

        Returns:
            VersionMatchResult if a match is found, else None.
        """
        existing_versions = list(
            await self.session.scalars(
                select(Version).where(Version.work_id == work.id)
            )
        )

        if not existing_versions:
            return None

        # Filter to same language first
        same_language = [v for v in existing_versions if v.language == language]
        if not same_language:
            return None

        # If translator group is given, try to match it
        if translator_group:
            return self._match_by_translator(
                same_language, translator_group, version_type
            )

        # No translator info — only match if there's exactly one version
        # of this language and type to avoid ambiguous merges
        same_type = [v for v in same_language if v.version_type == version_type]
        if len(same_type) == 1:
            v = same_type[0]
            return VersionMatchResult(
                version_id=str(v.id),
                is_new=False,
                confidence=0.6,
                match_reason="language_only",
            )

        return None

    def _match_by_translator(
        self,
        versions: list[Version],
        translator_group: str,
        version_type: str,
    ) -> VersionMatchResult | None:
        best_version: Version | None = None
        best_score = 0.0

        for version in versions:
            if not version.translator_group:
                continue
            score = fuzz.token_sort_ratio(
                translator_group.lower(),
                version.translator_group.lower(),
            )
            if score > best_score:
                best_score = float(score)
                best_version = version

        if best_version is None or best_score < self.translator_threshold:
            return None

        reason = "translator_exact" if best_score >= 98 else "translator_fuzzy"

        return VersionMatchResult(
            version_id=str(best_version.id),
            is_new=False,
            confidence=best_score / 100.0,
            match_reason=reason,
        )
