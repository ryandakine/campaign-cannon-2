"""Post service — CRUD for posts within a campaign."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Campaign, Platform, Post, PostStatus
from src.exceptions import NotFoundError, ValidationError


def generate_dedup_key(campaign_id: str, platform: str, scheduled_at: datetime, copy: str) -> str:
    """Deterministic dedup key based on campaign + platform + time + content hash."""
    content_hash = hashlib.sha256(copy.encode()).hexdigest()[:12]
    ts = scheduled_at.strftime("%Y%m%d%H%M%S")
    return f"{campaign_id}:{platform}:{ts}:{content_hash}"


async def create_post(
    session: AsyncSession,
    *,
    campaign_id: str,
    platform: Platform,
    copy: str,
    scheduled_at: datetime,
    asset_id: str | None = None,
    target_account: str | None = None,
    subreddit: str | None = None,
    hashtags: str | None = None,
    dedup_key: str | None = None,
) -> Post:
    if platform == Platform.reddit and not subreddit:
        raise ValidationError("Reddit posts require a subreddit")

    if not dedup_key:
        dedup_key = generate_dedup_key(campaign_id, platform.value, scheduled_at, copy)

    # Check for dedup collision
    existing = await session.execute(select(Post).where(Post.dedup_key == dedup_key))
    if existing.scalar_one_or_none():
        # Generate unique dedup key by appending UUID suffix
        dedup_key = f"{dedup_key}:{uuid.uuid4().hex[:8]}"

    post = Post(
        campaign_id=campaign_id,
        platform=platform,
        copy=copy,
        scheduled_at=scheduled_at,
        asset_id=asset_id,
        target_account=target_account,
        subreddit=subreddit,
        hashtags=hashtags,
        dedup_key=dedup_key,
    )
    session.add(post)
    await session.flush()
    return post


async def get_post(session: AsyncSession, post_id: str) -> Post:
    result = await session.execute(select(Post).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise NotFoundError("Post", post_id)
    return post


async def list_posts(
    session: AsyncSession,
    campaign_id: str,
    *,
    status: PostStatus | None = None,
    platform: Platform | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Post]:
    stmt = (
        select(Post)
        .where(Post.campaign_id == campaign_id)
        .order_by(Post.scheduled_at.asc())
        .limit(limit)
        .offset(offset)
    )
    if status:
        stmt = stmt.where(Post.status == status)
    if platform:
        stmt = stmt.where(Post.platform == platform)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_post(
    session: AsyncSession,
    post_id: str,
    *,
    copy: str | None = None,
    scheduled_at: datetime | None = None,
    subreddit: str | None = None,
    hashtags: str | None = None,
    target_account: str | None = None,
) -> Post:
    post = await get_post(session, post_id)
    if post.status not in (PostStatus.draft, PostStatus.pending, PostStatus.retry_scheduled):
        raise ValidationError(f"Cannot update post in '{post.status.value}' status")

    if copy is not None:
        post.copy = copy
    if scheduled_at is not None:
        post.scheduled_at = scheduled_at
    if subreddit is not None:
        post.subreddit = subreddit
    if hashtags is not None:
        post.hashtags = hashtags
    if target_account is not None:
        post.target_account = target_account

    post.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return post


async def delete_post(session: AsyncSession, post_id: str) -> None:
    post = await get_post(session, post_id)
    if post.status in (PostStatus.locked, PostStatus.posting):
        raise ValidationError(f"Cannot delete post in '{post.status.value}' status")
    await session.delete(post)
    await session.flush()


async def get_post_with_campaign(session: AsyncSession, slug: str, post_id: str) -> Post:
    """Get a post ensuring it belongs to the campaign with the given slug."""
    result = await session.execute(
        select(Post)
        .join(Campaign)
        .where(Campaign.slug == slug, Post.id == post_id)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise NotFoundError("Post", post_id)
    return post
