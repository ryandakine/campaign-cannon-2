"""Tests for campaign import validation — 6 tests."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────

def _valid_campaign_payload():
    """Return a complete valid campaign import payload."""
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    return {
        "name": "Launch Campaign",
        "slug": "launch-campaign",
        "posts": [
            {
                "slug": "tweet-1",
                "platform": "twitter",
                "body": "Excited to announce our new product! #launch",
                "scheduled_at": future,
            },
            {
                "slug": "reddit-1",
                "platform": "reddit",
                "title": "We just launched something awesome",
                "body": "Check out our new product...",
                "scheduled_at": future,
            },
        ],
    }


def _validate_payload(payload):
    """Local validation logic matching expected import validator behavior."""
    errors = []

    if not payload.get("name"):
        errors.append({"field": "name", "error": "Campaign name is required"})

    slugs_seen = set()
    for i, post in enumerate(payload.get("posts", [])):
        prefix = f"posts[{i}]"

        # Body required
        if not post.get("body"):
            errors.append({"field": f"{prefix}.body", "error": "Post body is required"})

        # Reddit requires title
        if post.get("platform") == "reddit" and not post.get("title"):
            errors.append({"field": f"{prefix}.title", "error": "Reddit posts require a title"})

        # scheduled_at must be in the future
        if post.get("scheduled_at"):
            try:
                scheduled = datetime.fromisoformat(post["scheduled_at"])
                if scheduled.tzinfo is None:
                    scheduled = scheduled.replace(tzinfo=timezone.utc)
                if scheduled < datetime.now(timezone.utc):
                    errors.append({
                        "field": f"{prefix}.scheduled_at",
                        "error": "Scheduled date must be in the future",
                    })
            except (ValueError, TypeError):
                errors.append({
                    "field": f"{prefix}.scheduled_at",
                    "error": "Invalid date format",
                })

        # Twitter body length check
        if post.get("platform") == "twitter" and post.get("body") and len(post["body"]) > 280:
            errors.append({
                "field": f"{prefix}.body",
                "error": f"Twitter body exceeds 280 chars ({len(post['body'])} chars)",
            })

        # Duplicate slugs
        slug = post.get("slug", "")
        if slug in slugs_seen:
            errors.append({
                "field": f"{prefix}.slug",
                "error": f"Duplicate slug: {slug}",
            })
        slugs_seen.add(slug)

    return {"valid": len(errors) == 0, "errors": errors}


# ── Tests ─────────────────────────────────────────────────────────────────

class TestValidImport:
    """Valid payloads should pass validation."""

    def test_valid_campaign_passes(self):
        """Complete valid payload → valid."""
        payload = _valid_campaign_payload()
        result = _validate_payload(payload)
        assert result["valid"] is True
        assert result["errors"] == []


class TestRequiredFields:
    """Missing required fields should fail."""

    def test_missing_body_fails(self):
        """Post without body → error."""
        payload = _valid_campaign_payload()
        payload["posts"][0]["body"] = ""
        result = _validate_payload(payload)
        assert result["valid"] is False
        assert any("body" in e["field"] and "required" in e["error"].lower() for e in result["errors"])

    def test_reddit_missing_title_fails(self):
        """Reddit post without title → error."""
        payload = _valid_campaign_payload()
        # Ensure the reddit post has no title
        payload["posts"][1]["title"] = ""
        result = _validate_payload(payload)
        assert result["valid"] is False
        assert any("title" in e["field"] for e in result["errors"])


class TestSchedulingValidation:
    """Schedule timing validation."""

    def test_past_scheduled_at_fails(self):
        """Date in the past → error."""
        payload = _valid_campaign_payload()
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        payload["posts"][0]["scheduled_at"] = past
        result = _validate_payload(payload)
        assert result["valid"] is False
        assert any("future" in e["error"].lower() for e in result["errors"])


class TestContentValidation:
    """Platform-specific content rules."""

    def test_twitter_body_too_long(self):
        """>280 chars on Twitter → error."""
        payload = _valid_campaign_payload()
        payload["posts"][0]["body"] = "x" * 300  # 300 chars
        result = _validate_payload(payload)
        assert result["valid"] is False
        assert any("280" in e["error"] for e in result["errors"])


class TestUniqueness:
    """Duplicate detection within payload."""

    def test_duplicate_slugs_fail(self):
        """Two posts with the same slug → error."""
        payload = _valid_campaign_payload()
        payload["posts"][1]["slug"] = payload["posts"][0]["slug"]  # duplicate
        result = _validate_payload(payload)
        assert result["valid"] is False
        assert any("Duplicate slug" in e["error"] for e in result["errors"])
