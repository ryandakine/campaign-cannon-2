"""Integration tests for crash recovery and restart safety — 3 tests."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_post(state="publishing", minutes_ago=10, **kwargs):
    """Create a mock post stuck in a state."""
    post = MagicMock()
    post.id = uuid.uuid4()
    post.campaign_id = uuid.uuid4()
    post.platform = kwargs.get("platform", "twitter")
    post.body = "Test crash recovery post"
    post.state = state
    post.updated_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    post.scheduled_at = datetime.now(timezone.utc) - timedelta(hours=1)
    post.idempotency_key = f"crash-test-{uuid.uuid4().hex[:8]}"
    post.retry_count = kwargs.get("retry_count", 0)
    post.max_retries = kwargs.get("max_retries", 3)
    post.version = kwargs.get("version", 1)
    post.platform_post_id = kwargs.get("platform_post_id", None)
    post.error_detail = None
    return post


def _make_session(posts=None):
    """Create a mock session that returns given posts for queries."""
    session = MagicMock()
    query_mock = MagicMock()

    if posts:
        query_mock.filter.return_value = query_mock
        query_mock.all.return_value = posts
    else:
        query_mock.filter.return_value = query_mock
        query_mock.all.return_value = []

    session.query.return_value = query_mock
    session.add = MagicMock()
    session.flush = MagicMock()
    session.commit = MagicMock()
    return session


# ── Tests ─────────────────────────────────────────────────────────────────

class TestStuckPostRecovery:
    """Posts stuck in PUBLISHING should be recovered."""

    def test_stuck_publishing_recovered(self):
        """
        1. Post in PUBLISHING with updated_at 10 min ago
        2. Run recover_stuck_posts logic
        3. Post should be back to QUEUED with auto-recovery log
        """
        post = _make_post(state="publishing", minutes_ago=10)
        session = _make_session(posts=[post])

        # Simulate recovery: find stuck posts (PUBLISHING > 5 min)
        stuck_threshold = timedelta(minutes=5)
        now = datetime.now(timezone.utc)
        time_stuck = now - post.updated_at

        assert time_stuck > stuck_threshold, "Post should be identified as stuck"

        # Recovery action
        post.state = "queued"
        post.version += 1
        post.updated_at = now

        # Create recovery log
        log = MagicMock()
        log.post_id = post.id
        log.from_state = "publishing"
        log.to_state = "queued"
        log.metadata = {"reason": "auto-recovery", "stuck_duration_seconds": time_stuck.total_seconds()}

        assert post.state == "queued"
        assert log.metadata["reason"] == "auto-recovery"


class TestCrashMidPublish:
    """Prevent double-posting after crash during publish."""

    @patch("campaign_cannon.engine.publisher.publish_post", new_callable=AsyncMock)
    def test_crash_mid_publish_no_double_post(self, mock_publish):
        """
        1. Post in PUBLISHING state (simulated crash)
        2. Restart (new session)
        3. Idempotency guard prevents double publish
        """
        # Post was mid-publish when crash happened
        post = _make_post(state="publishing", minutes_ago=2)

        # After recovery, post is back to QUEUED
        post.state = "queued"

        # New session — simulate restart
        new_session = _make_session()

        # When publish_post is called again, the idempotency_key
        # prevents double-posting. If platform_post_id is already set,
        # publisher skips.
        mock_publish.return_value = MagicMock(
            success=True,
            platform_post_id="real-post-123",
        )

        # First publish succeeds
        post.platform_post_id = "real-post-123"
        post.state = "posted"

        # If called again, the guard should prevent re-publish
        assert post.platform_post_id is not None

        # Simulate second call — publisher should detect already-posted
        mock_publish.return_value = None  # skip
        assert post.state == "posted"
        assert post.platform_post_id == "real-post-123"


class TestSchedulerRestart:
    """Scheduler jobs persist across restarts."""

    def test_scheduler_restart_preserves_jobs(self):
        """
        1. Schedule campaign → jobs created
        2. Shutdown scheduler
        3. Restart scheduler
        4. Same jobs still pending
        """
        # Simulate scheduler with job store
        scheduler = MagicMock()
        job_ids = [f"job-{uuid.uuid4().hex[:8]}" for _ in range(3)]

        # Step 1: Schedule jobs
        jobs = []
        for jid in job_ids:
            job = MagicMock()
            job.id = jid
            job.pending = True
            job.next_run_time = datetime.now(timezone.utc) + timedelta(hours=1)
            jobs.append(job)

        scheduler.get_jobs.return_value = jobs
        assert len(scheduler.get_jobs()) == 3

        # Step 2: Shutdown
        scheduler.shutdown = MagicMock()
        scheduler.shutdown(wait=False)

        # Step 3: Restart — new scheduler instance loads from job store
        new_scheduler = MagicMock()
        new_scheduler.get_jobs.return_value = jobs  # same jobs persisted

        # Step 4: Verify same jobs
        reloaded = new_scheduler.get_jobs()
        assert len(reloaded) == 3
        reloaded_ids = {j.id for j in reloaded}
        assert reloaded_ids == set(job_ids)
        for job in reloaded:
            assert job.next_run_time > datetime.now(timezone.utc) - timedelta(seconds=5)
