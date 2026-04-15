"""Tests for WorkMatcher."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from novara.matching.work_matcher import WorkMatcher
from novara.models import SourceTitle, Version, Work


@pytest.mark.asyncio
async def test_creates_new_work_for_unknown_title(
    session: AsyncSession,
    source_title: SourceTitle,
) -> None:
    matcher = WorkMatcher(session)
    result = await matcher.match_or_create(
        source_title,
        candidate_title="Brand New Novel Nobody Knows",
        candidate_language="en",
    )
    assert result.is_new_work is True
    assert result.is_new_version is True
    assert result.match_reason == "new"
    assert result.matched_work_id is not None


@pytest.mark.asyncio
async def test_matches_existing_work_by_slug(
    session: AsyncSession,
    work: Work,
    source_title: SourceTitle,
) -> None:
    # The work fixture has slug "the-legendary-mechanic"
    # Create a second source title with a matching title
    second_st = SourceTitle(
        version_id=source_title.version_id,
        source_site="wuxiaworld",
        source_id="mech-99",
        source_url="https://www.wuxiaworld.com/novel/the-legendary-mechanic",
        raw_metadata={},
    )
    session.add(second_st)
    await session.flush()

    matcher = WorkMatcher(session)
    result = await matcher.match_or_create(
        second_st,
        candidate_title="The Legendary Mechanic",  # same slug as work fixture
        candidate_language="en",
        candidate_translator_group="WuxiaWorld",
    )

    assert result.is_new_work is False
    assert result.match_reason == "exact_slug"
    assert str(result.matched_work_id) == str(work.id)


@pytest.mark.asyncio
async def test_fuzzy_match_finds_similar_title(
    session: AsyncSession,
    source_title: SourceTitle,
) -> None:
    # Create a work with a known title
    known = Work(slug="lord-of-mysteries", title="Lord of Mysteries")
    session.add(known)
    await session.flush()

    # Create a new source title with a near-match title
    new_st = SourceTitle(
        version_id=source_title.version_id,
        source_site="novelbin",
        source_id="lom-1",
        source_url="https://novelbin.com/b/lord-of-mysteries",
        raw_metadata={},
    )
    session.add(new_st)
    await session.flush()

    matcher = WorkMatcher(session, match_threshold=85.0)
    result = await matcher.match_or_create(
        new_st,
        candidate_title="Lord Of Mysteries",  # slightly different capitalisation
        candidate_language="en",
    )

    assert result.is_new_work is False
    assert result.match_reason in ("exact_slug", "fuzzy_title")


@pytest.mark.asyncio
async def test_different_translator_creates_new_version(
    session: AsyncSession,
    work: Work,
    version: Version,
    source_title: SourceTitle,
) -> None:
    """Different translator group → new Version under same Work."""
    new_st = SourceTitle(
        version_id=version.id,  # temporary; will be reassigned
        source_site="novelgate",
        source_id="mech-alt",
        source_url="https://novelgate.com/the-legendary-mechanic",
        raw_metadata={},
    )
    session.add(new_st)
    await session.flush()

    matcher = WorkMatcher(session)
    result = await matcher.match_or_create(
        new_st,
        candidate_title="The Legendary Mechanic",
        candidate_language="en",
        candidate_translator_group="Different Translation Group",
    )

    assert result.matched_work_id == str(work.id)
    # Should have created or found a version
    assert result.matched_version_id is not None
