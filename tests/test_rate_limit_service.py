"""Tests for rate limit service."""

from __future__ import annotations

import pytest

from src.db.models import Platform
from src.exceptions import RateLimitExceededError
from src.services.rate_limit_service import (
    check_rate_limit,
    enforce_rate_limit,
    get_rate_limit_status,
    record_api_call,
)


class TestCheckRateLimit:
    async def test_allows_first_call(self, session):
        allowed = await check_rate_limit(session, Platform.twitter.value)
        assert allowed is True

    async def test_unknown_platform_always_allowed(self, session):
        allowed = await check_rate_limit(session, "mastodon")
        assert allowed is True

    async def test_allows_within_limit(self, session):
        for _ in range(5):
            await record_api_call(session, Platform.reddit.value)
        allowed = await check_rate_limit(session, Platform.reddit.value)
        assert allowed is True


class TestRecordApiCall:
    async def test_record_increments_count(self, session):
        await record_api_call(session, Platform.twitter.value)
        await record_api_call(session, Platform.twitter.value)
        status = await get_rate_limit_status(session)
        twitter_status = next(s for s in status if s["platform"] == Platform.twitter.value)
        assert twitter_status["calls_made"] == 2


class TestEnforceRateLimit:
    async def test_enforce_does_not_raise_when_allowed(self, session):
        await enforce_rate_limit(session, Platform.twitter.value)  # should not raise

    async def test_enforce_raises_when_exceeded(self, session):
        # Fill up Reddit's low limit (10/min)
        for _ in range(10):
            await record_api_call(session, Platform.reddit.value)
        with pytest.raises(RateLimitExceededError):
            await enforce_rate_limit(session, Platform.reddit.value)


class TestGetStatus:
    async def test_returns_all_platforms(self, session):
        status = await get_rate_limit_status(session)
        platforms = {s["platform"] for s in status}
        assert Platform.twitter.value in platforms
        assert Platform.reddit.value in platforms

    async def test_status_has_headroom(self, session):
        status = await get_rate_limit_status(session)
        for s in status:
            assert "headroom_pct" in s
            assert 0 <= s["headroom_pct"] <= 100
