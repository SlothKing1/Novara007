"""ParagraphFixer — repairs common paragraph-structure problems.

Common issues found in scraped chapter text:
- One giant blob of text with no paragraph breaks
- Very long paragraphs that span what should be multiple paragraphs
- Orphan single words or numbers as standalone "paragraphs"
- Trailing/leading punctuation noise in otherwise valid paragraphs
"""

from __future__ import annotations

import re

# Heuristic: a paragraph this long that contains no sentence-ending punctuation
# is probably a blob that needs splitting.
BLOB_WORD_THRESHOLD = 500

# Sentence-ending punctuation patterns
_SENTENCE_END = re.compile(r'([.!?…]["\']?\s+)')

# Minimum word count for a paragraph to be considered valid standalone content
MIN_WORDS = 3


class ParagraphFixer:
    """Repairs paragraph structure issues in cleaned chapter text.

    Works on a list of paragraph strings.  The cleaner may:
    - Split overly long blob paragraphs at sentence boundaries
    - Merge orphan single-sentence fragments into the previous paragraph
      (only when they look like continuation, not new content)
    - Drop paragraphs below the minimum word threshold
    """

    def __init__(
        self,
        blob_word_threshold: int = BLOB_WORD_THRESHOLD,
        min_words: int = MIN_WORDS,
        split_blobs: bool = True,
        merge_orphans: bool = False,
    ) -> None:
        self.blob_word_threshold = blob_word_threshold
        self.min_words = min_words
        self.split_blobs = split_blobs
        self.merge_orphans = merge_orphans

    def fix(self, paragraphs: list[str]) -> list[str]:
        """Apply all paragraph structure fixes.

        Args:
            paragraphs: List of paragraph strings from HtmlCleaner.

        Returns:
            Repaired list of paragraph strings.
        """
        result: list[str] = []

        for para in paragraphs:
            if self.split_blobs and _word_count(para) >= self.blob_word_threshold:
                result.extend(self._split_blob(para))
            else:
                result.append(para)

        if self.merge_orphans:
            result = self._merge_orphans(result)

        # Drop paragraphs below minimum word count
        result = [p for p in result if _word_count(p) >= self.min_words]

        return result

    # ── private ───────────────────────────────────────────────────────────────

    def _split_blob(self, text: str) -> list[str]:
        """Split a blob paragraph at sentence boundaries."""
        parts = _SENTENCE_END.split(text)
        # Re-join the separator with its preceding sentence
        sentences: list[str] = []
        i = 0
        while i < len(parts):
            sentence = parts[i]
            if i + 1 < len(parts) and _SENTENCE_END.fullmatch(parts[i + 1]):
                sentence += parts[i + 1]
                i += 2
            else:
                i += 1
            stripped = sentence.strip()
            if stripped:
                sentences.append(stripped)

        # Group sentences into paragraphs of reasonable length
        # (aim for ~150 words per paragraph)
        groups: list[str] = []
        current_words = 0
        current_parts: list[str] = []
        for sentence in sentences:
            wc = _word_count(sentence)
            if current_words + wc > 200 and current_parts:
                groups.append(" ".join(current_parts))
                current_parts = [sentence]
                current_words = wc
            else:
                current_parts.append(sentence)
                current_words += wc
        if current_parts:
            groups.append(" ".join(current_parts))
        return groups or [text]

    def _merge_orphans(self, paragraphs: list[str]) -> list[str]:
        """Merge very short fragment paragraphs into the preceding one."""
        if not paragraphs:
            return paragraphs
        result = [paragraphs[0]]
        for para in paragraphs[1:]:
            if _word_count(para) < self.min_words and result:
                result[-1] = result[-1].rstrip() + " " + para.lstrip()
            else:
                result.append(para)
        return result


def _word_count(text: str) -> int:
    return len(text.split())
