"""Tests for post service."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.db.models import Platform, PostStatus
from src.exceptions import NotFoundError, ValidationError
from src.services.post_service import (
    create_post,
    delete_post,
    generate_dedup_key,
    get_post,
    list_posts,
    update_post,
)


class TestDedupKey:
    def test_deterministic(self):
        ts = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        k1 = generate_dedup_key("c1", "twitter", ts, "Hello")
        k2 = generate_dedup_key("c1", "twitter", ts, "Hello")
        assert k1 == k2

    def test_different_content_produces_different_key(self):
        ts = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        k1 = generate_dedup_key("c1", "twitter", ts, "Hello")
        k2 = generate_dedup_key("c1", "twitter", ts, "Goodbye")
        assert k1 != k2


class TestCreatePost:
    async def test_create_twitter_post(self, session, campaign):
        ts = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        p = await create_post(
            session,
            campaign_id=campaign.id,
            platform=Platform.twitter,
            copy="Test tweet",
            scheduled_at=ts,
        )
        assert p.platform == Platform.twitter
        assert p.copy == "Test tweet"
        assert p.status == PostStatus.draft
        assert p.dedup_key is not None

    async def test_create_reddit_requires_subreddit(self, session, campaign):
        ts = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(ValidationError, match="subreddit"):
            await create_post(
                session,
                campaign_id=campaign.id,
                platform=Platform.reddit,
                copy="Test post",
                scheduled_at=ts,
            )

    async def test_create_reddit_with_subreddit(self, session, campaign):
        ts = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        p = await create_post(
            session,
            campaign_id=campaign.id,
            platform=Platform.reddit,
            copy="Test post",
            scheduled_at=ts,
            subreddit="test",
        )
        assert p.subreddit == "test"

    async def test_dedup_collision_gets_unique_suffix(self, session, campaign):
        ts = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        p1 = await create_post(
            session,
            campaign_id=campaign.id,
            platform=Platform.twitter,
            copy="Same content",
            scheduled_at=ts,
        )
        p2 = await create_post(
            session,
            campaign_id=campaign.id,
            platform=Platform.twitter,
            copy="Same content",
            scheduled_at=ts,
        )
        assert p1.dedup_key != p2.dedup_key


class TestGetPost:
    async def test_get_existing(self, session, campaign, post_factory):
        post = await post_factory(campaign.id)
        result = await get_post(session, post.id)
        assert result.id == post.id

    async def test_get_nonexistent_raises(self, session):
        with pytest.raises(NotFoundError):
            await get_post(session, "nonexistent-id")


class TestListPosts:
    async def test_list_by_campaign(self, session, campaign, post_factory):
        await post_factory(campaign.id, copy="Post 1")
        await post_factory(campaign.id, copy="Post 2")
        result = await list_posts(session, campaign.id)
        assert len(result) == 2

    async def test_filter_by_status(self, session, campaign, post_factory):
        await post_factory(campaign.id, status=PostStatus.draft)
        await post_factory(campaign.id, status=PostStatus.pending)
        result = await list_posts(session, campaign.id, status=PostStatus.draft)
        assert len(result) == 1
        assert result[0].status == PostStatus.draft

    async def test_filter_by_platform(self, session, campaign, post_factory):
        await post_factory(campaign.id, platform=Platform.twitter)
        await post_factory(campaign.id, platform=Platform.reddit, subreddit="test")
        result = await list_posts(session, campaign.id, platform=Platform.twitter)
        assert len(result) == 1
        assert result[0].platform == Platform.twitter


class TestUpdatePost:
    async def test_update_copy(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.draft)
        result = await update_post(session, post.id, copy="Updated!")
        assert result.copy == "Updated!"

    async def test_cannot_update_posted(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.posted)
        with pytest.raises(ValidationError, match="Cannot update"):
            await update_post(session, post.id, copy="Nope")

    async def test_can_update_pending(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.pending)
        result = await update_post(session, post.id, copy="Still ok")
        assert result.copy == "Still ok"


class TestDeletePost:
    async def test_delete_draft(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.draft)
        await delete_post(session, post.id)
        with pytest.raises(NotFoundError):
            await get_post(session, post.id)

    async def test_cannot_delete_locked(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.locked)
        with pytest.raises(ValidationError, match="Cannot delete"):
            await delete_post(session, post.id)

    async def test_cannot_delete_posting(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.posting)
        with pytest.raises(ValidationError, match="Cannot delete"):
            await delete_post(session, post.id)
