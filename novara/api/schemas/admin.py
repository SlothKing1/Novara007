"""Pydantic schemas for admin and ingestion endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IngestionJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_site: str
    source_url: str
    source_title_id: uuid.UUID | None
    job_type: str
    status: str
    error_message: str | None
    chapters_found: int | None
    chapters_new: int | None
    chapters_updated: int | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class TriggerIngestionRequest(BaseModel):
    source_site: str
    source_url: str
    scrape_chapters: bool = True
    scrape_content: bool = True


class SourceTitleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_id: uuid.UUID
    source_site: str
    source_id: str
    source_url: str
    quality_score: float | None
    last_scraped_at: datetime | None
    is_metadata_authoritative: bool
    created_at: datetime


class SourceHealthResponse(BaseModel):
    source_site: str
    total_source_titles: int
    total_source_chapters: int
    avg_chapter_quality: float | None
    last_job_status: str | None
    last_scraped_at: datetime | None


class MetadataClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_title_id: uuid.UUID
    field_name: str
    raw_value: str
    normalised_value: str | None
    confidence: float
    is_resolved: bool
    created_at: datetime


class ResolveWorkRequest(BaseModel):
    work_id: uuid.UUID
    resolve_metadata: bool = True
    resolve_covers: bool = True
    resolve_chapters: bool = True
