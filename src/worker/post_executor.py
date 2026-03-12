"""Post executor — picks up due posts, acquires lock, calls adapter, records result.

This is the core execution loop. Every delivery attempt is persisted
in the same transaction as the post status change.
"""

from __future__ import annotations

import json
import platform
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.base import BaseAdapter, PostResult
from src.adapters.reddit_adapter import RedditAdapter
from src.adapters.twitter_adapter import TwitterAdapter
from src.config import LOCAL_STORAGE_PATH
from src.db.models import Campaign, CampaignStatus, MediaAsset, Platform, Post, PostStatus
from src.services import execution_service, rate_limit_service

logger = structlog.get_logger()

WORKER_ID = f"{platform.node()}-{uuid.uuid4().hex[:8]}"


def _get_adapter(plat: Platform) -> BaseAdapter:
    adapters: dict[Platform, BaseAdapter] = {
        Platform.twitter: TwitterAdapter(),
        Platform.reddit: RedditAdapter(),
    }
    return adapters[plat]


async def execute_pending_posts(session: AsyncSession) -> int:
    """Find and execute all due pending posts. Returns count executed."""
    now = datetime.now(timezone.utc)

    # Find due posts from active campaigns
    result = await session.execute(
        select(Post)
        .join(Campaign)
        .where(
            Campaign.status == CampaignStatus.active,
            Post.status.in_([PostStatus.pending, PostStatus.retry_scheduled]),
            Post.scheduled_at <= now,
            Post.lock_token.is_(None),
        )
        .order_by(Post.scheduled_at.asc())
        .limit(10)
    )
    due_posts = result.scalars().all()

    executed = 0
    for post in due_posts:
        try:
            await execute_single_post(session, post)
            executed += 1
        except Exception as e:
            logger.error("post_execution_error", post_id=post.id, error=str(e))

    return executed


async def execute_single_post(session: AsyncSession, post: Post) -> None:
    """Execute a single post: lock → check rate limit → post → record result."""
    # Acquire lock
    try:
        lock_token = await execution_service.acquire_lock(session, post.id, WORKER_ID)
    except Exception as e:
        logger.warning("lock_failed", post_id=post.id, error=str(e))
        return

    # Check rate limit
    try:
        await rate_limit_service.enforce_rate_limit(session, post.platform.value)
    except Exception as e:
        logger.warning("rate_limit_block", post_id=post.id, error=str(e))
        await execution_service.release_lock(session, post.id, lock_token)
        return

    # Transition to posting
    post.status = PostStatus.posting
    post.updated_at = datetime.now(timezone.utc)
    await session.flush()

    # Get adapter and media path
    adapter = _get_adapter(post.platform)
    media_path: Path | None = None
    if post.asset_id:
        asset = await session.get(MediaAsset, post.asset_id)
        if asset:
            media_path = LOCAL_STORAGE_PATH / asset.storage_key

    # Generate idempotency key
    attempt_number = post.retry_count + 1
    idempotency_key = f"{post.dedup_key}:attempt:{attempt_number}"

    # Parse hashtags
    hashtags: list[str] | None = None
    if post.hashtags:
        try:
            hashtags = json.loads(post.hashtags)
        except (json.JSONDecodeError, TypeError):
            hashtags = [h.strip() for h in post.hashtags.split(",") if h.strip()]

    # Execute
    try:
        result: PostResult = await adapter.post(
            post.copy,
            media_path=media_path,
            subreddit=post.subreddit,
            hashtags=hashtags,
            target_account=post.target_account,
            idempotency_key=idempotency_key,
        )
    except Exception as e:
        logger.error("adapter_unexpected_error", post_id=post.id, error=str(e))
        await execution_service.release_lock(session, post.id, lock_token)
        raise

    # Record result — in the same transaction
    if result.success:
        await execution_service.record_success(
            session,
            post,
            platform_post_id=result.platform_post_id or "",
            attempt_number=attempt_number,
            idempotency_key=idempotency_key,
            request_fingerprint=result.request_fingerprint,
        )
        # Record API call for rate limiting
        await rate_limit_service.record_api_call(session, post.platform.value)
    else:
        await execution_service.record_failure(
            session,
            post,
            attempt_number=attempt_number,
            idempotency_key=idempotency_key,
            error_code=result.error_code or "UNKNOWN",
            error_message=result.error_message or "Unknown error",
            provider_status_code=result.provider_status_code,
            is_retryable=result.is_retryable,
            request_fingerprint=result.request_fingerprint,
        )

    logger.info(
        "post_executed",
        post_id=post.id,
        success=result.success,
        platform=post.platform.value,
    )
