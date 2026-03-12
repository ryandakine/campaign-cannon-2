"""Dashboard service — queries for dashboard widgets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    Campaign,
    CampaignStatus,
    DeliveryAttempt,
    DeliveryOutcome,
    Post,
    PostStatus,
)
from src.services import rate_limit_service


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_summary(session: AsyncSession) -> dict:
    """Campaign status breakdown."""
    counts: dict[str, int] = {}
    for status in CampaignStatus:
        result = await session.execute(
            select(func.count()).select_from(Campaign).where(Campaign.status == status)
        )
        counts[status.value] = result.scalar() or 0

    total = sum(counts.values())
    return {"total": total, "by_status": counts}


async def get_next_due(session: AsyncSession, limit: int = 10) -> list[dict]:
    """Next due posts across all active campaigns."""
    now = _utcnow()
    result = await session.execute(
        select(Post)
        .join(Campaign)
        .where(
            Campaign.status == CampaignStatus.active,
            Post.status.in_([PostStatus.pending, PostStatus.retry_scheduled]),
            Post.scheduled_at >= now,
        )
        .order_by(Post.scheduled_at.asc())
        .limit(limit)
    )
    posts = result.scalars().all()
    return [
        {
            "id": p.id,
            "campaign_id": p.campaign_id,
            "platform": p.platform.value,
            "copy": p.copy[:80],
            "scheduled_at": p.scheduled_at.isoformat(),
            "status": p.status.value,
        }
        for p in posts
    ]


async def get_recent_failures(session: AsyncSession, limit: int = 10) -> list[dict]:
    """Recent delivery failures."""
    result = await session.execute(
        select(DeliveryAttempt)
        .where(
            DeliveryAttempt.outcome.in_([
                DeliveryOutcome.retryable_failure,
                DeliveryOutcome.permanent_failure,
            ])
        )
        .order_by(DeliveryAttempt.finished_at.desc())
        .limit(limit)
    )
    attempts = result.scalars().all()
    return [
        {
            "id": a.id,
            "post_id": a.post_id,
            "attempt_number": a.attempt_number,
            "outcome": a.outcome.value if a.outcome else None,
            "error_code": a.error_code,
            "error_message": a.error_message,
            "finished_at": a.finished_at.isoformat() if a.finished_at else None,
        }
        for a in attempts
    ]


async def get_retry_queue(session: AsyncSession, limit: int = 20) -> list[dict]:
    """Posts currently in retry_scheduled status."""
    result = await session.execute(
        select(Post)
        .where(Post.status == PostStatus.retry_scheduled)
        .order_by(Post.scheduled_at.asc())
        .limit(limit)
    )
    posts = result.scalars().all()
    return [
        {
            "id": p.id,
            "campaign_id": p.campaign_id,
            "platform": p.platform.value,
            "copy": p.copy[:60],
            "retry_count": p.retry_count,
            "max_retries": p.max_retries,
            "scheduled_at": p.scheduled_at.isoformat(),
            "error": p.error,
        }
        for p in posts
    ]


async def get_rate_limits(session: AsyncSession) -> list[dict]:
    """Current rate limit status for all platforms."""
    return await rate_limit_service.get_rate_limit_status(session)


async def get_missed_posts(session: AsyncSession, limit: int = 10) -> list[dict]:
    """Posts marked as missed."""
    result = await session.execute(
        select(Post)
        .where(Post.status == PostStatus.missed)
        .order_by(Post.scheduled_at.desc())
        .limit(limit)
    )
    posts = result.scalars().all()
    return [
        {
            "id": p.id,
            "campaign_id": p.campaign_id,
            "platform": p.platform.value,
            "copy": p.copy[:60],
            "scheduled_at": p.scheduled_at.isoformat(),
        }
        for p in posts
    ]
