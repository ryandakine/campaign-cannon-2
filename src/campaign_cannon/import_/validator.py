"""Import payload validation for Campaign Cannon.

Validates campaign import payloads against platform-specific rules,
date constraints, content length limits, and media requirements.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from campaign_cannon.api.schemas import CampaignImportRequest, PostImport
from campaign_cannon.db.models import Platform


# ── Platform Constraints ────────────────────────────────────────────────────

PLATFORM_BODY_LIMITS: dict[Platform, int] = {
    Platform.TWITTER: 280,
    Platform.REDDIT: 40_000,
    Platform.LINKEDIN: 3_000,
}

PLATFORM_IMAGE_SIZE_MB: dict[Platform, int] = {
    Platform.TWITTER: 5,
    Platform.REDDIT: 20,
    Platform.LINKEDIN: 10,
}

PLATFORM_VIDEO_SIZE_MB: dict[Platform, int] = {
    Platform.TWITTER: 512,
    Platform.REDDIT: 1_000,
    Platform.LINKEDIN: 200,
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv"}


# ── Result Model ────────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    """Result of import payload validation."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.valid = False

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


# ── Validation Functions ────────────────────────────────────────────────────


def validate_import(
    payload: CampaignImportRequest,
    check_media_exists: bool = True,
) -> ValidationResult:
    """Validate a full campaign import payload.

    Args:
        payload: The campaign import request to validate.
        check_media_exists: Whether to check that media files exist on disk.

    Returns:
        ValidationResult with errors and warnings.
    """
    result = ValidationResult()

    # Check for duplicate post slugs within campaign
    _validate_unique_slugs(payload, result)

    # Validate each post
    for i, post in enumerate(payload.posts):
        prefix = f"posts[{i}] (slug={post.slug!r})"
        _validate_post_platform_rules(post, prefix, result)
        _validate_post_schedule(post, prefix, result)
        _validate_post_body_length(post, prefix, result)
        if check_media_exists:
            _validate_post_media(post, payload.media_base_path, prefix, result)

    return result


def _validate_unique_slugs(payload: CampaignImportRequest, result: ValidationResult) -> None:
    """Check for duplicate slugs within the campaign."""
    seen: dict[str, int] = {}
    for i, post in enumerate(payload.posts):
        if post.slug in seen:
            result.add_error(
                f"Duplicate post slug {post.slug!r} at index {i} "
                f"(first seen at index {seen[post.slug]})"
            )
        else:
            seen[post.slug] = i


def _validate_post_platform_rules(
    post: PostImport, prefix: str, result: ValidationResult
) -> None:
    """Validate platform-specific required fields."""
    if post.platform == Platform.REDDIT:
        if not post.title:
            result.add_error(f"{prefix}: title is required for Reddit posts")
        if not post.subreddit:
            result.add_error(f"{prefix}: subreddit is required for Reddit posts")


def _validate_post_schedule(post: PostImport, prefix: str, result: ValidationResult) -> None:
    """Validate that scheduled_at is in the future."""
    now = datetime.now(timezone.utc)
    scheduled = post.scheduled_at
    # Ensure timezone-aware comparison
    if scheduled.tzinfo is None:
        result.add_error(f"{prefix}: scheduled_at must include timezone info")
        return
    if scheduled <= now:
        result.add_warning(f"{prefix}: scheduled_at is in the past ({scheduled.isoformat()})")


def _validate_post_body_length(
    post: PostImport, prefix: str, result: ValidationResult
) -> None:
    """Validate body length against platform limits."""
    limit = PLATFORM_BODY_LIMITS.get(post.platform)
    if limit and len(post.body) > limit:
        result.add_error(
            f"{prefix}: body length ({len(post.body)} chars) exceeds "
            f"{post.platform.value} limit of {limit} chars"
        )


def _validate_post_media(
    post: PostImport,
    media_base_path: str | None,
    prefix: str,
    result: ValidationResult,
) -> None:
    """Validate media files exist and meet platform constraints."""
    for media_path in post.media_paths:
        # Resolve path
        if media_base_path and not os.path.isabs(media_path):
            full_path = os.path.join(media_base_path, media_path)
        else:
            full_path = media_path

        # Check existence
        if not os.path.exists(full_path):
            result.add_error(f"{prefix}: media file not found: {full_path}")
            continue

        # Check file size
        file_size_bytes = os.path.getsize(full_path)
        ext = os.path.splitext(full_path)[1].lower()

        if ext in IMAGE_EXTENSIONS:
            max_mb = PLATFORM_IMAGE_SIZE_MB.get(post.platform, 20)
            if file_size_bytes > max_mb * 1024 * 1024:
                result.add_error(
                    f"{prefix}: image {media_path} ({file_size_bytes / 1024 / 1024:.1f}MB) "
                    f"exceeds {post.platform.value} limit of {max_mb}MB"
                )
        elif ext in VIDEO_EXTENSIONS:
            max_mb = PLATFORM_VIDEO_SIZE_MB.get(post.platform, 512)
            if file_size_bytes > max_mb * 1024 * 1024:
                result.add_error(
                    f"{prefix}: video {media_path} ({file_size_bytes / 1024 / 1024:.1f}MB) "
                    f"exceeds {post.platform.value} limit of {max_mb}MB"
                )
        else:
            result.add_warning(f"{prefix}: unrecognized media file extension: {ext}")
