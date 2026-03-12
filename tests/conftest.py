"""Shared fixtures for Campaign Cannon 2 tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, Campaign, CampaignStatus, Platform, Post, PostStatus


@pytest.fixture
async def engine():
    """Create a fresh in-memory database engine for each test."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    """Provide an async session that rolls back after each test."""
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as sess:
        async with sess.begin():
            yield sess
            await sess.rollback()


@pytest.fixture
async def campaign(session: AsyncSession) -> Campaign:
    """Create a basic draft campaign."""
    c = Campaign(
        slug="test-campaign",
        name="Test Campaign",
        description="A test campaign",
        timezone="UTC",
        catch_up=False,
        status=CampaignStatus.draft,
    )
    session.add(c)
    await session.flush()
    return c


@pytest.fixture
async def active_campaign(session: AsyncSession) -> Campaign:
    """Create an active campaign."""
    c = Campaign(
        slug="active-campaign",
        name="Active Campaign",
        status=CampaignStatus.active,
    )
    session.add(c)
    await session.flush()
    return c


@pytest.fixture
async def post_factory(session: AsyncSession):
    """Factory to create posts with sane defaults."""
    _counter = 0

    async def _create(
        campaign_id: str,
        *,
        platform: Platform = Platform.twitter,
        copy: str = "Hello world",
        scheduled_at: datetime | None = None,
        status: PostStatus = PostStatus.draft,
        subreddit: str | None = None,
    ) -> Post:
        nonlocal _counter
        _counter += 1
        if scheduled_at is None:
            scheduled_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        p = Post(
            campaign_id=campaign_id,
            platform=platform,
            copy=copy,
            scheduled_at=scheduled_at,
            status=status,
            subreddit=subreddit,
            dedup_key=f"test-dedup-{_counter}",
        )
        session.add(p)
        await session.flush()
        return p

    return _create
