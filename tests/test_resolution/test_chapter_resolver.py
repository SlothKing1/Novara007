"""Tests for ChapterResolver."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from novara.models import SourceChapter, SourceTitle, Version, VersionChapter
from novara.resolution.chapter_resolver import ChapterResolver


@pytest.mark.asyncio
async def test_creates_version_chapter_stub(
    session: AsyncSession,
    version: Version,
    source_title: SourceTitle,
) -> None:
    """Resolver should create VersionChapter from SourceChapter data."""
    sc = SourceChapter(
        source_title_id=source_title.id,
        source_url="https://example.com/chapter/5",
        source_chapter_id="5",
        chapter_number=5.0,
        source_title_text="Chapter 5",
        raw_content="<p>Chapter content here.</p><p>More content.</p>",
    )
    session.add(sc)
    await session.flush()

    resolver = ChapterResolver(session)
    report = await resolver.resolve(version)

    assert report.chapters_mapped >= 1

    await session.refresh(sc)
    assert sc.version_chapter_id is not None

    vc = await session.get(VersionChapter, sc.version_chapter_id)
    assert vc is not None
    assert vc.chapter_number == 5.0


@pytest.mark.asyncio
async def test_promotes_cleaned_content(
    session: AsyncSession,
    version: Version,
    source_title: SourceTitle,
) -> None:
    """Resolver should clean raw content and promote to VersionChapter."""
    sc = SourceChapter(
        source_title_id=source_title.id,
        source_url="https://example.com/chapter/1",
        source_chapter_id="ch1",
        chapter_number=1.0,
        source_title_text="Chapter 1 — The Beginning",
        raw_content=(
            "<div class='chapter-content'>"
            "<p>The hero stood at the edge of the world.</p>"
            "<p>Below him: nothing.</p>"
            "<p>Above him: stars.</p>"
            "</div>"
        ),
    )
    session.add(sc)
    await session.flush()

    resolver = ChapterResolver(session)
    report = await resolver.resolve(version)

    await session.refresh(sc)
    assert sc.cleaned_content is not None
    assert sc.quality_score is not None

    if sc.version_chapter_id:
        vc = await session.get(VersionChapter, sc.version_chapter_id)
        assert vc is not None
        assert vc.content is not None
        assert report.chapters_promoted >= 1


@pytest.mark.asyncio
async def test_picks_best_quality_source_chapter(
    session: AsyncSession,
    version: Version,
    source_title: SourceTitle,
) -> None:
    """When multiple SourceChapters exist for same chapter, best quality wins."""
    vc = VersionChapter(
        version_id=version.id,
        chapter_number=10.0,
        title="Chapter 10",
    )
    session.add(vc)
    await session.flush()

    # Low quality chapter
    low = SourceChapter(
        source_title_id=source_title.id,
        version_chapter_id=vc.id,
        source_url="https://example.com/ch10-low",
        source_chapter_id="ch10_low",
        chapter_number=10.0,
        raw_content="<p>bad.</p>",
        cleaned_content="bad.",
        quality_score=0.2,
        word_count=1,
    )
    # High quality chapter
    good_content = " ".join(["Great story paragraph." for _ in range(20)])
    high = SourceChapter(
        source_title_id=source_title.id,
        version_chapter_id=vc.id,
        source_url="https://example.com/ch10-high",
        source_chapter_id="ch10_high",
        chapter_number=10.0,
        raw_content=f"<p>{good_content}</p>",
        cleaned_content=good_content,
        quality_score=0.9,
        word_count=60,
    )
    session.add_all([low, high])
    await session.flush()

    resolver = ChapterResolver(session)
    await resolver.resolve(version)

    await session.refresh(vc)
    # The high quality chapter should have been promoted
    assert vc.promoted_from_id == high.id
