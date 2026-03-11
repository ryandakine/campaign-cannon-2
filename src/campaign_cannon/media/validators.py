"""Platform-specific media validation rules.

Each platform defines maximum file sizes and allowed MIME types.
``validate_for_platform()`` checks a file against these rules and
returns a ``ValidationResult``.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path

from campaign_cannon.db.models import Platform

# ── Constants ──────────────────────────────────────────────────────────

_MB = 1024 * 1024

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm"}

PLATFORM_LIMITS: dict[Platform, dict] = {
    Platform.TWITTER: {
        "max_image_bytes": 5 * _MB,
        "max_video_bytes": 512 * _MB,
        "allowed_image_types": ALLOWED_IMAGE_TYPES,
        "allowed_video_types": ALLOWED_VIDEO_TYPES,
    },
    Platform.REDDIT: {
        "max_image_bytes": 20 * _MB,
        "max_video_bytes": 0,  # Reddit video upload via API is limited
        "allowed_image_types": ALLOWED_IMAGE_TYPES,
        "allowed_video_types": set(),
    },
    Platform.LINKEDIN: {
        "max_image_bytes": 10 * _MB,
        "max_video_bytes": 0,
        "allowed_image_types": ALLOWED_IMAGE_TYPES,
        "allowed_video_types": set(),
    },
}


# ── Result type ────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    """Outcome of validating a media file against platform rules."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)


# ── Public API ─────────────────────────────────────────────────────────


def validate_for_platform(
    file_path: str | Path,
    platform: Platform,
) -> ValidationResult:
    """Validate a media file against the rules for *platform*.

    Checks:
    - File exists
    - MIME type is allowed for the platform
    - File size is within the platform limit

    Returns a ``ValidationResult`` with ``valid=True`` if all checks pass,
    or ``valid=False`` with a list of human-readable error strings.
    """
    path = Path(file_path)
    result = ValidationResult()

    if not path.exists():
        result.valid = False
        result.errors.append(f"File not found: {path}")
        return result

    limits = PLATFORM_LIMITS.get(platform)
    if limits is None:
        result.valid = False
        result.errors.append(f"Unknown platform: {platform}")
        return result

    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "application/octet-stream"
    size = path.stat().st_size

    is_image = mime in limits["allowed_image_types"]
    is_video = mime in limits.get("allowed_video_types", set())

    if not is_image and not is_video:
        result.valid = False
        result.errors.append(
            f"MIME type '{mime}' is not allowed for {platform.value}. "
            f"Allowed images: {sorted(limits['allowed_image_types'])}"
        )
        return result

    if is_image:
        max_bytes = limits["max_image_bytes"]
        if size > max_bytes:
            result.valid = False
            result.errors.append(
                f"Image too large for {platform.value}: "
                f"{size / _MB:.1f} MB > {max_bytes / _MB:.0f} MB limit"
            )

    if is_video:
        max_bytes = limits["max_video_bytes"]
        if max_bytes == 0:
            result.valid = False
            result.errors.append(f"Video uploads not supported for {platform.value}")
        elif size > max_bytes:
            result.valid = False
            result.errors.append(
                f"Video too large for {platform.value}: "
                f"{size / _MB:.1f} MB > {max_bytes / _MB:.0f} MB limit"
            )

    return result
