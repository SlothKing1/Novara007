"""Initial schema — all core tables.

Revision ID: 0001
Revises: —
Create Date: 2026-04-15
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── works ────────────────────────────────────────────────────────────────
    op.create_table(
        "works",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("original_language", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("synopsis", sa.Text(), nullable=True),
        sa.Column("selected_cover_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_works_slug"),
    )
    op.create_index("ix_works_slug", "works", ["slug"])

    # ── versions ─────────────────────────────────────────────────────────────
    op.create_table(
        "versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("translator_group", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=False, server_default="en"),
        sa.Column("version_type", sa.Text(), nullable=False, server_default="fan"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("work_id", "slug", name="uq_versions_work_slug"),
    )
    op.create_index("ix_versions_work_id", "versions", ["work_id"])

    # ── source_titles ────────────────────────────────────────────────────────
    op.create_table(
        "source_titles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_site", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column(
            "raw_metadata", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("last_scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_metadata_authoritative",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_site", "source_id", name="uq_source_titles_site_id"
        ),
    )
    op.create_index("ix_source_titles_version_id", "source_titles", ["version_id"])
    op.create_index("ix_source_titles_source_site", "source_titles", ["source_site"])

    # ── metadata_claims ──────────────────────────────────────────────────────
    op.create_table(
        "metadata_claims",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "source_title_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("field_name", sa.Text(), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("normalised_value", sa.Text(), nullable=True),
        sa.Column("claim_hash", sa.Text(), nullable=False),
        sa.Column(
            "confidence", sa.Float(), nullable=False, server_default="0.5"
        ),
        sa.Column(
            "is_resolved", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_title_id"], ["source_titles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_title_id",
            "field_name",
            "claim_hash",
            name="uq_metadata_claims_source_field_hash",
        ),
    )
    op.create_index(
        "ix_metadata_claims_source_title_id", "metadata_claims", ["source_title_id"]
    )
    op.create_index(
        "ix_metadata_claims_field_name", "metadata_claims", ["field_name"]
    )

    # ── cover_candidates ─────────────────────────────────────────────────────
    op.create_table(
        "cover_candidates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "source_title_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("image_format", sa.Text(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column(
            "is_selected", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_title_id"], ["source_titles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cover_candidates_source_title_id",
        "cover_candidates",
        ["source_title_id"],
    )

    # ── version_chapters ─────────────────────────────────────────────────────
    op.create_table(
        "version_chapters",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chapter_number", sa.Float(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("promoted_from_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "version_id",
            "chapter_number",
            name="uq_version_chapters_version_num",
        ),
    )
    op.create_index(
        "ix_version_chapters_version_id", "version_chapters", ["version_id"]
    )

    # ── source_chapters ──────────────────────────────────────────────────────
    op.create_table(
        "source_chapters",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "source_title_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "version_chapter_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_chapter_id", sa.Text(), nullable=True),
        sa.Column("chapter_number", sa.Float(), nullable=True),
        sa.Column("source_title_text", sa.Text(), nullable=True),
        sa.Column("raw_content", sa.Text(), nullable=True),
        sa.Column("cleaned_content", sa.Text(), nullable=True),
        sa.Column("paragraph_count", sa.Integer(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("cleaner_version", sa.Text(), nullable=True),
        sa.Column("last_scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_cleaned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_title_id"], ["source_titles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["version_chapter_id"], ["version_chapters.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_source_chapters_source_title_id",
        "source_chapters",
        ["source_title_id"],
    )
    op.create_index(
        "ix_source_chapters_version_chapter_id",
        "source_chapters",
        ["version_chapter_id"],
    )

    # ── ingestion_jobs ───────────────────────────────────────────────────────
    op.create_table(
        "ingestion_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source_site", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column(
            "source_title_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "job_type", sa.Text(), nullable=False, server_default="full"
        ),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default="pending"
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("chapters_found", sa.Integer(), nullable=True),
        sa.Column("chapters_new", sa.Integer(), nullable=True),
        sa.Column("chapters_updated", sa.Integer(), nullable=True),
        sa.Column(
            "extra", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_title_id"], ["source_titles.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ingestion_jobs_source_site", "ingestion_jobs", ["source_site"]
    )
    op.create_index(
        "ix_ingestion_jobs_source_title_id",
        "ingestion_jobs",
        ["source_title_id"],
    )


def downgrade() -> None:
    op.drop_table("ingestion_jobs")
    op.drop_table("source_chapters")
    op.drop_table("version_chapters")
    op.drop_table("cover_candidates")
    op.drop_table("metadata_claims")
    op.drop_table("source_titles")
    op.drop_table("versions")
    op.drop_table("works")
