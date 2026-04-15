"""Public API — Version Chapters."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from novara.api.schemas.chapters import (
    ChapterListItem,
    ChapterListResponse,
    ChapterResponse,
    SourceChapterSummary,
)
from novara.database import get_session
from novara.models import SourceChapter, SourceTitle, Version, VersionChapter

router = APIRouter(prefix="/versions", tags=["Chapters"])


@router.get("/{version_id}/chapters", response_model=ChapterListResponse)
async def list_chapters(
    version_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ChapterListResponse:
    """List all VersionChapters for a Version, ordered by chapter_number."""
    version = await session.get(Version, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    total = await session.scalar(
        select(func.count(VersionChapter.id)).where(
            VersionChapter.version_id == version_id
        )
    ) or 0

    chapters = list(
        await session.scalars(
            select(VersionChapter)
            .where(VersionChapter.version_id == version_id)
            .order_by(VersionChapter.chapter_number)
        )
    )

    items = [
        ChapterListItem(
            id=c.id,
            chapter_number=c.chapter_number,
            title=c.title,
            word_count=c.word_count,
            has_content=bool(c.content),
        )
        for c in chapters
    ]

    return ChapterListResponse(items=items, total=total, version_id=version_id)


@router.get("/{version_id}/chapters/{chapter_number}", response_model=ChapterResponse)
async def get_chapter(
    version_id: uuid.UUID,
    chapter_number: float,
    session: AsyncSession = Depends(get_session),
) -> ChapterResponse:
    """Fetch a single VersionChapter by version and chapter number."""
    chapter = await session.scalar(
        select(VersionChapter).where(
            VersionChapter.version_id == version_id,
            VersionChapter.chapter_number == chapter_number,
        )
    )
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    return ChapterResponse(
        id=chapter.id,
        version_id=chapter.version_id,
        chapter_number=chapter.chapter_number,
        title=chapter.title,
        content=chapter.content,
        word_count=chapter.word_count,
        promoted_from_id=chapter.promoted_from_id,
        created_at=chapter.created_at,
        updated_at=chapter.updated_at,
    )


@router.get(
    "/{version_id}/chapters/{chapter_number}/sources",
    response_model=list[SourceChapterSummary],
)
async def list_chapter_sources(
    version_id: uuid.UUID,
    chapter_number: float,
    session: AsyncSession = Depends(get_session),
) -> list[SourceChapterSummary]:
    """List all SourceChapters backing a VersionChapter (admin / debug view)."""
    vc = await session.scalar(
        select(VersionChapter).where(
            VersionChapter.version_id == version_id,
            VersionChapter.chapter_number == chapter_number,
        )
    )
    if not vc:
        raise HTTPException(status_code=404, detail="Chapter not found")

    source_chapters = list(
        await session.scalars(
            select(SourceChapter).where(
                SourceChapter.version_chapter_id == vc.id
            )
        )
    )

    result = []
    for sc in source_chapters:
        # Load the source site name from the parent SourceTitle
        st = await session.get(SourceTitle, sc.source_title_id)
        result.append(
            SourceChapterSummary(
                id=sc.id,
                source_site=st.source_site if st else "unknown",
                source_url=sc.source_url,
                quality_score=sc.quality_score,
                word_count=sc.word_count,
                is_promoted=(sc.id == vc.promoted_from_id),
            )
        )

    return result
