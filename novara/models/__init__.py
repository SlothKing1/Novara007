"""SQLAlchemy models — import all to register with the metadata."""

from novara.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from novara.models.cover_candidate import CoverCandidate
from novara.models.ingestion_job import IngestionJob
from novara.models.metadata_claim import MetadataClaim
from novara.models.source_chapter import SourceChapter
from novara.models.source_title import SourceTitle
from novara.models.version import Version
from novara.models.version_chapter import VersionChapter
from novara.models.work import Work

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "Work",
    "Version",
    "SourceTitle",
    "MetadataClaim",
    "CoverCandidate",
    "VersionChapter",
    "SourceChapter",
    "IngestionJob",
]
