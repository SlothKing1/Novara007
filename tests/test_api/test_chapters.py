"""Tests for the Chapters API endpoints."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from novara.api.main import app
from novara.database import get_session
from novara.models import Version, VersionChapter


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncClient:
    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_chapters_empty(
    client: AsyncClient,
    version: Version,
) -> None:
    resp = await client.get(f"/api/v1/versions/{version.id}/chapters")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 0
    assert str(data["version_id"]) == str(version.id)


@pytest.mark.asyncio
async def test_get_chapter(
    client: AsyncClient,
    version: Version,
    version_chapter: VersionChapter,
    session: AsyncSession,
) -> None:
    # Add content to the chapter
    version_chapter.content = "Han Xiao woke up.\n\nHe was reborn."
    version_chapter.word_count = 8
    await session.flush()

    resp = await client.get(
        f"/api/v1/versions/{version.id}/chapters/{version_chapter.chapter_number}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["chapter_number"] == 1.0
    assert data["title"] == "Chapter 1 — Rebirth"
    assert "Han Xiao" in (data["content"] or "")


@pytest.mark.asyncio
async def test_get_chapter_not_found(
    client: AsyncClient,
    version: Version,
) -> None:
    resp = await client.get(f"/api/v1/versions/{version.id}/chapters/9999.0")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_chapter_sources(
    client: AsyncClient,
    version: Version,
    version_chapter: VersionChapter,
    source_chapter,
) -> None:
    resp = await client.get(
        f"/api/v1/versions/{version.id}/chapters/{version_chapter.chapter_number}/sources"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["source_site"] == "royalroad"
