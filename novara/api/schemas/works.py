"""Pydantic schemas for Work and Version responses."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    label: str | None
    translator_group: str | None
    language: str
    version_type: str
    is_active: bool
    chapter_count: int = 0


class WorkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str | None
    original_language: str | None
    status: str | None
    synopsis: str | None
    selected_cover_id: uuid.UUID | None
    versions: list[VersionSummary] = []
    created_at: datetime
    updated_at: datetime


class WorkListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str | None
    original_language: str | None
    status: str | None
    selected_cover_id: uuid.UUID | None
    version_count: int = 0
    updated_at: datetime


class WorkListResponse(BaseModel):
    items: list[WorkListItem]
    total: int
    page: int
    page_size: int


class CreateWorkRequest(BaseModel):
    slug: str
    title: str | None = None
    original_language: str | None = None
    status: str | None = None
    synopsis: str | None = None


class CreateVersionRequest(BaseModel):
    slug: str
    label: str | None = None
    translator_group: str | None = None
    language: str = "en"
    version_type: str = "fan"
