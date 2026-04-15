"""Resolution package — metadata, cover, and chapter resolvers."""

from novara.resolution.chapter_resolver import ChapterResolver, ChapterResolutionReport
from novara.resolution.cover_resolver import CoverResolver
from novara.resolution.metadata_resolver import MetadataResolver, ResolutionReport

__all__ = [
    "MetadataResolver",
    "ResolutionReport",
    "CoverResolver",
    "ChapterResolver",
    "ChapterResolutionReport",
]
