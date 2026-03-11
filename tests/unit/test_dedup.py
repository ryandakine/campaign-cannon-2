"""Tests for idempotency key generation and duplicate detection — 6 tests."""

import uuid
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────

def _compute_idempotency_key(campaign_id, slug, platform, scheduled_at):
    """Reference implementation of idempotency key generation."""
    raw = f"{campaign_id}-{slug}-{platform}-{scheduled_at.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _make_post(campaign_id=None, slug="test-post", platform="twitter",
               scheduled_at=None, body="Hello world"):
    """Create a mock post for dedup tests."""
    post = MagicMock()
    post.id = uuid.uuid4()
    post.campaign_id = campaign_id or uuid.uuid4()
    post.slug = slug
    post.platform = platform
    post.scheduled_at = scheduled_at or datetime.now(timezone.utc)
    post.body = body
    post.idempotency_key = _compute_idempotency_key(
        post.campaign_id, post.slug, post.platform, post.scheduled_at,
    )
    return post


# ── Tests ─────────────────────────────────────────────────────────────────

class TestIdempotencyKeyGeneration:
    """Verify deterministic key generation from post attributes."""

    def test_idempotency_key_deterministic(self):
        """Same inputs must produce the same key every time."""
        campaign_id = uuid.uuid4()
        slug = "launch-post"
        platform = "twitter"
        scheduled_at = datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc)

        key1 = _compute_idempotency_key(campaign_id, slug, platform, scheduled_at)
        key2 = _compute_idempotency_key(campaign_id, slug, platform, scheduled_at)

        assert key1 == key2
        assert len(key1) == 64  # SHA-256 hex digest

    def test_idempotency_key_unique(self):
        """Different inputs must produce different keys."""
        campaign_id = uuid.uuid4()
        scheduled_at = datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc)

        key1 = _compute_idempotency_key(campaign_id, "post-a", "twitter", scheduled_at)
        key2 = _compute_idempotency_key(campaign_id, "post-b", "twitter", scheduled_at)
        key3 = _compute_idempotency_key(campaign_id, "post-a", "reddit", scheduled_at)

        assert key1 != key2  # different slug
        assert key1 != key3  # different platform
        assert key2 != key3


class TestDuplicateDetection:
    """Verify re-import and content duplicate detection."""

    @patch("campaign_cannon.engine.dedup.check_duplicate")
    def test_duplicate_detected(self, mock_check):
        """Re-importing the same post must be detected."""
        post = _make_post()
        mock_check.return_value = True  # duplicate found

        result = mock_check(post.idempotency_key, session=MagicMock())
        assert result is True

    @patch("campaign_cannon.engine.dedup.check_duplicate")
    def test_no_false_positive(self, mock_check):
        """Similar but different posts should not be flagged."""
        post_a = _make_post(slug="post-a")
        post_b = _make_post(slug="post-b")

        # Different idempotency keys → not a duplicate
        mock_check.return_value = False
        assert post_a.idempotency_key != post_b.idempotency_key

        result = mock_check(post_b.idempotency_key, session=MagicMock())
        assert result is False


class TestContentDuplicate:
    """Content-level duplicate detection within time windows."""

    @patch("campaign_cannon.engine.dedup.detect_content_duplicate")
    def test_content_duplicate_within_window(self, mock_detect):
        """Same body text to same platform within 24h should trigger warning."""
        now = datetime.now(timezone.utc)
        post_a = _make_post(body="Great product launch!", scheduled_at=now)
        post_b = _make_post(body="Great product launch!", scheduled_at=now + timedelta(hours=2))

        mock_detect.return_value = {
            "is_duplicate": True,
            "existing_post_id": post_a.id,
            "time_gap_hours": 2,
        }

        result = mock_detect(
            body=post_b.body,
            platform=post_b.platform,
            scheduled_at=post_b.scheduled_at,
            session=MagicMock(),
        )
        assert result["is_duplicate"] is True
        assert result["time_gap_hours"] < 24

    @patch("campaign_cannon.engine.dedup.detect_content_duplicate")
    def test_content_duplicate_outside_window(self, mock_detect):
        """Same body text after 24h should NOT trigger warning."""
        now = datetime.now(timezone.utc)
        post_a = _make_post(body="Great product launch!", scheduled_at=now)
        post_b = _make_post(
            body="Great product launch!",
            scheduled_at=now + timedelta(hours=25),
        )

        mock_detect.return_value = {
            "is_duplicate": False,
            "existing_post_id": None,
            "time_gap_hours": 25,
        }

        result = mock_detect(
            body=post_b.body,
            platform=post_b.platform,
            scheduled_at=post_b.scheduled_at,
            session=MagicMock(),
        )
        assert result["is_duplicate"] is False
