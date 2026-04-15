"""Celery tasks for background ingestion and resolution."""

from __future__ import annotations

import asyncio
import traceback
import uuid
from datetime import datetime, timezone

import structlog

from novara.tasks.celery_app import celery_app

log = structlog.get_logger(__name__)


def _run_async(coro):  # type: ignore[no-untyped-def]
    """Run an async coroutine in a new event loop (for Celery worker context)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="novara.tasks.ingestion_tasks.run_ingestion_job",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def run_ingestion_job(
    self,  # type: ignore[no-untyped-def]
    job_id: str,
    source_site: str,
    source_url: str,
    *,
    scrape_chapters: bool = True,
    scrape_content: bool = True,
) -> dict:
    """Run a full ingestion job for a source URL.

    This task:
    1. Finds or creates the SourceTitle.
    2. Calls IngestionRunner to scrape metadata + chapters.
    3. Updates the IngestionJob with results.
    """
    log.info("ingestion_task_started", job_id=job_id, site=source_site, url=source_url)

    async def _inner() -> dict:
        from sqlalchemy import select

        from novara.database import async_session_factory
        from novara.ingestion.registry import get_adapter
        from novara.ingestion.runner import IngestionRunner
        from novara.models import IngestionJob, SourceTitle, Version, Work
        from novara.matching.work_matcher import WorkMatcher

        async with async_session_factory() as session:
            # Update job to running
            job = await session.get(IngestionJob, uuid.UUID(job_id))
            if not job:
                log.error("ingestion_job_not_found", job_id=job_id)
                return {"error": "job not found"}

            job.status = "running"
            job.started_at = datetime.now(tz=timezone.utc)
            await session.flush()

            try:
                # Find or create SourceTitle
                source_title = await session.scalar(
                    select(SourceTitle).where(SourceTitle.source_url == source_url)
                )

                if not source_title:
                    # Create a minimal SourceTitle stub so the runner can proceed.
                    # The WorkMatcher will assign it to a Work/Version after we
                    # have metadata.
                    adapter_cls = get_adapter(source_site)
                    adapter = adapter_cls()
                    source_id = adapter.extract_source_id(source_url)

                    source_title = SourceTitle(
                        source_site=source_site,
                        source_id=source_id,
                        source_url=source_url,
                        raw_metadata={},
                        # Temporary: will be updated after matching
                        version_id=await _get_or_create_placeholder_version(session),
                    )
                    session.add(source_title)
                    await session.flush()

                job.source_title_id = source_title.id

                # Run the ingestion
                runner = IngestionRunner(session)
                completed_job = await runner.ingest(
                    source_title,
                    scrape_chapters=scrape_chapters,
                    scrape_content=scrape_content,
                )

                # Now try to match to a Work
                if source_title.raw_metadata.get("title"):
                    matcher = WorkMatcher(session)
                    await matcher.match_or_create(
                        source_title,
                        candidate_title=source_title.raw_metadata["title"],
                        candidate_language=source_title.raw_metadata.get("language", "en"),
                        candidate_translator_group=source_title.raw_metadata.get(
                            "translator_group"
                        ),
                    )

                await session.commit()

                log.info(
                    "ingestion_task_completed",
                    job_id=job_id,
                    status=completed_job.status,
                    chapters_found=completed_job.chapters_found,
                )
                return {
                    "job_id": job_id,
                    "status": completed_job.status,
                    "chapters_found": completed_job.chapters_found,
                }

            except Exception as exc:
                await session.rollback()
                log.exception("ingestion_task_failed", job_id=job_id)

                # Update job to failed
                async with async_session_factory() as err_session:
                    err_job = await err_session.get(IngestionJob, uuid.UUID(job_id))
                    if err_job:
                        err_job.status = "failed"
                        err_job.error_message = str(exc)
                        err_job.error_detail = traceback.format_exc()
                        err_job.completed_at = datetime.now(tz=timezone.utc)
                        await err_session.commit()

                raise self.retry(exc=exc)

    return _run_async(_inner())


@celery_app.task(name="novara.tasks.ingestion_tasks.refresh_active_sources")
def refresh_active_sources() -> dict:
    """Periodic task: re-scrape all active SourceTitles to pick up new chapters."""
    async def _inner() -> dict:
        from sqlalchemy import select

        from novara.database import async_session_factory
        from novara.models import SourceTitle

        async with async_session_factory() as session:
            source_titles = list(
                await session.scalars(select(SourceTitle).order_by(SourceTitle.last_scraped_at.asc()))
            )

        count = 0
        for st in source_titles:
            run_ingestion_job.delay(
                str(uuid.uuid4()),  # new job ID
                st.source_site,
                st.source_url,
                scrape_chapters=True,
                scrape_content=True,
            )
            count += 1

        log.info("refresh_dispatched", count=count)
        return {"dispatched": count}

    return _run_async(_inner())


@celery_app.task(name="novara.tasks.ingestion_tasks.resolve_work")
def resolve_work_task(work_id: str) -> dict:
    """Run all resolution passes for a Work."""
    async def _inner() -> dict:
        from sqlalchemy import select

        from novara.database import async_session_factory
        from novara.models import Version, Work
        from novara.resolution.chapter_resolver import ChapterResolver
        from novara.resolution.cover_resolver import CoverResolver
        from novara.resolution.metadata_resolver import MetadataResolver

        async with async_session_factory() as session:
            work = await session.get(Work, uuid.UUID(work_id))
            if not work:
                return {"error": "work not found"}

            meta = MetadataResolver(session)
            await meta.resolve(work)

            covers = CoverResolver(session)
            await covers.resolve(work)

            versions = list(
                await session.scalars(
                    select(Version).where(Version.work_id == work.id)
                )
            )
            for version in versions:
                chapter_resolver = ChapterResolver(session)
                await chapter_resolver.resolve(version)

            await session.commit()

        return {"work_id": work_id, "status": "resolved"}

    return _run_async(_inner())


async def _get_or_create_placeholder_version(session) -> uuid.UUID:  # type: ignore[no-untyped-def]
    """Create a minimal placeholder Version for initial SourceTitle creation.

    This will be re-pointed to the correct Version after WorkMatcher runs.
    """
    from novara.models import Version, Work

    placeholder_work = Work(slug=f"__placeholder_{uuid.uuid4().hex[:8]}__")
    session.add(placeholder_work)
    await session.flush()

    placeholder_version = Version(
        work_id=placeholder_work.id,
        slug="placeholder",
        language="en",
        version_type="fan",
    )
    session.add(placeholder_version)
    await session.flush()

    return placeholder_version.id
