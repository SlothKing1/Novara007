"""Pydantic schemas for chapter responses."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChapterListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chapter_number: float
    title: str | None
    word_count: int | None
    has_content: bool = False


class ChapterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_id: uuid.UUID
    chapter_number: float
    title: str | None
    content: str | None
    word_count: int | None
    promoted_from_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ChapterListResponse(BaseModel):
    items: list[ChapterListItem]
    total: int
    version_id: uuid.UUID


class SourceChapterSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_site: str
    source_url: str
    quality_score: float | None
    word_count: int | None
    is_promoted: bool = False
