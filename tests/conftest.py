"""Shared pytest fixtures."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from novara.models import Base, Version, VersionChapter, Work
from novara.models.source_chapter import SourceChapter
from novara.models.source_title import SourceTitle


# ── In-memory SQLite database for tests ─────────────────────────────────────

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create a test database engine with the full schema."""
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a fresh async session for each test, rolled back after."""
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.rollback()


# ── Domain object fixtures ───────────────────────────────────────────────────

@pytest_asyncio.fixture
async def work(session: AsyncSession) -> Work:
    w = Work(slug="the-legendary-mechanic", title="The Legendary Mechanic")
    session.add(w)
    await session.flush()
    return w


@pytest_asyncio.fixture
async def version(session: AsyncSession, work: Work) -> Version:
    v = Version(
        work_id=work.id,
        slug="en-wuxiaworld",
        label="WuxiaWorld (EN)",
        translator_group="WuxiaWorld",
        language="en",
        version_type="fan",
    )
    session.add(v)
    await session.flush()
    return v


@pytest_asyncio.fixture
async def source_title(session: AsyncSession, version: Version) -> SourceTitle:
    st = SourceTitle(
        version_id=version.id,
        source_site="royalroad",
        source_id="12345",
        source_url="https://www.royalroad.com/fiction/12345/the-legendary-mechanic",
        raw_metadata={},
    )
    session.add(st)
    await session.flush()
    return st


@pytest_asyncio.fixture
async def version_chapter(session: AsyncSession, version: Version) -> VersionChapter:
    vc = VersionChapter(
        version_id=version.id,
        chapter_number=1.0,
        title="Chapter 1 — Rebirth",
    )
    session.add(vc)
    await session.flush()
    return vc


@pytest_asyncio.fixture
async def source_chapter(
    session: AsyncSession,
    source_title: SourceTitle,
    version_chapter: VersionChapter,
) -> SourceChapter:
    sc = SourceChapter(
        source_title_id=source_title.id,
        version_chapter_id=version_chapter.id,
        source_url="https://www.royalroad.com/fiction/12345/chapter/1",
        source_chapter_id="1",
        chapter_number=1.0,
        source_title_text="Chapter 1 — Rebirth",
        raw_content="<div class='chapter-content'><p>Han Xiao woke up.</p><p>He was alive.</p></div>",
    )
    session.add(sc)
    await session.flush()
    return sc
