"""Tests for execution service — locking, delivery attempts, retries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.db.models import PostStatus
from src.exceptions import LockError
from src.services.execution_service import (
    acquire_lock,
    cleanup_stale_locks,
    record_failure,
    record_success,
    release_lock,
)


class TestAcquireLock:
    async def test_lock_pending_post(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.pending)
        token = await acquire_lock(session, post.id, "worker-1")
        await session.refresh(post)
        assert post.status == PostStatus.locked
        assert post.lock_token == token
        assert post.worker_id == "worker-1"

    async def test_lock_already_locked_raises(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.pending)
        await acquire_lock(session, post.id, "worker-1")
        with pytest.raises(LockError):
            await acquire_lock(session, post.id, "worker-2")

    async def test_expired_lock_can_be_reacquired(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.pending)
        await acquire_lock(session, post.id, "worker-1")
        # Manually expire the lock
        post.locked_at = datetime.now(timezone.utc) - timedelta(seconds=9999)
        await session.flush()
        token = await acquire_lock(session, post.id, "worker-2")
        assert token is not None
        await session.refresh(post)
        assert post.worker_id == "worker-2"


class TestReleaseLock:
    async def test_release_restores_pending(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.pending)
        token = await acquire_lock(session, post.id, "worker-1")
        await release_lock(session, post.id, token)
        await session.refresh(post)
        assert post.status == PostStatus.pending
        assert post.lock_token is None
        assert post.worker_id is None

    async def test_release_wrong_token_is_noop(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.pending)
        token = await acquire_lock(session, post.id, "worker-1")
        await release_lock(session, post.id, "wrong-token")
        await session.refresh(post)
        assert post.lock_token == token  # still locked


class TestCleanupStaleLocks:
    async def test_cleanup_expired_locks(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.locked)
        post.lock_token = "stale-token"
        post.locked_at = datetime.now(timezone.utc) - timedelta(seconds=9999)
        post.worker_id = "dead-worker"
        await session.flush()

        cleaned = await cleanup_stale_locks(session)
        assert cleaned == 1
        await session.refresh(post)
        assert post.status == PostStatus.pending
        assert post.lock_token is None

    async def test_fresh_locks_untouched(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.pending)
        await acquire_lock(session, post.id, "worker-1")
        cleaned = await cleanup_stale_locks(session)
        assert cleaned == 0


class TestRecordSuccess:
    async def test_success_creates_attempt_and_updates_post(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.posting)
        post.lock_token = "tok"
        post.locked_at = datetime.now(timezone.utc)
        await session.flush()

        attempt = await record_success(
            session,
            post,
            platform_post_id="ext-123",
            attempt_number=1,
            idempotency_key="idem-1",
        )
        assert attempt.outcome.value == "success"
        assert post.status == PostStatus.posted
        assert post.platform_post_id == "ext-123"
        assert post.lock_token is None


class TestRecordFailure:
    async def test_retryable_failure_schedules_retry(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.posting)
        post.lock_token = "tok"
        post.locked_at = datetime.now(timezone.utc)
        post.retry_count = 0
        post.max_retries = 3
        await session.flush()

        attempt = await record_failure(
            session,
            post,
            attempt_number=1,
            idempotency_key="idem-2",
            error_code="RATE_LIMIT",
            error_message="Too many requests",
            is_retryable=True,
        )
        assert attempt.outcome.value == "retryable_failure"
        assert post.status == PostStatus.retry_scheduled
        assert post.retry_count == 1

    async def test_permanent_failure_marks_failed(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.posting)
        post.lock_token = "tok"
        post.locked_at = datetime.now(timezone.utc)
        await session.flush()

        attempt = await record_failure(
            session,
            post,
            attempt_number=1,
            idempotency_key="idem-3",
            error_code="AUTH_FAILURE",
            error_message="Invalid credentials",
            is_retryable=False,
        )
        assert attempt.outcome.value == "permanent_failure"
        assert post.status == PostStatus.failed

    async def test_max_retries_exhausted_marks_failed(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.posting)
        post.lock_token = "tok"
        post.locked_at = datetime.now(timezone.utc)
        post.retry_count = 3
        post.max_retries = 3
        await session.flush()

        await record_failure(
            session,
            post,
            attempt_number=4,
            idempotency_key="idem-4",
            error_code="NETWORK",
            error_message="Timeout",
            is_retryable=True,
        )
        assert post.status == PostStatus.failed

    async def test_backoff_increases_scheduled_at(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.posting)
        post.lock_token = "tok"
        post.locked_at = datetime.now(timezone.utc)
        post.retry_count = 1
        post.max_retries = 5
        original_scheduled = post.scheduled_at
        await session.flush()

        await record_failure(
            session,
            post,
            attempt_number=2,
            idempotency_key="idem-5",
            error_code="RATE_LIMIT",
            error_message="Slow down",
            is_retryable=True,
        )
        assert post.scheduled_at > original_scheduled
