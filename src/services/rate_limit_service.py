"""Rate limit service — persistent tracking, survives restarts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import REDDIT_POSTS_PER_MIN, TWITTER_TWEETS_PER_3H
from src.db.models import Platform, RateLimitLog
from src.exceptions import RateLimitExceededError

logger = structlog.get_logger()

# Platform rate limit configurations
PLATFORM_LIMITS: dict[str, dict[str, int]] = {
    Platform.twitter.value: {
        "calls_limit": TWITTER_TWEETS_PER_3H,
        "window_duration_sec": 3 * 3600,  # 3 hours
    },
    Platform.reddit.value: {
        "calls_limit": REDDIT_POSTS_PER_MIN,
        "window_duration_sec": 60,  # 1 minute
    },
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def check_rate_limit(session: AsyncSession, platform: str) -> bool:
    """Check if we can make another call. Returns True if allowed."""
    config = PLATFORM_LIMITS.get(platform)
    if not config:
        return True

    window_duration = config["window_duration_sec"]
    calls_limit = config["calls_limit"]

    now = _utcnow()
    window_start = now - timedelta(seconds=window_duration)

    result = await session.execute(
        select(RateLimitLog).where(
            RateLimitLog.platform == platform,
            RateLimitLog.window_start >= window_start,
        )
    )
    log = result.scalar_one_or_none()

    if not log:
        return True

    return log.calls_made < calls_limit


async def record_api_call(session: AsyncSession, platform: str) -> None:
    """Record an API call for rate limit tracking."""
    config = PLATFORM_LIMITS.get(platform)
    if not config:
        return

    window_duration = config["window_duration_sec"]
    calls_limit = config["calls_limit"]
    now = _utcnow()
    window_start = now - timedelta(seconds=window_duration)

    result = await session.execute(
        select(RateLimitLog).where(
            RateLimitLog.platform == platform,
            RateLimitLog.window_start >= window_start,
        )
    )
    log = result.scalar_one_or_none()

    if log:
        log.calls_made += 1
        log.updated_at = now
    else:
        log = RateLimitLog(
            platform=platform,
            window_start=now,
            window_duration_sec=window_duration,
            calls_made=1,
            calls_limit=calls_limit,
        )
        session.add(log)

    await session.flush()

    if log.calls_made >= calls_limit:
        logger.warning("rate_limit_reached", platform=platform, calls=log.calls_made)


async def enforce_rate_limit(session: AsyncSession, platform: str) -> None:
    """Check rate limit and raise if exceeded."""
    allowed = await check_rate_limit(session, platform)
    if not allowed:
        config = PLATFORM_LIMITS.get(platform, {})
        raise RateLimitExceededError(platform, retry_after=config.get("window_duration_sec"))


async def get_rate_limit_status(session: AsyncSession) -> list[dict]:
    """Get current rate limit status for all platforms."""
    statuses = []
    now = _utcnow()

    for platform, config in PLATFORM_LIMITS.items():
        window_duration = config["window_duration_sec"]
        window_start = now - timedelta(seconds=window_duration)

        result = await session.execute(
            select(RateLimitLog).where(
                RateLimitLog.platform == platform,
                RateLimitLog.window_start >= window_start,
            )
        )
        log = result.scalar_one_or_none()

        calls_made = log.calls_made if log else 0
        calls_limit = config["calls_limit"]

        statuses.append({
            "platform": platform,
            "calls_made": calls_made,
            "calls_limit": calls_limit,
            "remaining": max(0, calls_limit - calls_made),
            "window_duration_sec": window_duration,
            "headroom_pct": round((1 - calls_made / calls_limit) * 100, 1) if calls_limit > 0 else 100,
        })

    return statuses
