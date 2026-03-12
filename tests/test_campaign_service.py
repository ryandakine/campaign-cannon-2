"""Tests for campaign service."""

from __future__ import annotations

import pytest

from src.db.models import Campaign, CampaignStatus, PostStatus
from src.exceptions import NotFoundError, SlugConflictError, StateTransitionError, ValidationError
from src.services.campaign_service import (
    activate_campaign,
    cancel_campaign,
    create_campaign,
    get_campaign,
    list_campaigns,
    pause_campaign,
    resume_campaign,
    update_campaign,
    validate_slug,
)


class TestValidateSlug:
    def test_valid_slugs(self):
        for slug in ["my-campaign", "abc", "test-123", "a" * 255]:
            validate_slug(slug)  # should not raise

    def test_too_short(self):
        with pytest.raises(ValidationError):
            validate_slug("ab")

    def test_starts_with_hyphen(self):
        with pytest.raises(ValidationError):
            validate_slug("-bad")

    def test_ends_with_hyphen(self):
        with pytest.raises(ValidationError):
            validate_slug("bad-")

    def test_uppercase_rejected(self):
        with pytest.raises(ValidationError):
            validate_slug("Bad-Campaign")

    def test_spaces_rejected(self):
        with pytest.raises(ValidationError):
            validate_slug("bad campaign")


class TestCreateCampaign:
    async def test_create_basic(self, session):
        c = await create_campaign(session, slug="my-test", name="My Test")
        assert c.slug == "my-test"
        assert c.name == "My Test"
        assert c.status == CampaignStatus.draft
        assert c.id is not None

    async def test_create_with_options(self, session):
        c = await create_campaign(
            session,
            slug="full-test",
            name="Full",
            description="Desc",
            timezone_str="US/Eastern",
            catch_up=True,
        )
        assert c.description == "Desc"
        assert c.timezone == "US/Eastern"
        assert c.catch_up is True

    async def test_duplicate_slug_raises(self, session):
        await create_campaign(session, slug="unique-slug", name="First")
        with pytest.raises(SlugConflictError):
            await create_campaign(session, slug="unique-slug", name="Second")

    async def test_invalid_slug_raises(self, session):
        with pytest.raises(ValidationError):
            await create_campaign(session, slug="BAD!", name="Invalid")


class TestGetCampaign:
    async def test_get_existing(self, session, campaign):
        result = await get_campaign(session, "test-campaign")
        assert result.id == campaign.id

    async def test_get_nonexistent_raises(self, session):
        with pytest.raises(NotFoundError):
            await get_campaign(session, "nonexistent")


class TestListCampaigns:
    async def test_list_all(self, session, campaign):
        result = await list_campaigns(session)
        assert len(result) >= 1

    async def test_list_by_status(self, session, campaign, active_campaign):
        drafts = await list_campaigns(session, status=CampaignStatus.draft)
        assert all(c.status == CampaignStatus.draft for c in drafts)

    async def test_pagination(self, session):
        for i in range(5):
            await create_campaign(session, slug=f"page-test-{i:03d}", name=f"P{i}")
        result = await list_campaigns(session, limit=2, offset=0)
        assert len(result) == 2


class TestUpdateCampaign:
    async def test_update_name(self, session, campaign):
        result = await update_campaign(session, "test-campaign", name="New Name")
        assert result.name == "New Name"

    async def test_update_non_draft_raises(self, session, active_campaign):
        with pytest.raises(ValidationError, match="Only draft"):
            await update_campaign(session, "active-campaign", name="X")


class TestCampaignLifecycle:
    async def test_activate(self, session, campaign):
        result = await activate_campaign(session, "test-campaign")
        assert result.status == CampaignStatus.active

    async def test_activate_transitions_draft_posts(self, session, campaign, post_factory):
        post = await post_factory(campaign.id, status=PostStatus.draft)
        await activate_campaign(session, "test-campaign")
        await session.refresh(post)
        assert post.status == PostStatus.pending

    async def test_pause_active(self, session, active_campaign):
        result = await pause_campaign(session, "active-campaign")
        assert result.status == CampaignStatus.paused

    async def test_resume_paused(self, session, active_campaign):
        await pause_campaign(session, "active-campaign")
        result = await resume_campaign(session, "active-campaign")
        assert result.status == CampaignStatus.active

    async def test_cancel_cancels_non_terminal_posts(self, session, active_campaign, post_factory):
        p1 = await post_factory(active_campaign.id, status=PostStatus.pending)
        p2 = await post_factory(active_campaign.id, status=PostStatus.posted)
        await cancel_campaign(session, "active-campaign")
        await session.refresh(p1)
        await session.refresh(p2)
        assert p1.status == PostStatus.cancelled
        assert p2.status == PostStatus.posted  # terminal, unchanged

    async def test_invalid_transition_raises(self, session, campaign):
        with pytest.raises(StateTransitionError):
            await pause_campaign(session, "test-campaign")  # draft cannot pause
