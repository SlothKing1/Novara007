"""MetadataClaim — a single field-level claim from a source."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novara.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from novara.models.source_title import SourceTitle


# All recognised metadata field names
METADATA_FIELDS = frozenset(
    {
        "title",
        "original_title",
        "synopsis",
        "status",
        "original_language",
        "author",
        "artist",
        "genres",
        "tags",
        "total_chapters",
        "release_year",
        "release_frequency",
        "translator_group",
        "publisher",
        "cover_url",
    }
)


class MetadataClaim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A claim from a SourceTitle about a single metadata field.

    Resolution logic in novara.resolution.metadata_resolver picks the
    winning claim per field based on source quality scores and field-specific
    priority rules.

    Claims are never deleted; instead a new claim is created each scrape so
    that history is preserved and re-resolution can happen offline.
    """

    __tablename__ = "metadata_claims"
    __table_args__ = (
        UniqueConstraint(
            "source_title_id",
            "field_name",
            "claim_hash",
            name="uq_metadata_claims_source_field_hash",
        ),
    )

    source_title_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_titles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # One of the recognised METADATA_FIELDS values
    field_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    # Raw string value as seen from the source (always preserved)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)

    # Normalised value after light standardisation (e.g. status → "ongoing")
    normalised_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    # MD5 of raw_value used for deduplication within the same source+field
    claim_hash: Mapped[str] = mapped_column(Text, nullable=False)

    # Confidence in this claim: 0.0–1.0
    # Derived from source quality_score + field-specific heuristics
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    # Whether this claim was selected as the winner for its field
    is_resolved: Mapped[bool] = mapped_column(nullable=False, default=False)

    source_title: Mapped[SourceTitle] = relationship(
        "SourceTitle", back_populates="metadata_claims"
    )

    def __repr__(self) -> str:
        return (
            f"<MetadataClaim id={self.id} field={self.field_name!r} "
            f"confidence={self.confidence:.2f}>"
        )
