"""Execution service — locking, delivery attempts, retry logic.

This is the heart of the execution engine. All delivery attempts are
persisted in the same transaction as the post status update.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import BACKOFF_BASE_SEC, LOCK_TTL_SEC, MAX_RETRIES
from src.db.models import (
    DeliveryAttempt,
    DeliveryOutcome,
    Post,
    PostStatus,
)
from src.exceptions import LockError

logger = structlog.get_logger()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def acquire_lock(
    session: AsyncSession,
    post_id: str,
    worker_id: str,
) -> str:
    """Try to lock a post for execution. Returns lock_token on success."""
    post = await session.get(Post, post_id)
    if not post:
        raise LockError(f"Post {post_id} not found")

    now = _utcnow()

    # Already locked by someone and lock not expired
    if post.lock_token and post.locked_at:
        lock_age = (now - post.locked_at).total_seconds()
        if lock_age < LOCK_TTL_SEC:
            raise LockError(f"Post {post_id} already locked by {post.worker_id}")

    # Acquire lock
    token = str(uuid.uuid4())
    post.lock_token = token
    post.locked_at = now
    post.worker_id = worker_id
    post.status = PostStatus.locked
    post.updated_at = now
    await session.flush()

    logger.info("lock_acquired", post_id=post_id, worker_id=worker_id, token=token)
    return token


async def release_lock(session: AsyncSession, post_id: str, lock_token: str) -> None:
    """Release a lock on a post."""
    post = await session.get(Post, post_id)
    if not post:
        return
    if post.lock_token != lock_token:
        logger.warning("lock_mismatch", post_id=post_id, expected=lock_token, actual=post.lock_token)
        return

    post.lock_token = None
    post.locked_at = None
    post.worker_id = None
    if post.status == PostStatus.locked:
        post.status = PostStatus.pending
    post.updated_at = _utcnow()
    await session.flush()


async def cleanup_stale_locks(session: AsyncSession) -> int:
    """Reclaim locks older than LOCK_TTL_SEC. Returns count of cleaned locks."""
    cutoff = _utcnow() - timedelta(seconds=LOCK_TTL_SEC)
    result = await session.execute(
        select(Post).where(
            and_(
                Post.lock_token.isnot(None),
                Post.locked_at < cutoff,
            )
        )
    )
    cleaned = 0
    for post in result.scalars().all():
        logger.warning("stale_lock_cleanup", post_id=post.id, worker_id=post.worker_id)
        post.lock_token = None
        post.locked_at = None
        post.worker_id = None
        if post.status == PostStatus.locked:
            post.status = PostStatus.pending
        post.updated_at = _utcnow()
        cleaned += 1
    await session.flush()
    return cleaned


async def record_success(
    session: AsyncSession,
    post: Post,
    *,
    platform_post_id: str,
    attempt_number: int,
    idempotency_key: str,
    request_fingerprint: str | None = None,
) -> DeliveryAttempt:
    """Record a successful delivery and update post status atomically."""
    now = _utcnow()

    attempt = DeliveryAttempt(
        post_id=post.id,
        attempt_number=attempt_number,
        started_at=post.locked_at or now,
        finished_at=now,
        outcome=DeliveryOutcome.success,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
    )
    session.add(attempt)

    post.status = PostStatus.posted
    post.posted_at = now
    post.platform_post_id = platform_post_id
    post.lock_token = None
    post.locked_at = None
    post.error = None
    post.updated_at = now
    await session.flush()

    logger.info("delivery_success", post_id=post.id, platform_post_id=platform_post_id)
    return attempt


async def record_failure(
    session: AsyncSession,
    post: Post,
    *,
    attempt_number: int,
    idempotency_key: str,
    error_code: str,
    error_message: str,
    provider_status_code: int | None = None,
    is_retryable: bool = True,
    request_fingerprint: str | None = None,
) -> DeliveryAttempt:
    """Record a failed delivery attempt and schedule retry or mark as failed."""
    now = _utcnow()

    attempt = DeliveryAttempt(
        post_id=post.id,
        attempt_number=attempt_number,
        started_at=post.locked_at or now,
        finished_at=now,
        outcome=DeliveryOutcome.retryable_failure if is_retryable else DeliveryOutcome.permanent_failure,
        error_code=error_code,
        error_message=error_message,
        provider_status_code=provider_status_code,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
    )
    session.add(attempt)

    post.error = f"{error_code}: {error_message}"
    post.lock_token = None
    post.locked_at = None
    post.updated_at = now

    max_retries = post.max_retries or MAX_RETRIES

    if is_retryable and post.retry_count < max_retries:
        post.retry_count += 1
        backoff = BACKOFF_BASE_SEC * (2 ** (post.retry_count - 1))
        post.scheduled_at = now + timedelta(seconds=backoff)
        post.status = PostStatus.retry_scheduled
        logger.info(
            "delivery_retry_scheduled",
            post_id=post.id,
            retry_count=post.retry_count,
            next_attempt=post.scheduled_at.isoformat(),
        )
    else:
        post.status = PostStatus.failed
        logger.error(
            "delivery_failed_permanently",
            post_id=post.id,
            retry_count=post.retry_count,
            error_code=error_code,
        )

    await session.flush()
    return attempt


def calculate_backoff(retry_count: int) -> int:
    """Exponential backoff: base * 2^(retry-1)."""
    return BACKOFF_BASE_SEC * (2 ** max(0, retry_count - 1))
