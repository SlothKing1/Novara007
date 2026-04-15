"""CleaningPipeline — orchestrates all cleaners into a single pass."""

from __future__ import annotations

from dataclasses import dataclass

import ftfy

from novara.cleaning.cleaners.boilerplate_cleaner import BoilerplateCleaner
from novara.cleaning.cleaners.heading_dedup import HeadingDedup
from novara.cleaning.cleaners.html_cleaner import HtmlCleaner
from novara.cleaning.cleaners.paragraph_fixer import ParagraphFixer

# Bump this when the pipeline logic changes so we can detect stale cleaned content
PIPELINE_VERSION = "1.0"


@dataclass
class CleaningResult:
    """Output of a single pipeline run."""

    paragraphs: list[str]
    word_count: int
    paragraph_count: int
    pipeline_version: str

    @property
    def content(self) -> str:
        """Paragraphs joined with double newline for storage."""
        return "\n\n".join(self.paragraphs)


class CleaningPipeline:
    """Processes raw chapter HTML through all cleaning stages.

    Pipeline stages (in order):
    1. Unicode repair (ftfy)
    2. HTML sanitisation and paragraph extraction (HtmlCleaner)
    3. Boilerplate removal (BoilerplateCleaner)
    4. Paragraph structure repair (ParagraphFixer)
    5. Heading deduplication (HeadingDedup)

    The pipeline is stateless and safe to call concurrently.
    All configuration is set at construction time.
    """

    def __init__(
        self,
        html_cleaner: HtmlCleaner | None = None,
        boilerplate_cleaner: BoilerplateCleaner | None = None,
        paragraph_fixer: ParagraphFixer | None = None,
        heading_dedup: HeadingDedup | None = None,
    ) -> None:
        self._html = html_cleaner or HtmlCleaner()
        self._boilerplate = boilerplate_cleaner or BoilerplateCleaner()
        self._para = paragraph_fixer or ParagraphFixer()
        self._dedup = heading_dedup or HeadingDedup()

    def run(
        self,
        raw_content: str,
        *,
        content_format: str = "html",
        chapter_title: str | None = None,
    ) -> CleaningResult:
        """Run the full cleaning pipeline on raw chapter content.

        Args:
            raw_content: Raw HTML or plain text from the adapter.
            content_format: "html" (default) or "text".
            chapter_title: The chapter's resolved title, used for heading dedup.

        Returns:
            CleaningResult with cleaned paragraphs and quality signals.
        """
        # Stage 1: Unicode repair
        repaired = ftfy.fix_text(raw_content)

        # Stage 2: HTML → paragraph list
        if content_format == "html":
            paragraphs = self._html.clean(repaired)
        else:
            # Plain text: split on double newlines
            paragraphs = [
                p.strip()
                for p in repaired.split("\n\n")
                if p.strip()
            ]

        # Stage 3: Boilerplate removal
        paragraphs = self._boilerplate.clean(paragraphs)

        # Stage 4: Paragraph structure repair
        paragraphs = self._para.fix(paragraphs)

        # Stage 5: Heading deduplication
        paragraphs = self._dedup.deduplicate(paragraphs, chapter_title)

        word_count = sum(len(p.split()) for p in paragraphs)

        return CleaningResult(
            paragraphs=paragraphs,
            word_count=word_count,
            paragraph_count=len(paragraphs),
            pipeline_version=PIPELINE_VERSION,
        )


# Module-level default pipeline instance for convenience
default_pipeline = CleaningPipeline()
