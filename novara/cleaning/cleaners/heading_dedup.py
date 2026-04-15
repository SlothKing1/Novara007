"""HeadingDedup — removes repeated chapter titles from chapter body text.

Some sources repeat the chapter title 2–3 times at the top of the content:
once in the H1, once as the first paragraph, sometimes again as "Chapter X".

This cleaner removes leading paragraphs that are near-duplicate of the
chapter title so the reading experience starts cleanly with narrative text.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz


class HeadingDedup:
    """Removes leading heading repetitions from a list of paragraphs.

    Only looks at the first N paragraphs (configurable) to avoid false
    positives deep in the content.
    """

    def __init__(
        self,
        similarity_threshold: float = 85.0,
        max_heading_paragraphs: int = 4,
    ) -> None:
        """Args:
        similarity_threshold: Minimum fuzz ratio (0–100) to consider a
            paragraph a duplicate of the chapter title.
        max_heading_paragraphs: Only check this many paragraphs from the top.
        """
        self.similarity_threshold = similarity_threshold
        self.max_heading_paragraphs = max_heading_paragraphs

    def deduplicate(
        self,
        paragraphs: list[str],
        chapter_title: str | None,
    ) -> list[str]:
        """Remove leading paragraphs that duplicate the chapter title.

        Args:
            paragraphs: Cleaned paragraph list.
            chapter_title: The resolved chapter title (may be None).

        Returns:
            Paragraphs with heading duplicates removed from the top.
        """
        if not paragraphs or not chapter_title:
            return paragraphs

        normalised_title = _normalise(chapter_title)
        result = list(paragraphs)

        # We iterate forward but only within the heading window.
        # Build a set of indices to drop, then filter.
        to_drop: set[int] = set()
        window = min(self.max_heading_paragraphs, len(result))

        for i in range(window):
            para = result[i]
            normalised_para = _normalise(para)

            # Exact or near-exact match
            if fuzz.ratio(normalised_title, normalised_para) >= self.similarity_threshold:
                to_drop.add(i)
                continue

            # Bare chapter number patterns: "Chapter 42", "chapter 42 – Title"
            if _is_bare_heading(para):
                to_drop.add(i)
                continue

        return [p for i, p in enumerate(result) if i not in to_drop]


def _normalise(text: str) -> str:
    """Lowercase and strip punctuation for fuzzy comparison."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_BARE_HEADING_RE = re.compile(
    r"^\s*(chapter|ch\.?|vol\.?|volume|book|arc|part)?\s*\d+(\.\d+)?"
    r"(\s*[-–—:]\s*.{0,80})?\s*$",
    re.IGNORECASE,
)


def _is_bare_heading(text: str) -> bool:
    """Return True if the text looks like a standalone heading marker."""
    return bool(_BARE_HEADING_RE.fullmatch(text.strip()))
