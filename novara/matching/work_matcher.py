"""WorkMatcher — deduplicates and links SourceTitles to canonical Works.

The matcher answers the question:
"Is this SourceTitle the same story as an existing Work?"

Strategy:
1. Exact slug match (computed from normalised title).
2. Fuzzy title match above a configurable threshold.
3. If no match: create a new Work + new Version.

This is intentionally conservative.  False merges (two different stories
treated as one) are much harder to recover from than false splits (same
story as two Works).  Merge decisions can be reviewed and corrected via
the admin API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog
from rapidfuzz import fuzz
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novara.models import SourceTitle, Version, Work

log = structlog.get_logger(__name__)

# Title similarity threshold to consider a match (0–100)
DEFAULT_MATCH_THRESHOLD = 90.0

# Stop words removed during aggressive normalisation
_STOP_WORDS = frozenset({
    "the", "a", "an", "of", "in", "to", "is", "it", "as",
    "and", "or", "for", "on", "with", "at", "by", "from",
    "i", "ii", "iii", "iv",
    # common web-novel title noise
    "novel", "light", "manga", "manhwa", "manhua", "webtoon",
    "omniscient", "reader", "viewpoint", "view", "point",
})


def _normalise_for_matching(title: str) -> str:
    """Aggressive title normalisation for fuzzy comparison.

    Lowercases, strips punctuation, removes stop words so that titles like
    "The Legendary Moonlight Sculptor" and "Legendary Moonlight Sculptor"
    resolve to the same comparison string.

    Ported from Max-System-novara-project-1 / scraper_v2/core/ingest.py.
    """
    t = re.sub(r"[^a-z0-9\s]", "", title.lower())
    words = [w for w in t.split() if w and w not in _STOP_WORDS]
    return " ".join(words)


@dataclass
class MatchResult:
    """Outcome of a match attempt for one SourceTitle."""

    source_title_id: str
    matched_work_id: str | None
    matched_version_id: str | None
    is_new_work: bool
    is_new_version: bool
    confidence: float
    match_reason: str  # "exact_slug" | "fuzzy_title" | "new"


class WorkMatcher:
    """Matches a SourceTitle to an existing Work (or creates one).

    The matcher does NOT commit — the caller must commit the session.
    """

    def __init__(
        self,
        session: AsyncSession,
        match_threshold: float = DEFAULT_MATCH_THRESHOLD,
    ) -> None:
        self.session = session
        self.match_threshold = match_threshold

    async def match_or_create(
        self,
        source_title: SourceTitle,
        *,
        candidate_title: str,
        candidate_language: str = "en",
        candidate_translator_group: str | None = None,
        candidate_version_type: str = "fan",
    ) -> MatchResult:
        """Find or create a Work + Version for source_title.

        Args:
            source_title: The SourceTitle being matched.
            candidate_title: The normalised title from the best metadata claim.
            candidate_language: Language of this version.
            candidate_translator_group: Translator attribution if known.
            candidate_version_type: "official" | "fan" | "mtl" | "original".

        Returns:
            MatchResult describing what was found or created.
        """
        candidate_slug = slugify(candidate_title)

        # 1. Exact slug match
        existing_work = await self._find_by_slug(candidate_slug)
        if existing_work:
            version = await self._find_or_create_version(
                work=existing_work,
                language=candidate_language,
                translator_group=candidate_translator_group,
                version_type=candidate_version_type,
            )
            source_title.version_id = version.id
            return MatchResult(
                source_title_id=str(source_title.id),
                matched_work_id=str(existing_work.id),
                matched_version_id=str(version.id),
                is_new_work=False,
                is_new_version=False,
                confidence=1.0,
                match_reason="exact_slug",
            )

        # 2. Fuzzy title match against all Works
        best_work, best_score = await self._fuzzy_match(candidate_title)
        if best_work and best_score >= self.match_threshold:
            version = await self._find_or_create_version(
                work=best_work,
                language=candidate_language,
                translator_group=candidate_translator_group,
                version_type=candidate_version_type,
            )
            source_title.version_id = version.id
            log.info(
                "work_fuzzy_matched",
                candidate=candidate_title,
                matched=best_work.title,
                score=best_score,
            )
            return MatchResult(
                source_title_id=str(source_title.id),
                matched_work_id=str(best_work.id),
                matched_version_id=str(version.id),
                is_new_work=False,
                is_new_version=False,
                confidence=best_score / 100.0,
                match_reason="fuzzy_title",
            )

        # 3. No match — create new Work + Version
        work = Work(slug=candidate_slug, title=candidate_title)
        self.session.add(work)
        await self.session.flush()

        version = await self._create_version(
            work=work,
            language=candidate_language,
            translator_group=candidate_translator_group,
            version_type=candidate_version_type,
        )
        source_title.version_id = version.id

        log.info(
            "work_created",
            slug=candidate_slug,
            version_id=str(version.id),
        )

        return MatchResult(
            source_title_id=str(source_title.id),
            matched_work_id=str(work.id),
            matched_version_id=str(version.id),
            is_new_work=True,
            is_new_version=True,
            confidence=1.0,
            match_reason="new",
        )

    # ── private ───────────────────────────────────────────────────────────────

    async def _find_by_slug(self, slug: str) -> Work | None:
        return await self.session.scalar(
            select(Work).where(Work.slug == slug)
        )

    async def _fuzzy_match(
        self, candidate_title: str
    ) -> tuple[Work | None, float]:
        """Scan all Works for the best fuzzy title match."""
        all_works = list(await self.session.scalars(select(Work)))
        best_work: Work | None = None
        best_score = 0.0

        norm_candidate = _normalise_for_matching(candidate_title)
        for work in all_works:
            if not work.title:
                continue
            score = fuzz.token_sort_ratio(
                norm_candidate, _normalise_for_matching(work.title)
            )
            if score > best_score:
                best_score = float(score)
                best_work = work

        return best_work, best_score

    async def _find_or_create_version(
        self,
        work: Work,
        language: str,
        translator_group: str | None,
        version_type: str,
    ) -> Version:
        """Return an existing Version or create a new one."""
        version_slug = _build_version_slug(language, translator_group)

        existing = await self.session.scalar(
            select(Version).where(
                Version.work_id == work.id,
                Version.slug == version_slug,
            )
        )
        if existing:
            return existing

        return await self._create_version(
            work=work,
            language=language,
            translator_group=translator_group,
            version_type=version_type,
        )

    async def _create_version(
        self,
        work: Work,
        language: str,
        translator_group: str | None,
        version_type: str,
    ) -> Version:
        version_slug = _build_version_slug(language, translator_group)
        label = _build_version_label(language, translator_group, version_type)

        version = Version(
            work_id=work.id,
            slug=version_slug,
            label=label,
            translator_group=translator_group,
            language=language,
            version_type=version_type,
        )
        self.session.add(version)
        await self.session.flush()
        return version


def _build_version_slug(language: str, translator_group: str | None) -> str:
    if translator_group:
        return slugify(f"{language}-{translator_group}")
    return slugify(language)


def _build_version_label(
    language: str, translator_group: str | None, version_type: str
) -> str:
    if translator_group:
        return f"{translator_group} ({language.upper()})"
    labels = {
        "official": f"Official ({language.upper()})",
        "mtl": f"MTL ({language.upper()})",
        "original": f"Original ({language.upper()})",
        "fan": f"Fan Translation ({language.upper()})",
        "revised": f"Revised ({language.upper()})",
    }
    return labels.get(version_type, f"{version_type.title()} ({language.upper()})")
