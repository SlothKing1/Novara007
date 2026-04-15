"""Celery application configuration."""

from celery import Celery

from novara.config import get_settings

settings = get_settings()

celery_app = Celery(
    "novara",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["novara.tasks.ingestion_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Retry failed tasks up to 3 times with exponential backoff
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Beat schedule for periodic ingestion updates
    beat_schedule={
        "refresh-active-sources-hourly": {
            "task": "novara.tasks.ingestion_tasks.refresh_active_sources",
            "schedule": 3600.0,  # every hour
        },
    },
)
