"""BoilerplateCleaner — removes site-specific boilerplate from chapter text."""

from __future__ import annotations

import re

# Patterns that commonly appear as boilerplate in scraped web novel chapters.
# Each entry is (description, compiled regex).
# Paragraphs fully matching any pattern are removed.
# Add source-specific patterns by extending BOILERPLATE_PATTERNS.

BOILERPLATE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Translator notes / disclaimers
    ("translator_note", re.compile(
        r"^\s*(translator'?s?\s+note|tl\s*note|tln?|t/n)[:\s]",
        re.IGNORECASE,
    )),
    # Editor notes
    ("editor_note", re.compile(
        r"^\s*(editor'?s?\s+note|ed\s*note|e/n)[:\s]",
        re.IGNORECASE,
    )),
    # Chapter end markers
    ("chapter_end", re.compile(
        r"^\s*[-—~*=\s]*(end\s+of\s+chapter|chapter\s+end|fin)[-—~*=\s]*$",
        re.IGNORECASE,
    )),
    # "Read on <site>" / "Visit <site> for more"
    ("read_on_site", re.compile(
        r"read\s+(this|the\s+latest|more|on|at|from)\s+(novel|chapter|update)",
        re.IGNORECASE,
    )),
    # Support the author
    ("support_author", re.compile(
        r"(support\s+the\s+(author|translator)|buy\s+the\s+(book|raw|raws))",
        re.IGNORECASE,
    )),
    # Piracy warning
    ("piracy_warning", re.compile(
        r"(if\s+you\s+are\s+reading\s+this\s+(novel|chapter)\s+on\s+any\s+other\s+site"
        r"|stolen\s+(novel|content)|this\s+chapter\s+is\s+stolen)",
        re.IGNORECASE,
    )),
    # "Previous chapter / Next chapter" navigation text
    ("chapter_nav", re.compile(
        r"^\s*(previous|next)\s+chapter\s*$",
        re.IGNORECASE,
    )),
    # Donation / Patreon lines
    ("donation", re.compile(
        r"(patreon|ko-fi|donate|paypal)\b",
        re.IGNORECASE,
    )),
    # Ad-like lines
    ("advertisement", re.compile(
        r"^\s*advertisement\s*$",
        re.IGNORECASE,
    )),
    # "Chapter X" standalone heading repeated in content
    ("bare_chapter_heading", re.compile(
        r"^\s*chapter\s+\d+(\.\d+)?\s*$",
        re.IGNORECASE,
    )),
    # "Volume X / Book X" standalone heading repeated in content
    ("bare_volume_heading", re.compile(
        r"^\s*(volume|book|arc|part)\s+\d+(\.\d+)?\s*$",
        re.IGNORECASE,
    )),
]


class BoilerplateCleaner:
    """Removes boilerplate paragraphs from cleaned chapter text.

    Works on a list of paragraph strings (output of HtmlCleaner).
    Paragraphs that fully match any boilerplate pattern are removed.
    Paragraphs that contain a boilerplate pattern inline are flagged
    but preserved — aggressive removal of inline boilerplate risks
    damaging valid narrative content.
    """

    def __init__(
        self,
        extra_patterns: list[re.Pattern[str]] | None = None,
    ) -> None:
        self._patterns = [p for _, p in BOILERPLATE_PATTERNS]
        if extra_patterns:
            self._patterns.extend(extra_patterns)

    def clean(self, paragraphs: list[str]) -> list[str]:
        """Return paragraphs with boilerplate entries removed.

        Args:
            paragraphs: List of paragraph strings from HtmlCleaner.

        Returns:
            Filtered list with boilerplate paragraphs removed.
        """
        result: list[str] = []
        for para in paragraphs:
            if not self._is_boilerplate(para):
                result.append(para)
        return result

    def _is_boilerplate(self, para: str) -> bool:
        stripped = para.strip()
        # Very short paragraphs that are only punctuation / whitespace
        if len(stripped) < 3:
            return True
        for pattern in self._patterns:
            if pattern.search(stripped):
                return True
        return False
