"""QualityScorer — assigns a quality score to cleaned chapter content.

Score is a float in [0.0, 1.0].  Higher is better.

The scorer is heuristic-based and intentionally transparent — each sub-signal
can be inspected in the returned detail dict.  The weights are chosen to
penalise common scraping failures without false-positives on short chapters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Expected word count range for a typical web novel chapter
MIN_EXPECTED_WORDS = 500
TARGET_WORDS = 2000
MAX_EXPECTED_WORDS = 15_000

# Typical paragraph count range
MIN_PARAGRAPHS = 5
TARGET_PARAGRAPHS = 30

# Suspicious signals in cleaned text
_BOILERPLATE_INDICATORS = re.compile(
    r"(translator|tl note|patreon|stolen|read on|support the|ko-fi|donate)",
    re.IGNORECASE,
)
_REPETITIVE_LINE_RE = re.compile(r"(.{20,})\n\1", re.MULTILINE)


@dataclass
class QualitySignals:
    """Individual scoring signals for inspection."""

    word_count: int = 0
    paragraph_count: int = 0
    avg_paragraph_length: float = 0.0
    boilerplate_hits: int = 0
    has_repetition: bool = False
    # 0.0–1.0 sub-scores
    length_score: float = 0.0
    structure_score: float = 0.0
    cleanliness_score: float = 0.0
    final_score: float = 0.0
    # Free-form notes for admin review
    notes: list[str] = field(default_factory=list)


class QualityScorer:
    """Scores cleaned chapter content for quality.

    Can score both SourceChapters (content quality) and SourceTitles
    (metadata completeness).
    """

    def score_chapter(
        self,
        paragraphs: list[str],
        word_count: int,
    ) -> QualitySignals:
        """Score a cleaned chapter.

        Args:
            paragraphs: List of cleaned paragraph strings.
            word_count: Total word count from CleaningResult.

        Returns:
            QualitySignals with individual sub-scores and final_score.
        """
        signals = QualitySignals(
            word_count=word_count,
            paragraph_count=len(paragraphs),
        )

        if paragraphs:
            signals.avg_paragraph_length = word_count / len(paragraphs)

        # ── length score ────────────────────────────────────────────────────
        if word_count == 0:
            signals.length_score = 0.0
            signals.notes.append("empty content")
        elif word_count < MIN_EXPECTED_WORDS:
            signals.length_score = word_count / MIN_EXPECTED_WORDS * 0.5
            signals.notes.append(f"short chapter ({word_count} words)")
        elif word_count > MAX_EXPECTED_WORDS:
            signals.length_score = 0.5
            signals.notes.append(f"suspiciously long ({word_count} words)")
        else:
            # Smooth score peaking at TARGET_WORDS
            ratio = min(word_count, TARGET_WORDS) / TARGET_WORDS
            signals.length_score = 0.5 + ratio * 0.5

        # ── structure score ─────────────────────────────────────────────────
        if signals.paragraph_count == 0:
            signals.structure_score = 0.0
        elif signals.paragraph_count == 1:
            signals.structure_score = 0.1
            signals.notes.append("single blob paragraph")
        elif signals.avg_paragraph_length > 500:
            signals.structure_score = 0.3
            signals.notes.append("unusually long average paragraph")
        else:
            pct = min(signals.paragraph_count, TARGET_PARAGRAPHS) / TARGET_PARAGRAPHS
            signals.structure_score = 0.4 + pct * 0.6

        # ── cleanliness score ───────────────────────────────────────────────
        full_text = "\n".join(paragraphs)
        boilerplate_hits = len(_BOILERPLATE_INDICATORS.findall(full_text))
        signals.boilerplate_hits = boilerplate_hits

        has_repetition = bool(_REPETITIVE_LINE_RE.search(full_text))
        signals.has_repetition = has_repetition

        cleanliness = 1.0
        if boilerplate_hits > 0:
            cleanliness -= min(boilerplate_hits * 0.1, 0.4)
            signals.notes.append(f"{boilerplate_hits} boilerplate hit(s)")
        if has_repetition:
            cleanliness -= 0.2
            signals.notes.append("repetitive content detected")

        signals.cleanliness_score = max(0.0, cleanliness)

        # ── final score ─────────────────────────────────────────────────────
        signals.final_score = round(
            0.35 * signals.length_score
            + 0.35 * signals.structure_score
            + 0.30 * signals.cleanliness_score,
            4,
        )

        return signals

    def score_metadata_completeness(self, raw_metadata: dict) -> float:
        """Return a completeness score (0.0–1.0) for a source's metadata.

        Used to set SourceTitle.quality_score and influence MetadataClaim
        confidence values.
        """
        important_fields = [
            "title",
            "synopsis",
            "author",
            "status",
            "cover_url",
            "genres",
        ]
        bonus_fields = [
            "original_title",
            "original_language",
            "translator_group",
            "total_chapters",
            "release_year",
            "tags",
        ]

        present_important = sum(
            1 for f in important_fields if raw_metadata.get(f)
        )
        present_bonus = sum(
            1 for f in bonus_fields if raw_metadata.get(f)
        )

        base = present_important / len(important_fields)
        bonus = (present_bonus / len(bonus_fields)) * 0.2

        return round(min(base + bonus, 1.0), 4)
