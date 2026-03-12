"""Integration tests for the campaign lifecycle through the API."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import src.db.database as db_mod
from src.db.models import Base


@pytest.fixture(scope="module")
async def _test_engine():
    """Create a single in-memory engine shared across all tests in this module."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture(autouse=True)
async def _patch_db(_test_engine):
    """Patch the database module to use the test engine for every test."""
    original_engine = db_mod.engine
    original_session = db_mod.AsyncSessionLocal
    db_mod.engine = _test_engine
    db_mod.AsyncSessionLocal = async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )
    yield
    db_mod.engine = original_engine
    db_mod.AsyncSessionLocal = original_session


@pytest.fixture
async def client(_test_engine, _patch_db):
    """Provide an async HTTP test client."""
    from src.api.app import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestSystemEndpoints:
    async def test_health_check(self, client: AsyncClient):
        resp = await client.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestCampaignCRUD:
    async def test_create_campaign(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/campaigns",
            json={"slug": "test-camp", "name": "Test Campaign"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["slug"] == "test-camp"
        assert data["status"] == "draft"

    async def test_get_campaign(self, client: AsyncClient):
        await client.post(
            "/api/v1/campaigns",
            json={"slug": "get-test", "name": "Get Test"},
        )
        resp = await client.get("/api/v1/campaigns/get-test")
        assert resp.status_code == 200
        assert resp.json()["slug"] == "get-test"

    async def test_get_nonexistent_returns_404(self, client: AsyncClient):
        resp = await client.get("/api/v1/campaigns/nonexistent")
        assert resp.status_code == 404

    async def test_list_campaigns(self, client: AsyncClient):
        await client.post("/api/v1/campaigns", json={"slug": "list-one", "name": "One"})
        await client.post("/api/v1/campaigns", json={"slug": "list-two", "name": "Two"})
        resp = await client.get("/api/v1/campaigns")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2

    async def test_duplicate_slug_returns_409(self, client: AsyncClient):
        await client.post("/api/v1/campaigns", json={"slug": "dup-slug", "name": "First"})
        resp = await client.post("/api/v1/campaigns", json={"slug": "dup-slug", "name": "Second"})
        assert resp.status_code == 409


class TestCampaignLifecycleAPI:
    async def test_full_lifecycle(self, client: AsyncClient):
        # Create
        await client.post("/api/v1/campaigns", json={"slug": "lifecycle", "name": "LC"})

        # Activate
        resp = await client.post("/api/v1/campaigns/lifecycle/activate")
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

        # Pause
        resp = await client.post("/api/v1/campaigns/lifecycle/pause")
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

        # Resume
        resp = await client.post("/api/v1/campaigns/lifecycle/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

        # Cancel
        resp = await client.post("/api/v1/campaigns/lifecycle/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    async def test_invalid_transition_returns_400(self, client: AsyncClient):
        await client.post("/api/v1/campaigns", json={"slug": "bad-trans", "name": "BT"})
        resp = await client.post("/api/v1/campaigns/bad-trans/pause")  # draft -> pause invalid
        assert resp.status_code == 400

    async def test_status_endpoint(self, client: AsyncClient):
        await client.post("/api/v1/campaigns", json={"slug": "status-test", "name": "ST"})
        resp = await client.get("/api/v1/campaigns/status-test/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "campaign" in data
        assert "post_counts" in data
