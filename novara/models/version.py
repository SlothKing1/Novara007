"""Version — a readable variant of a Work (translator, language, revision)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novara.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from novara.models.source_title import SourceTitle
    from novara.models.version_chapter import VersionChapter
    from novara.models.work import Work


class Version(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A readable translation or language variant of a Work.

    Examples of distinct Versions for the same Work:
    - Official English translation by publisher X
    - Fan translation by group "Wuxiaworld"
    - Fan translation by group "Qidian International"
    - Original Chinese / Korean / Japanese text

    The same translation group may publish on multiple sites; those are
    different SourceTitle records pointing to the same Version.
    """

    __tablename__ = "versions"
    __table_args__ = (
        UniqueConstraint("work_id", "slug", name="uq_versions_work_slug"),
    )

    work_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("works.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # URL-safe identifier within this work (e.g. "wuxiaworld-en", "official-en")
    slug: Mapped[str] = mapped_column(Text, nullable=False)

    # Human-readable label shown to readers
    label: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Translation group name (e.g. "Wuxiaworld", "Official", "Qidian")
    translator_group: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Language code of this version (e.g. "en", "zh", "ko")
    language: Mapped[str] = mapped_column(Text, nullable=False, default="en")

    # Classification: official | fan | mtl | original | revised
    version_type: Mapped[str] = mapped_column(Text, nullable=False, default="fan")

    # Is this version currently being updated?
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    work: Mapped[Work] = relationship("Work", back_populates="versions")
    source_titles: Mapped[list[SourceTitle]] = relationship(
        "SourceTitle", back_populates="version", cascade="all, delete-orphan"
    )
    chapters: Mapped[list[VersionChapter]] = relationship(
        "VersionChapter", back_populates="version", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Version id={self.id} slug={self.slug!r} work_id={self.work_id}>"
