"""Tests for state machine transition logic."""

from __future__ import annotations

import pytest

from src.db.models import (
    CAMPAIGN_TRANSITIONS,
    POST_TRANSITIONS,
    Campaign,
    CampaignStatus,
    Post,
    PostStatus,
)


class TestCampaignTransitions:
    def test_draft_can_activate(self):
        c = Campaign(slug="t", name="t", status=CampaignStatus.draft)
        assert c.can_transition_to(CampaignStatus.active) is True

    def test_draft_can_cancel(self):
        c = Campaign(slug="t", name="t", status=CampaignStatus.draft)
        assert c.can_transition_to(CampaignStatus.cancelled) is True

    def test_draft_cannot_pause(self):
        c = Campaign(slug="t", name="t", status=CampaignStatus.draft)
        assert c.can_transition_to(CampaignStatus.paused) is False

    def test_draft_cannot_complete(self):
        c = Campaign(slug="t", name="t", status=CampaignStatus.draft)
        assert c.can_transition_to(CampaignStatus.completed) is False

    def test_active_can_pause(self):
        c = Campaign(slug="t", name="t", status=CampaignStatus.active)
        assert c.can_transition_to(CampaignStatus.paused) is True

    def test_active_can_complete(self):
        c = Campaign(slug="t", name="t", status=CampaignStatus.active)
        assert c.can_transition_to(CampaignStatus.completed) is True

    def test_active_can_cancel(self):
        c = Campaign(slug="t", name="t", status=CampaignStatus.active)
        assert c.can_transition_to(CampaignStatus.cancelled) is True

    def test_active_cannot_go_to_draft(self):
        c = Campaign(slug="t", name="t", status=CampaignStatus.active)
        assert c.can_transition_to(CampaignStatus.draft) is False

    def test_paused_can_resume(self):
        c = Campaign(slug="t", name="t", status=CampaignStatus.paused)
        assert c.can_transition_to(CampaignStatus.active) is True

    def test_paused_can_cancel(self):
        c = Campaign(slug="t", name="t", status=CampaignStatus.paused)
        assert c.can_transition_to(CampaignStatus.cancelled) is True

    def test_completed_is_terminal(self):
        c = Campaign(slug="t", name="t", status=CampaignStatus.completed)
        for target in CampaignStatus:
            assert c.can_transition_to(target) is False

    def test_cancelled_is_terminal(self):
        c = Campaign(slug="t", name="t", status=CampaignStatus.cancelled)
        for target in CampaignStatus:
            assert c.can_transition_to(target) is False

    def test_all_states_have_transition_entries(self):
        for status in CampaignStatus:
            assert status in CAMPAIGN_TRANSITIONS


class TestPostTransitions:
    def test_draft_to_pending(self):
        p = Post(
            campaign_id="x", platform="twitter", copy="hi",
            scheduled_at="2025-01-01", dedup_key="k1", status=PostStatus.draft,
        )
        assert p.can_transition_to(PostStatus.pending) is True

    def test_pending_to_locked(self):
        p = Post(
            campaign_id="x", platform="twitter", copy="hi",
            scheduled_at="2025-01-01", dedup_key="k2", status=PostStatus.pending,
        )
        assert p.can_transition_to(PostStatus.locked) is True

    def test_locked_to_posting(self):
        p = Post(
            campaign_id="x", platform="twitter", copy="hi",
            scheduled_at="2025-01-01", dedup_key="k3", status=PostStatus.locked,
        )
        assert p.can_transition_to(PostStatus.posting) is True

    def test_posting_to_posted(self):
        p = Post(
            campaign_id="x", platform="twitter", copy="hi",
            scheduled_at="2025-01-01", dedup_key="k4", status=PostStatus.posting,
        )
        assert p.can_transition_to(PostStatus.posted) is True

    def test_posting_to_retry_scheduled(self):
        p = Post(
            campaign_id="x", platform="twitter", copy="hi",
            scheduled_at="2025-01-01", dedup_key="k5", status=PostStatus.posting,
        )
        assert p.can_transition_to(PostStatus.retry_scheduled) is True

    def test_posting_to_failed(self):
        p = Post(
            campaign_id="x", platform="twitter", copy="hi",
            scheduled_at="2025-01-01", dedup_key="k6", status=PostStatus.posting,
        )
        assert p.can_transition_to(PostStatus.failed) is True

    def test_posted_is_terminal(self):
        p = Post(
            campaign_id="x", platform="twitter", copy="hi",
            scheduled_at="2025-01-01", dedup_key="k7", status=PostStatus.posted,
        )
        for target in PostStatus:
            assert p.can_transition_to(target) is False

    def test_failed_is_terminal(self):
        p = Post(
            campaign_id="x", platform="twitter", copy="hi",
            scheduled_at="2025-01-01", dedup_key="k8", status=PostStatus.failed,
        )
        for target in PostStatus:
            assert p.can_transition_to(target) is False

    def test_all_states_have_transition_entries(self):
        for status in PostStatus:
            assert status in POST_TRANSITIONS
