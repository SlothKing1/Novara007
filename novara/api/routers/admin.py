"""Admin API — source health, metadata claims, resolution triggers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from novara.api.schemas.admin import (
    MetadataClaimResponse,
    ResolveWorkRequest,
    SourceHealthResponse,
    SourceTitleResponse,
)
from novara.database import get_session
from novara.models import (
    IngestionJob,
    MetadataClaim,
    SourceChapter,
    SourceTitle,
    Version,
    Work,
)
from novara.resolution.chapter_resolver import ChapterResolver
from novara.resolution.cover_resolver import CoverResolver
from novara.resolution.metadata_resolver import MetadataResolver

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/sources/health", response_model=list[SourceHealthResponse])
async def source_health(
    session: AsyncSession = Depends(get_session),
) -> list[SourceHealthResponse]:
    """Return health summary per source site."""
    site_rows = await session.execute(
        select(SourceTitle.source_site)
        .distinct()
        .order_by(SourceTitle.source_site)
    )
    sites = [row[0] for row in site_rows]

    results = []
    for site in sites:
        st_count = await session.scalar(
            select(func.count(SourceTitle.id)).where(
                SourceTitle.source_site == site
            )
        ) or 0

        sc_count = await session.scalar(
            select(func.count(SourceChapter.id))
            .join(SourceTitle, SourceChapter.source_title_id == SourceTitle.id)
            .where(SourceTitle.source_site == site)
        ) or 0

        avg_quality = await session.scalar(
            select(func.avg(SourceChapter.quality_score))
            .join(SourceTitle, SourceChapter.source_title_id == SourceTitle.id)
            .where(
                SourceTitle.source_site == site,
                SourceChapter.quality_score.is_not(None),
            )
        )

        last_job = await session.scalar(
            select(IngestionJob)
            .where(IngestionJob.source_site == site)
            .order_by(IngestionJob.created_at.desc())
            .limit(1)
        )

        results.append(
            SourceHealthResponse(
                source_site=site,
                total_source_titles=st_count,
                total_source_chapters=sc_count,
                avg_chapter_quality=float(avg_quality) if avg_quality else None,
                last_job_status=last_job.status if last_job else None,
                last_scraped_at=last_job.completed_at if last_job else None,
            )
        )

    return results


@router.get("/sources/{source_site}", response_model=list[SourceTitleResponse])
async def list_source_titles(
    source_site: str,
    session: AsyncSession = Depends(get_session),
) -> list[SourceTitleResponse]:
    """List all SourceTitles for a given source site."""
    titles = list(
        await session.scalars(
            select(SourceTitle)
            .where(SourceTitle.source_site == source_site)
            .order_by(SourceTitle.created_at.desc())
        )
    )
    return [
        SourceTitleResponse(
            id=st.id,
            version_id=st.version_id,
            source_site=st.source_site,
            source_id=st.source_id,
            source_url=st.source_url,
            quality_score=st.quality_score,
            last_scraped_at=st.last_scraped_at,
            is_metadata_authoritative=st.is_metadata_authoritative,
            created_at=st.created_at,
        )
        for st in titles
    ]


@router.get(
    "/works/{work_id}/claims",
    response_model=list[MetadataClaimResponse],
)
async def list_metadata_claims(
    work_id: uuid.UUID,
    field_name: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[MetadataClaimResponse]:
    """List all MetadataClaims for a Work, optionally filtered by field."""
    work = await session.get(Work, work_id)
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")

    stmt = (
        select(MetadataClaim)
        .join(SourceTitle, MetadataClaim.source_title_id == SourceTitle.id)
        .join(Version, SourceTitle.version_id == Version.id)
        .where(Version.work_id == work_id)
        .order_by(MetadataClaim.field_name, MetadataClaim.confidence.desc())
    )
    if field_name:
        stmt = stmt.where(MetadataClaim.field_name == field_name)

    claims = list(await session.scalars(stmt))
    return [
        MetadataClaimResponse(
            id=c.id,
            source_title_id=c.source_title_id,
            field_name=c.field_name,
            raw_value=c.raw_value,
            normalised_value=c.normalised_value,
            confidence=c.confidence,
            is_resolved=c.is_resolved,
            created_at=c.created_at,
        )
        for c in claims
    ]


@router.post("/resolve")
async def trigger_resolution(
    body: ResolveWorkRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Trigger resolution passes for a Work.

    This re-runs metadata, cover, and/or chapter resolution without
    re-scraping any source data.
    """
    work = await session.get(Work, body.work_id)
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")

    report: dict = {"work_id": str(work.id)}

    if body.resolve_metadata:
        resolver = MetadataResolver(session)
        meta_report = await resolver.resolve(work)
        report["metadata"] = {
            "resolved": meta_report.fields_resolved,
            "skipped": meta_report.fields_skipped,
        }

    if body.resolve_covers:
        cover_resolver = CoverResolver(session)
        winner = await cover_resolver.resolve(work)
        report["cover"] = {
            "selected_cover_id": str(winner.id) if winner else None,
        }

    if body.resolve_chapters:
        versions = list(
            await session.scalars(
                select(Version).where(Version.work_id == work.id)
            )
        )
        chapter_reports = []
        for version in versions:
            chapter_resolver = ChapterResolver(session)
            ch_report = await chapter_resolver.resolve(version)
            chapter_reports.append(
                {
                    "version_id": ch_report.version_id,
                    "mapped": ch_report.chapters_mapped,
                    "promoted": ch_report.chapters_promoted,
                    "skipped": ch_report.chapters_skipped,
                }
            )
        report["chapters"] = chapter_reports

    return report
