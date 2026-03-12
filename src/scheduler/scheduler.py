"""Scheduler — APScheduler-based periodic job runner.

Jobs:
  1. Post executor — picks up due posts, locks, and executes
  2. Stale lock cleanup — reclaims expired locks
  3. Missed post detector — marks overdue posts as missed
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import (
    CATCH_UP_MAX_LATENESS_MIN,
    CHECK_INTERVAL_SEC,
    LOCK_TTL_SEC,
    MISSED_POST_WINDOW_MIN,
    SCHEDULER_ENABLED,
)

logger = structlog.get_logger()

scheduler = AsyncIOScheduler()


async def execute_due_posts() -> None:
    """Find and execute all posts that are due now."""
    from src.db.unit_of_work import unit_of_work
    from src.worker.post_executor import execute_pending_posts

    try:
        async with unit_of_work() as session:
            count = await execute_pending_posts(session)
            if count > 0:
                logger.info("executed_posts", count=count)
    except Exception as e:
        logger.error("execute_due_posts_error", error=str(e))


async def cleanup_stale_locks() -> None:
    """Clean up stale locks from crashed workers."""
    from src.db.unit_of_work import unit_of_work
    from src.services.execution_service import cleanup_stale_locks as _cleanup

    try:
        async with unit_of_work() as session:
            cleaned = await _cleanup(session)
            if cleaned > 0:
                logger.info("stale_locks_cleaned", count=cleaned)
    except Exception as e:
        logger.error("cleanup_stale_locks_error", error=str(e))


async def detect_missed_posts() -> None:
    """Mark overdue posts as missed (if catch_up=false) or re-queue them."""
    from sqlalchemy import select
    from src.db.unit_of_work import unit_of_work
    from src.db.models import Campaign, CampaignStatus, Post, PostStatus

    try:
        async with unit_of_work() as session:
            now = datetime.now(timezone.utc)
            missed_window = now - timedelta(minutes=MISSED_POST_WINDOW_MIN)
            catchup_window = now - timedelta(minutes=CATCH_UP_MAX_LATENESS_MIN)

            # Find overdue pending posts
            result = await session.execute(
                select(Post)
                .join(Campaign)
                .where(
                    Campaign.status == CampaignStatus.active,
                    Post.status == PostStatus.pending,
                    Post.scheduled_at < missed_window,
                )
            )
            overdue_posts = result.scalars().all()

            for post in overdue_posts:
                campaign = await session.get(Campaign, post.campaign_id)
                if not campaign:
                    continue

                if campaign.catch_up and post.scheduled_at > catchup_window:
                    # Re-queue for immediate execution
                    post.scheduled_at = now
                    post.updated_at = now
                    logger.info("post_catch_up", post_id=post.id)
                else:
                    post.status = PostStatus.missed
                    post.updated_at = now
                    logger.warning("post_missed", post_id=post.id)

            await session.flush()

    except Exception as e:
        logger.error("detect_missed_posts_error", error=str(e))


def start_scheduler() -> None:
    """Start the APScheduler with all periodic jobs."""
    if not SCHEDULER_ENABLED:
        logger.info("scheduler_disabled")
        return

    scheduler.add_job(
        execute_due_posts,
        "interval",
        seconds=CHECK_INTERVAL_SEC,
        id="execute_due_posts",
        replace_existing=True,
    )

    scheduler.add_job(
        cleanup_stale_locks,
        "interval",
        seconds=LOCK_TTL_SEC,
        id="cleanup_stale_locks",
        replace_existing=True,
    )

    scheduler.add_job(
        detect_missed_posts,
        "interval",
        seconds=300,  # Every 5 minutes
        id="detect_missed_posts",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "scheduler_started",
        check_interval=CHECK_INTERVAL_SEC,
        lock_ttl=LOCK_TTL_SEC,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")
