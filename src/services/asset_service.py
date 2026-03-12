"""Asset service — file operations, SHA256 hashing, validation."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path

import structlog

from src.config import LOCAL_STORAGE_PATH, MAX_IMAGE_MB, MAX_VIDEO_MB
from src.exceptions import MediaValidationError, ValidationError

logger = structlog.get_logger()

# Safe filename pattern
_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-. ]{0,248}[a-zA-Z0-9.]$")

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/webm"}
ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES

# Extension to MIME type mapping
EXTENSION_MIME_MAP: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal."""
    # Strip directory components
    filename = os.path.basename(filename)
    # Remove null bytes
    filename = filename.replace("\x00", "")
    # Check against safe pattern
    if not filename or not _SAFE_FILENAME_RE.match(filename):
        # Replace unsafe chars
        safe = re.sub(r"[^a-zA-Z0-9_\-.]", "_", filename)
        if not safe:
            raise ValidationError("Invalid filename")
        filename = safe
    return filename


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_campaign_media_dir(campaign_slug: str) -> Path:
    """Get the media directory for a campaign."""
    media_dir = LOCAL_STORAGE_PATH / campaign_slug / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    return media_dir


def validate_media_file(
    file_path: Path,
    mime_type: str,
    platform: str = "twitter",
) -> None:
    """Validate a media file for platform requirements."""
    if mime_type not in ALLOWED_TYPES:
        raise MediaValidationError(f"Unsupported MIME type: {mime_type}")

    size_bytes = file_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)

    if mime_type in ALLOWED_IMAGE_TYPES:
        max_mb = 5 if platform == "twitter" else MAX_IMAGE_MB
        if size_mb > max_mb:
            raise MediaValidationError(
                f"Image too large: {size_mb:.1f}MB (max {max_mb}MB for {platform})"
            )
    elif mime_type in ALLOWED_VIDEO_TYPES:
        if size_mb > MAX_VIDEO_MB:
            raise MediaValidationError(
                f"Video too large: {size_mb:.1f}MB (max {MAX_VIDEO_MB}MB)"
            )


def copy_asset_to_campaign(
    source_path: Path,
    campaign_slug: str,
    filename: str,
) -> tuple[Path, str]:
    """Copy an asset file to the campaign media directory.

    Returns (destination_path, sha256_hash).
    Validates path traversal safety using realpath.
    """
    safe_filename = sanitize_filename(filename)
    media_dir = get_campaign_media_dir(campaign_slug)

    dest = media_dir / safe_filename
    # Verify no path traversal: resolved dest must be under media_dir
    resolved_dest = dest.resolve()
    resolved_media = media_dir.resolve()
    if not str(resolved_dest).startswith(str(resolved_media)):
        raise ValidationError("Path traversal detected")

    shutil.copy2(source_path, dest)
    sha256 = calculate_sha256(dest)

    logger.info("asset_copied", filename=safe_filename, sha256=sha256[:12])
    return dest, sha256


def guess_mime_type(filename: str) -> str | None:
    """Guess MIME type from file extension."""
    ext = Path(filename).suffix.lower()
    return EXTENSION_MIME_MAP.get(ext)
