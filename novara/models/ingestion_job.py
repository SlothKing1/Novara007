"""IngestionJob — tracks a single ingestion run for a source."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from novara.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class IngestionJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Audit log for ingestion runs.

    One IngestionJob is created per scrape attempt of a SourceTitle.
    Status transitions: pending → running → completed | failed.
    """

    __tablename__ = "ingestion_jobs"

    # Which source site triggered this job
    source_site: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    # URL that was ingested
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    # FK to the SourceTitle if already linked; null for discovery jobs
    source_title_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_titles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Job type: "discover" | "chapters" | "chapter" | "covers" | "full"
    job_type: Mapped[str] = mapped_column(Text, nullable=False, default="full")

    # pending | running | completed | failed | skipped
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")

    # Error message if status == "failed"
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Error traceback if status == "failed"
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Counts for observability
    chapters_found: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapters_new: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapters_updated: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Additional metadata the adapter wants to persist
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<IngestionJob id={self.id} site={self.source_site!r} "
            f"status={self.status!r}>"
        )
