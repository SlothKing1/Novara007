"""Matching package — Work and Version deduplication logic."""

from novara.matching.version_matcher import VersionMatcher, VersionMatchResult
from novara.matching.work_matcher import MatchResult, WorkMatcher

__all__ = [
    "WorkMatcher",
    "MatchResult",
    "VersionMatcher",
    "VersionMatchResult",
]
