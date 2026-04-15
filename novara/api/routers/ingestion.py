"""Admin API — ingestion job management."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novara.api.schemas.admin import IngestionJobResponse, TriggerIngestionRequest
from novara.database import get_session
from novara.ingestion.registry import list_adapters
from novara.models import IngestionJob, SourceTitle, Version

router = APIRouter(prefix="/ingestion", tags=["Ingestion"])


@router.get("/adapters")
async def list_registered_adapters() -> list[dict]:
    """List all registered source adapters."""
    return [
        {"site_key": key, "site_name": cls.SITE_NAME, "base_url": cls.BASE_URL}
        for key, cls in list_adapters().items()
    ]


@router.post("/jobs", response_model=IngestionJobResponse, status_code=202)
async def trigger_ingestion_job(
    body: TriggerIngestionRequest,
    session: AsyncSession = Depends(get_session),
) -> IngestionJobResponse:
    """Queue an ingestion job for a source URL.

    This creates the IngestionJob record and dispatches a Celery task.
    The actual scraping happens asynchronously.
    """
    # Validate adapter exists
    from novara.ingestion.registry import get_adapter

    try:
        get_adapter(body.source_site)
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"No adapter registered for site {body.source_site!r}",
        )

    # Find or create a SourceTitle stub for this URL
    source_title = await session.scalar(
        select(SourceTitle).where(SourceTitle.source_url == body.source_url)
    )

    job = IngestionJob(
        source_site=body.source_site,
        source_url=body.source_url,
        source_title_id=source_title.id if source_title else None,
        job_type="full" if body.scrape_content else "chapters",
        status="pending",
    )
    session.add(job)
    await session.flush()

    # Dispatch to Celery (import here to avoid circular at module level)
    try:
        from novara.tasks.ingestion_tasks import run_ingestion_job

        run_ingestion_job.delay(
            str(job.id),
            body.source_site,
            body.source_url,
            scrape_chapters=body.scrape_chapters,
            scrape_content=body.scrape_content,
        )
    except Exception:
        # Worker may not be running in dev; update job to reflect this
        job.status = "failed"
        job.error_message = "Failed to dispatch Celery task — is the worker running?"

    return IngestionJobResponse(
        id=job.id,
        source_site=job.source_site,
        source_url=job.source_url,
        source_title_id=job.source_title_id,
        job_type=job.job_type,
        status=job.status,
        error_message=job.error_message,
        chapters_found=job.chapters_found,
        chapters_new=job.chapters_new,
        chapters_updated=job.chapters_updated,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )


@router.get("/jobs", response_model=list[IngestionJobResponse])
async def list_jobs(
    source_site: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[IngestionJobResponse]:
    """List recent ingestion jobs, optionally filtered."""
    stmt = select(IngestionJob).order_by(IngestionJob.created_at.desc()).limit(limit)
    if source_site:
        stmt = stmt.where(IngestionJob.source_site == source_site)
    if status:
        stmt = stmt.where(IngestionJob.status == status)

    jobs = list(await session.scalars(stmt))
    return [
        IngestionJobResponse(
            id=j.id,
            source_site=j.source_site,
            source_url=j.source_url,
            source_title_id=j.source_title_id,
            job_type=j.job_type,
            status=j.status,
            error_message=j.error_message,
            chapters_found=j.chapters_found,
            chapters_new=j.chapters_new,
            chapters_updated=j.chapters_updated,
            started_at=j.started_at,
            completed_at=j.completed_at,
            created_at=j.created_at,
        )
        for j in jobs
    ]


@router.get("/jobs/{job_id}", response_model=IngestionJobResponse)
async def get_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> IngestionJobResponse:
    """Get a single ingestion job by ID."""
    job = await session.get(IngestionJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return IngestionJobResponse(
        id=job.id,
        source_site=job.source_site,
        source_url=job.source_url,
        source_title_id=job.source_title_id,
        job_type=job.job_type,
        status=job.status,
        error_message=job.error_message,
        chapters_found=job.chapters_found,
        chapters_new=job.chapters_new,
        chapters_updated=job.chapters_updated,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )
