"""Shared test fixtures for Campaign Cannon test suite."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

# ---------------------------------------------------------------------------
# We mock-import all Phase 1-3 modules so tests remain runnable even if the
# real implementations haven't landed yet.  Each test file patches what it
# needs; here we just set up the database layer.
# ---------------------------------------------------------------------------

# Try importing real models; fall back to lightweight stubs so fixtures work.
try:
    from campaign_cannon.db.models import Base, Campaign, Post, MediaAsset, PostLog
    from campaign_cannon.db.models import PostState, CampaignStatus, Platform
except ImportError:
    # Stub models — just enough for fixture signatures
    Base = None  # type: ignore


# ── Enum stubs used across tests ──────────────────────────────────────────

class _PostState:
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    PUBLISHING = "publishing"
    POSTED = "posted"
    FAILED = "failed"
    RETRY = "retry"
    DEAD_LETTER = "dead_letter"


class _CampaignStatus:
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class _Platform:
    TWITTER = "twitter"
    REDDIT = "reddit"
    LINKEDIN = "linkedin"


# Export canonical enum refs — tests import from here
try:
    from campaign_cannon.db.models import PostState, CampaignStatus, Platform
except ImportError:
    PostState = _PostState  # type: ignore
    CampaignStatus = _CampaignStatus  # type: ignore
    Platform = _Platform  # type: ignore


# ── Database fixtures ─────────────────────────────────────────────────────

@pytest.fixture()
def test_engine():
    """In-memory SQLite engine with WAL-like pragmas and all tables created."""
    engine = create_engine("sqlite:///:memory:", echo=False)

    # Enable WAL-like pragmas that work in memory
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    if Base is not None:
        Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def test_session(test_engine):
    """Session scoped per test with automatic rollback."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ── Factory helpers ───────────────────────────────────────────────────────

@pytest.fixture()
def sample_campaign(test_session):
    """Factory: create a Campaign with configurable fields."""

    def _factory(
        name="Test Campaign",
        slug=None,
        status=None,
        **kwargs,
    ):
        try:
            from campaign_cannon.db.models import Campaign, CampaignStatus as CS

            campaign = Campaign(
                id=uuid.uuid4(),
                name=name,
                slug=slug or f"test-{uuid.uuid4().hex[:8]}",
                status=status or CS.DRAFT,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                **kwargs,
            )
        except ImportError:
            # Lightweight dict stand-in
            campaign = MagicMock()
            campaign.id = uuid.uuid4()
            campaign.name = name
            campaign.slug = slug or f"test-{uuid.uuid4().hex[:8]}"
            campaign.status = status or "draft"
            campaign.created_at = datetime.now(timezone.utc)
            campaign.updated_at = datetime.now(timezone.utc)
            for k, v in kwargs.items():
                setattr(campaign, k, v)

        test_session.add(campaign)
        test_session.flush()
        return campaign

    return _factory


@pytest.fixture()
def sample_post(test_session, sample_campaign):
    """Factory: create a Post with all required fields + valid idempotency key."""

    def _factory(
        campaign=None,
        platform=None,
        state=None,
        body="Hello world! #test",
        scheduled_at=None,
        **kwargs,
    ):
        if campaign is None:
            campaign = sample_campaign()

        _platform = platform or "twitter"
        _scheduled_at = scheduled_at or (datetime.now(timezone.utc) + timedelta(hours=1))
        _idempotency_key = kwargs.pop(
            "idempotency_key",
            f"{campaign.id}-{_platform}-{uuid.uuid4().hex[:8]}",
        )

        try:
            from campaign_cannon.db.models import Post, PostState as PS, Platform as PL

            post = Post(
                id=uuid.uuid4(),
                campaign_id=campaign.id,
                platform=_platform,
                body=body,
                state=state or PS.DRAFT,
                scheduled_at=_scheduled_at,
                idempotency_key=_idempotency_key,
                retry_count=kwargs.pop("retry_count", 0),
                max_retries=kwargs.pop("max_retries", 3),
                version=kwargs.pop("version", 1),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                **kwargs,
            )
        except ImportError:
            post = MagicMock()
            post.id = uuid.uuid4()
            post.campaign_id = campaign.id
            post.platform = _platform
            post.body = body
            post.state = state or "draft"
            post.scheduled_at = _scheduled_at
            post.idempotency_key = _idempotency_key
            post.retry_count = kwargs.pop("retry_count", 0)
            post.max_retries = kwargs.pop("max_retries", 3)
            post.version = kwargs.pop("version", 1)
            post.platform_post_id = kwargs.pop("platform_post_id", None)
            post.created_at = datetime.now(timezone.utc)
            post.updated_at = datetime.now(timezone.utc)
            for k, v in kwargs.items():
                setattr(post, k, v)

        test_session.add(post)
        test_session.flush()
        return post

    return _factory


