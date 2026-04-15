"""CoverCandidate — a possible cover image from a source."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novara.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from novara.models.source_title import SourceTitle


class CoverCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One cover image candidate sourced from a SourceTitle.

    Multiple candidates can exist across sources.  The cover resolver
    selects the best one (largest, highest quality, cleanest) and writes
    its id into Work.selected_cover_id.
    """

    __tablename__ = "cover_candidates"

    source_title_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_titles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Original URL from the source site
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    # Local path or object-storage key after download
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Dimensions as detected after download
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # File size in bytes
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Format: "jpeg" | "png" | "webp"
    image_format: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Composite quality score: resolution + aspect ratio + sharpness heuristics
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # True if the cover resolver has selected this as the best candidate
    is_selected: Mapped[bool] = mapped_column(nullable=False, default=False)

    source_title: Mapped[SourceTitle] = relationship(
        "SourceTitle", back_populates="cover_candidates"
    )

    def __repr__(self) -> str:
        return (
            f"<CoverCandidate id={self.id} "
            f"quality={self.quality_score} selected={self.is_selected}>"
        )
