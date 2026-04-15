"""VersionChapter — a chapter belonging to a specific Version."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novara.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from novara.models.source_chapter import SourceChapter
    from novara.models.version import Version


class VersionChapter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The resolved, readable chapter for a Version.

    This is what readers see.  The cleaned content is promoted from the
    best-quality SourceChapter via the chapter resolver.

    Multiple SourceChapter rows may map to the same VersionChapter
    (e.g. the same chapter available on two mirror sites).
    """

    __tablename__ = "version_chapters"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "chapter_number", name="uq_version_chapters_version_num"
        ),
    )

    version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Numeric ordering key (supports decimal e.g. 12.5 for interlude chapters)
    chapter_number: Mapped[float] = mapped_column(Float, nullable=False)

    # Resolved display title
    title: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Cleaned, resolved content ready for readers
    content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Word count of cleaned content
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # UUID of the SourceChapter this content was promoted from
    promoted_from_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    version: Mapped[Version] = relationship("Version", back_populates="chapters")
    source_chapters: Mapped[list[SourceChapter]] = relationship(
        "SourceChapter", back_populates="version_chapter"
    )

    def __repr__(self) -> str:
        return (
            f"<VersionChapter id={self.id} "
            f"chapter_number={self.chapter_number} version_id={self.version_id}>"
        )