@pytest.fixture()
def sample_media_asset(test_session, tmp_path):
    """Factory: create a MediaAsset with a temp file."""

    def _factory(
        post_id=None,
        mime_type="image/jpeg",
        size_bytes=1024,
        **kwargs,
    ):
        file_path = tmp_path / f"{uuid.uuid4().hex}.jpg"
        file_path.write_bytes(b"\xff\xd8\xff" + b"\x00" * (size_bytes - 3))

        try:
            from campaign_cannon.db.models import MediaAsset

            asset = MediaAsset(
                id=uuid.uuid4(),
                post_id=post_id,
                file_path=str(file_path),
                original_path=str(file_path),
                sha256_hash=uuid.uuid4().hex,
                mime_type=mime_type,
                size_bytes=size_bytes,
                **kwargs,
            )
        except ImportError:
            asset = MagicMock()
            asset.id = uuid.uuid4()
            asset.post_id = post_id
            asset.file_path = str(file_path)
            asset.mime_type = mime_type
            asset.size_bytes = size_bytes

        test_session.add(asset)
        test_session.flush()
        return asset

    return _factory


# ── Mock adapter ──────────────────────────────────────────────────────────

class MockPlatformResult:
    """Lightweight stand-in for adapters.base.PlatformResult."""

    def __init__(self, success=True, platform_post_id=None, platform_post_url=None,
                 error=None, retryable=False):
        self.success = success
        self.platform_post_id = platform_post_id or (f"mock-{uuid.uuid4().hex[:8]}" if success else None)
        self.platform_post_url = platform_post_url or (
            f"https://mock.example.com/{self.platform_post_id}" if success else None
        )
        self.error = error
        self.retryable = retryable


class MockAdapter:
    """Mock adapter implementing the BaseAdapter interface."""

    def __init__(self, result=None):
        self._result = result or MockPlatformResult(success=True)
        self.publish_calls = []

    def set_result(self, result):
        self._result = result

    async def publish(self, post, credentials=None):
        self.publish_calls.append(post)
        return self._result

    def validate_credentials(self):
        return True


@pytest.fixture()
def mock_adapter():
    """Provides a MockAdapter that returns configurable PlatformResult."""
    return MockAdapter()


@pytest.fixture()
def mock_adapter_factory():
    """Factory for creating mock adapters with custom results."""

    def _factory(success=True, error=None, retryable=False, platform_post_id=None):
        result = MockPlatformResult(
            success=success,
            error=error,
            retryable=retryable,
            platform_post_id=platform_post_id,
        )
        return MockAdapter(result=result)

    return _factory


# ── Mock settings ─────────────────────────────────────────────────────────

@pytest.fixture()
def mock_settings():
    """Settings with test defaults — in-memory DB, fast retries."""
    settings = MagicMock()
    settings.database_path = ":memory:"
    settings.wal_mode = True
    settings.max_retries = 3
    settings.backoff_base = 1  # fast retries for tests
    settings.backoff_multiplier = 2
    settings.stuck_post_timeout = 300
    settings.max_concurrent_publishes = 3
    settings.twitter_posts_per_window = 300
    settings.twitter_window_seconds = 10800
    settings.reddit_posts_per_minute = 1
    settings.linkedin_posts_per_day = 100
    settings.api_host = "0.0.0.0"
    settings.api_port = 8000
    settings.log_level = "DEBUG"
    settings.dashboard_enabled = True
    settings.dashboard_refresh_interval = 5
    return settings
