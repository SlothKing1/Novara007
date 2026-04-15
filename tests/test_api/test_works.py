"""Tests for the Works API endpoints."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from novara.api.main import app
from novara.database import get_session
from novara.models import Work, Version


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncClient:
    """Async test client with overridden database session."""
    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_list_works_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/works")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["total"] >= 0


@pytest.mark.asyncio
async def test_create_and_get_work(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    resp = await client.post(
        "/api/v1/works",
        json={
            "slug": "test-novel-api",
            "title": "Test Novel",
            "original_language": "zh",
            "status": "ongoing",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "test-novel-api"
    assert data["title"] == "Test Novel"
    assert data["status"] == "ongoing"
    work_id = data["id"]

    # Fetch by ID
    resp2 = await client.get(f"/api/v1/works/{work_id}")
    assert resp2.status_code == 200
    assert resp2.json()["id"] == work_id

    # Fetch by slug
    resp3 = await client.get("/api/v1/works/test-novel-api")
    assert resp3.status_code == 200
    assert resp3.json()["slug"] == "test-novel-api"


@pytest.mark.asyncio
async def test_create_work_conflict(
    client: AsyncClient,
    work: Work,
) -> None:
    resp = await client.post(
        "/api/v1/works",
        json={"slug": work.slug},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_get_work_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/works/nonexistent-slug")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_version(
    client: AsyncClient,
    work: Work,
) -> None:
    resp = await client.post(
        f"/api/v1/works/{work.id}/versions",
        json={
            "slug": "en-official",
            "label": "Official English",
            "translator_group": "Publisher X",
            "language": "en",
            "version_type": "official",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "en-official"
    assert data["translator_group"] == "Publisher X"


@pytest.mark.asyncio
async def test_work_includes_versions(
    client: AsyncClient,
    work: Work,
    version: Version,
) -> None:
    resp = await client.get(f"/api/v1/works/{work.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["versions"]) >= 1
    version_slugs = [v["slug"] for v in data["versions"]]
    assert version.slug in version_slugs


@pytest.mark.asyncio
async def test_list_works_pagination(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    # Create several works
    for i in range(5):
        w = Work(slug=f"pagination-test-{i}", title=f"Novel {i}")
        session.add(w)
    await session.flush()

    resp = await client.get("/api/v1/works?page=1&page_size=3")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) <= 3
    assert data["page"] == 1
    assert data["page_size"] == 3
