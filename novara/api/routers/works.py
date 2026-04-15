"""Public API — Works and Versions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from novara.api.schemas.works import (
    CreateVersionRequest,
    CreateWorkRequest,
    VersionSummary,
    WorkListItem,
    WorkListResponse,
    WorkResponse,
)
from novara.database import get_session
from novara.models import Version, VersionChapter, Work

router = APIRouter(prefix="/works", tags=["Works"])


@router.get("", response_model=WorkListResponse)
async def list_works(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    language: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> WorkListResponse:
    """List all Works with optional filtering."""
    stmt = select(Work)
    if status:
        stmt = stmt.where(Work.status == status)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = await session.scalar(count_stmt) or 0

    stmt = stmt.offset((page - 1) * page_size).limit(page_size).order_by(Work.updated_at.desc())
    works = list(await session.scalars(stmt))

    # Build items with version counts
    items = []
    for work in works:
        version_count = await session.scalar(
            select(func.count(Version.id)).where(Version.work_id == work.id)
        ) or 0
        items.append(
            WorkListItem(
                id=work.id,
                slug=work.slug,
                title=work.title,
                original_language=work.original_language,
                status=work.status,
                selected_cover_id=work.selected_cover_id,
                version_count=version_count,
                updated_at=work.updated_at,
            )
        )

    return WorkListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{work_id_or_slug}", response_model=WorkResponse)
async def get_work(
    work_id_or_slug: str,
    session: AsyncSession = Depends(get_session),
) -> WorkResponse:
    """Fetch a single Work by UUID or slug, with its Versions."""
    work = await _resolve_work(work_id_or_slug, session)

    # Load versions with chapter counts
    versions_raw = list(
        await session.scalars(
            select(Version)
            .where(Version.work_id == work.id)
            .order_by(Version.created_at)
        )
    )

    version_summaries = []
    for v in versions_raw:
        chapter_count = await session.scalar(
            select(func.count(VersionChapter.id)).where(
                VersionChapter.version_id == v.id
            )
        ) or 0
        version_summaries.append(
            VersionSummary(
                id=v.id,
                slug=v.slug,
                label=v.label,
                translator_group=v.translator_group,
                language=v.language,
                version_type=v.version_type,
                is_active=v.is_active,
                chapter_count=chapter_count,
            )
        )

    return WorkResponse(
        id=work.id,
        slug=work.slug,
        title=work.title,
        original_language=work.original_language,
        status=work.status,
        synopsis=work.synopsis,
        selected_cover_id=work.selected_cover_id,
        versions=version_summaries,
        created_at=work.created_at,
        updated_at=work.updated_at,
    )


@router.post("", response_model=WorkResponse, status_code=201)
async def create_work(
    body: CreateWorkRequest,
    session: AsyncSession = Depends(get_session),
) -> WorkResponse:
    """Manually create a Work record."""
    existing = await session.scalar(select(Work).where(Work.slug == body.slug))
    if existing:
        raise HTTPException(status_code=409, detail=f"Work with slug {body.slug!r} already exists")

    work = Work(
        slug=body.slug,
        title=body.title,
        original_language=body.original_language,
        status=body.status,
        synopsis=body.synopsis,
    )
    session.add(work)
    await session.flush()

    return WorkResponse(
        id=work.id,
        slug=work.slug,
        title=work.title,
        original_language=work.original_language,
        status=work.status,
        synopsis=work.synopsis,
        selected_cover_id=None,
        versions=[],
        created_at=work.created_at,
        updated_at=work.updated_at,
    )


@router.post("/{work_id}/versions", response_model=VersionSummary, status_code=201)
async def create_version(
    work_id: uuid.UUID,
    body: CreateVersionRequest,
    session: AsyncSession = Depends(get_session),
) -> VersionSummary:
    """Manually create a Version within a Work."""
    work = await session.get(Work, work_id)
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")

    existing = await session.scalar(
        select(Version).where(Version.work_id == work_id, Version.slug == body.slug)
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Version {body.slug!r} already exists")

    version = Version(
        work_id=work_id,
        slug=body.slug,
        label=body.label,
        translator_group=body.translator_group,
        language=body.language,
        version_type=body.version_type,
    )
    session.add(version)
    await session.flush()

    return VersionSummary(
        id=version.id,
        slug=version.slug,
        label=version.label,
        translator_group=version.translator_group,
        language=version.language,
        version_type=version.version_type,
        is_active=version.is_active,
        chapter_count=0,
    )


async def _resolve_work(work_id_or_slug: str, session: AsyncSession) -> Work:
    """Resolve work by UUID or slug; raise 404 if not found."""
    work: Work | None = None
    try:
        uid = uuid.UUID(work_id_or_slug)
        work = await session.get(Work, uid)
    except ValueError:
        work = await session.scalar(
            select(Work).where(Work.slug == work_id_or_slug)
        )
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")
    return work
