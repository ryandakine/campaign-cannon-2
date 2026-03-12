"""Campaign service — CRUD + state transitions for campaigns."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import (
    Campaign,
    CampaignStatus,
    Post,
    PostStatus,
)
from src.exceptions import (
    NotFoundError,
    SlugConflictError,
    StateTransitionError,
    ValidationError,
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,253}[a-z0-9]$")


def validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise ValidationError(
            f"Slug must be 3-255 chars, lowercase alphanumeric + hyphens, "
            f"cannot start or end with a hyphen. Got: '{slug}'"
        )


async def create_campaign(
    session: AsyncSession,
    *,
    slug: str,
    name: str,
    description: str | None = None,
    timezone_str: str = "UTC",
    catch_up: bool = False,
    profile_id: str | None = None,
) -> Campaign:
    validate_slug(slug)

    existing = await session.execute(select(Campaign).where(Campaign.slug == slug))
    if existing.scalar_one_or_none():
        raise SlugConflictError(slug)

    campaign = Campaign(
        slug=slug,
        name=name,
        description=description,
        timezone=timezone_str,
        catch_up=catch_up,
        profile_id=profile_id,
    )
    session.add(campaign)
    await session.flush()
    return campaign


async def get_campaign(session: AsyncSession, slug: str) -> Campaign:
    result = await session.execute(
        select(Campaign)
        .where(Campaign.slug == slug)
        .options(selectinload(Campaign.posts), selectinload(Campaign.assets))
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise NotFoundError("Campaign", slug)
    return campaign


async def list_campaigns(
    session: AsyncSession,
    *,
    status: CampaignStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Campaign]:
    stmt = select(Campaign).order_by(Campaign.created_at.desc()).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(Campaign.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_campaign(
    session: AsyncSession,
    slug: str,
    *,
    name: str | None = None,
    description: str | None = None,
    timezone_str: str | None = None,
    catch_up: bool | None = None,
) -> Campaign:
    campaign = await get_campaign(session, slug)
    if campaign.status != CampaignStatus.draft:
        raise ValidationError("Only draft campaigns can be updated")

    if name is not None:
        campaign.name = name
    if description is not None:
        campaign.description = description
    if timezone_str is not None:
        campaign.timezone = timezone_str
    if catch_up is not None:
        campaign.catch_up = catch_up

    campaign.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return campaign


async def _transition_campaign(
    session: AsyncSession, slug: str, target: CampaignStatus
) -> Campaign:
    campaign = await get_campaign(session, slug)
    if not campaign.can_transition_to(target):
        raise StateTransitionError(campaign.status.value, target.value)

    campaign.status = target
    campaign.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return campaign


async def activate_campaign(session: AsyncSession, slug: str) -> Campaign:
    campaign = await _transition_campaign(session, slug, CampaignStatus.active)
    # Move all draft posts to pending
    result = await session.execute(
        select(Post).where(Post.campaign_id == campaign.id, Post.status == PostStatus.draft)
    )
    for post in result.scalars().all():
        post.status = PostStatus.pending
        post.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return campaign


async def pause_campaign(session: AsyncSession, slug: str) -> Campaign:
    return await _transition_campaign(session, slug, CampaignStatus.paused)


async def resume_campaign(session: AsyncSession, slug: str) -> Campaign:
    return await _transition_campaign(session, slug, CampaignStatus.active)


async def cancel_campaign(session: AsyncSession, slug: str) -> Campaign:
    campaign = await _transition_campaign(session, slug, CampaignStatus.cancelled)
    # Cancel all non-terminal posts
    terminal = {PostStatus.posted, PostStatus.failed, PostStatus.cancelled, PostStatus.missed}
    result = await session.execute(
        select(Post).where(Post.campaign_id == campaign.id, Post.status.notin_(terminal))
    )
    for post in result.scalars().all():
        post.status = PostStatus.cancelled
        post.lock_token = None
        post.locked_at = None
        post.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return campaign


async def get_campaign_status(session: AsyncSession, slug: str) -> dict:
    """Return campaign info with post-status counts and next due post."""
    campaign = await get_campaign(session, slug)

    post_counts: dict[str, int] = {}
    for post in campaign.posts:
        key = post.status.value
        post_counts[key] = post_counts.get(key, 0) + 1

    next_due = None
    pending_posts = [
        p for p in campaign.posts
        if p.status in (PostStatus.pending, PostStatus.retry_scheduled)
    ]
    if pending_posts:
        pending_posts.sort(key=lambda p: p.scheduled_at)
        nd = pending_posts[0]
        next_due = {
            "id": nd.id,
            "platform": nd.platform.value,
            "scheduled_at": nd.scheduled_at.isoformat(),
            "copy": nd.copy[:80],
        }

    return {
        "campaign": {
            "id": campaign.id,
            "slug": campaign.slug,
            "name": campaign.name,
            "status": campaign.status.value,
            "timezone": campaign.timezone,
            "catch_up": campaign.catch_up,
            "created_at": campaign.created_at.isoformat(),
        },
        "post_counts": post_counts,
        "total_posts": len(campaign.posts),
        "next_due": next_due,
    }
