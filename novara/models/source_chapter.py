"""SourceChapter — one source site's page for a chapter."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novara.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from novara.models.source_title import SourceTitle
    from novara.models.version_chapter import VersionChapter


class SourceChapter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Raw + cleaned chapter data from one source site.

    raw_content: exactly what was scraped — preserved forever.
    cleaned_content: output of the cleaning pipeline.
    quality_score: assigned by the quality scorer.

    The chapter resolver uses quality_score to decide which SourceChapter
    gets promoted to VersionChapter.content.
    """

    __tablename__ = "source_chapters"

    source_title_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_titles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Foreign key to the resolved chapter (nullable until resolution runs)
    version_chapter_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("version_chapters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # URL of this chapter on the source site
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    # Site-internal chapter identifier
    source_chapter_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Chapter number as parsed from the source (may differ between sites)
    chapter_number: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Title as seen on the source page
    source_title_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Raw HTML or text as scraped — never modified after initial write
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Output of the cleaning pipeline
    cleaned_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Paragraph count after cleaning
    paragraph_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Word count after cleaning
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Content quality score: 0.0–1.0 (set by quality scorer)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Cleaning pipeline version that produced cleaned_content
    cleaner_version: Mapped[str | None] = mapped_column(Text, nullable=True)

    last_scraped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_cleaned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    source_title: Mapped[SourceTitle] = relationship(
        "SourceTitle", back_populates="source_chapters"
    )
    version_chapter: Mapped[VersionChapter | None] = relationship(
        "VersionChapter", back_populates="source_chapters"
    )

    def __repr__(self) -> str:
        return (
            f"<SourceChapter id={self.id} "
            f"chapter_number={self.chapter_number} "
            f"quality={self.quality_score}>"
        )
