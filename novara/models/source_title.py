"""SourceTitle — one source site's representation of a Version/Work."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novara.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from novara.models.cover_candidate import CoverCandidate
    from novara.models.metadata_claim import MetadataClaim
    from novara.models.source_chapter import SourceChapter
    from novara.models.version import Version


class SourceTitle(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One site's page / listing for a story.

    Each SourceTitle belongs to exactly one Version (which belongs to one Work).
    A single Version may have many SourceTitles (same translator, many hosts).

    Raw scraped data is preserved here before any normalisation.
    MetadataClaim rows record individual field-level claims from this source.
    """

    __tablename__ = "source_titles"
    __table_args__ = (
        UniqueConstraint("source_site", "source_id", name="uq_source_titles_site_id"),
    )

    version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Short identifier for the source (e.g. "royalroad", "wuxiaworld")
    source_site: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    # Site-internal ID (novel ID from that site's URL / data)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)

    # Canonical URL for the title page on the source site
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    # Raw scraped metadata blob — never overwritten, append-only history via updated_at
    raw_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Overall quality score for this source (0.0–1.0), set by the scorer
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Timestamp of the most recent successful scrape
    last_scraped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Whether this source is considered authoritative for metadata resolution
    is_metadata_authoritative: Mapped[bool] = mapped_column(
        nullable=False, default=False
    )

    version: Mapped[Version] = relationship("Version", back_populates="source_titles")
    metadata_claims: Mapped[list[MetadataClaim]] = relationship(
        "MetadataClaim", back_populates="source_title", cascade="all, delete-orphan"
    )
    source_chapters: Mapped[list[SourceChapter]] = relationship(
        "SourceChapter", back_populates="source_title", cascade="all, delete-orphan"
    )
    cover_candidates: Mapped[list[CoverCandidate]] = relationship(
        "CoverCandidate", back_populates="source_title", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<SourceTitle id={self.id} site={self.source_site!r} "
            f"source_id={self.source_id!r}>"
        )
