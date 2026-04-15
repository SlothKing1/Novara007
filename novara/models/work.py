"""Work — the abstract story, independent of any source or translator."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novara.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from novara.models.version import Version


class Work(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The canonical, source-agnostic record for a story.

    A Work is resolved from one or more SourceTitle records.
    It carries only the fields we are confident enough to promote from claims.
    Raw data always lives in SourceTitle / MetadataClaim.
    """

    __tablename__ = "works"
    __table_args__ = (UniqueConstraint("slug", name="uq_works_slug"),)

    # Human-readable unique identifier (e.g. "the-legendary-mechanic")
    slug: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    # Resolved canonical title — promoted from the best metadata claim
    title: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Original language code (e.g. "zh", "ko", "en", "jp")
    original_language: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Resolved status: ongoing | completed | hiatus | dropped
    status: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Resolved synopsis (best-quality claim wins)
    synopsis: Mapped[str | None] = mapped_column(Text, nullable=True)

    # UUID of the selected cover candidate (denormalised for fast reads)
    selected_cover_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    versions: Mapped[list[Version]] = relationship(
        "Version", back_populates="work", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Work id={self.id} slug={self.slug!r}>"
