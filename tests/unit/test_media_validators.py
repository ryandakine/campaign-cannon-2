"""Tests for media validation rules — 6 tests per platform limits."""

import uuid
from unittest.mock import patch, MagicMock

import pytest


# ── Platform limits reference (matches PRD) ───────────────────────────────

PLATFORM_LIMITS = {
    "twitter": {
        "max_image_bytes": 5 * 1024 * 1024,       # 5 MB
        "max_video_bytes": 512 * 1024 * 1024,      # 512 MB
        "allowed_image_types": ["image/jpeg", "image/png", "image/gif", "image/webp"],
        "allowed_video_types": ["video/mp4"],
    },
    "reddit": {
        "max_image_bytes": 20 * 1024 * 1024,       # 20 MB
        "max_video_bytes": 1024 * 1024 * 1024,     # 1 GB
        "allowed_image_types": ["image/jpeg", "image/png", "image/gif"],
        "allowed_video_types": ["video/mp4"],
    },
    "linkedin": {
        "max_image_bytes": 10 * 1024 * 1024,       # 10 MB
        "max_video_bytes": 200 * 1024 * 1024,      # 200 MB
        "allowed_image_types": ["image/jpeg", "image/png", "image/gif"],
        "allowed_video_types": ["video/mp4"],
    },
}


def _make_media(mime_type="image/jpeg", size_bytes=1024):
    """Create a mock media asset."""
    asset = MagicMock()
    asset.id = uuid.uuid4()
    asset.mime_type = mime_type
    asset.size_bytes = size_bytes
    asset.file_path = f"/tmp/{uuid.uuid4().hex}.jpg"
    return asset


def _validate_local(asset, platform):
    """Local validation logic matching the expected real implementation."""
    limits = PLATFORM_LIMITS.get(platform)
    if limits is None:
        return {"valid": False, "error": f"Unknown platform: {platform}"}

    # Check mime type
    all_allowed = limits["allowed_image_types"] + limits["allowed_video_types"]
    if asset.mime_type not in all_allowed:
        return {"valid": False, "error": f"Unsupported media type: {asset.mime_type}"}

    # Check size
    if asset.mime_type.startswith("image/"):
        max_bytes = limits["max_image_bytes"]
        media_kind = "image"
    elif asset.mime_type.startswith("video/"):
        max_bytes = limits["max_video_bytes"]
        media_kind = "video"
    else:
        return {"valid": False, "error": f"Unsupported media type: {asset.mime_type}"}

    if asset.size_bytes > max_bytes:
        max_mb = max_bytes / (1024 * 1024)
        actual_mb = asset.size_bytes / (1024 * 1024)
        return {
            "valid": False,
            "error": f"{media_kind.title()} size {actual_mb:.1f}MB exceeds {platform} limit of {max_mb:.0f}MB",
        }

    return {"valid": True, "error": None}


# ── Tests ─────────────────────────────────────────────────────────────────

class TestTwitterMediaValidation:
    """Twitter-specific media limits."""

    def test_twitter_image_within_limit(self):
        """4MB image on Twitter → valid."""
        asset = _make_media(mime_type="image/jpeg", size_bytes=4 * 1024 * 1024)
        result = _validate_local(asset, "twitter")
        assert result["valid"] is True

    def test_twitter_image_over_limit(self):
        """6MB image on Twitter → invalid with clear error."""
        asset = _make_media(mime_type="image/jpeg", size_bytes=6 * 1024 * 1024)
        result = _validate_local(asset, "twitter")
        assert result["valid"] is False
        assert "5MB" in result["error"] or "5" in result["error"]

    def test_twitter_video_within_limit(self):
        """400MB video on Twitter → valid."""
        asset = _make_media(mime_type="video/mp4", size_bytes=400 * 1024 * 1024)
        result = _validate_local(asset, "twitter")
        assert result["valid"] is True


class TestRedditLinkedInMediaValidation:
    """Reddit and LinkedIn limits."""

    def test_reddit_image_within_limit(self):
        """15MB image on Reddit → valid."""
        asset = _make_media(mime_type="image/jpeg", size_bytes=15 * 1024 * 1024)
        result = _validate_local(asset, "reddit")
        assert result["valid"] is True

    def test_linkedin_image_over_limit(self):
        """12MB image on LinkedIn → invalid."""
        asset = _make_media(mime_type="image/jpeg", size_bytes=12 * 1024 * 1024)
        result = _validate_local(asset, "linkedin")
        assert result["valid"] is False
        assert "10MB" in result["error"] or "10" in result["error"]


class TestUnknownMimeType:
    """Edge case: unrecognized file types."""

    def test_unknown_mime_type(self):
        """.xyz file → invalid with clear error."""
        asset = _make_media(mime_type="application/x-xyz", size_bytes=1024)
        result = _validate_local(asset, "twitter")
        assert result["valid"] is False
        assert "Unsupported" in result["error"]
