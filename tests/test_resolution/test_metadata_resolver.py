"""Tests for MetadataResolver."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from novara.models import MetadataClaim, SourceTitle, Version, Work
from novara.resolution.metadata_resolver import MetadataResolver


@pytest.mark.asyncio
async def test_resolve_picks_highest_confidence(
    session: AsyncSession,
    work: Work,
    version: Version,
    source_title: SourceTitle,
) -> None:
    """The claim with highest confidence wins."""
    # Add a low-confidence claim
    low = MetadataClaim(
        source_title_id=source_title.id,
        field_name="title",
        raw_value="The Legendary Mechanic",
        claim_hash="hash_low",
        confidence=0.4,
    )
    # Add a high-confidence claim (same source, different hash = different scrape)
    high = MetadataClaim(
        source_title_id=source_title.id,
        field_name="title",
        raw_value="The Legendary Mechanic",
        claim_hash="hash_high",
        confidence=0.9,
    )
    session.add_all([low, high])
    await session.flush()

    resolver = MetadataResolver(session)
    report = await resolver.resolve(work)

    assert "title" in report.fields_resolved
    assert report.fields_resolved["title"] == "The Legendary Mechanic"
    # High confidence claim should be marked resolved
    await session.refresh(high)
    assert high.is_resolved is True
    await session.refresh(low)
    assert low.is_resolved is False


@pytest.mark.asyncio
async def test_resolve_promotes_to_work(
    session: AsyncSession,
    work: Work,
    version: Version,
    source_title: SourceTitle,
) -> None:
    """Resolved title and status should be written to Work."""
    session.add_all([
        MetadataClaim(
            source_title_id=source_title.id,
            field_name="title",
            raw_value="My Great Novel",
            claim_hash="title_hash",
            confidence=0.8,
        ),
        MetadataClaim(
            source_title_id=source_title.id,
            field_name="status",
            raw_value="ongoing",
            claim_hash="status_hash",
            confidence=0.7,
        ),
        MetadataClaim(
            source_title_id=source_title.id,
            field_name="synopsis",
            raw_value="A synopsis here.",
            claim_hash="synopsis_hash",
            confidence=0.6,
        ),
    ])
    await session.flush()

    resolver = MetadataResolver(session)
    await resolver.resolve(work)

    await session.refresh(work)
    assert work.title == "My Great Novel"
    assert work.status == "ongoing"
    assert work.synopsis == "A synopsis here."


@pytest.mark.asyncio
async def test_resolve_no_claims_returns_empty_report(
    session: AsyncSession,
    work: Work,
) -> None:
    resolver = MetadataResolver(session)
    report = await resolver.resolve(work)
    assert report.fields_resolved == {}
    assert work.title is not None  # Not overwritten
