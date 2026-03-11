"""Media asset pipeline — copy-on-import, SHA-256 hashing, MIME detection.

Assets are copied into ``./campaigns/{slug}/media/`` so originals are
never modified. Each file is hashed and validated before a ``MediaAsset``
record is created.
"""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
from pathlib import Path

from campaign_cannon.db.models import MediaAsset, Post
from campaign_cannon.media.validators import validate_for_platform


def _sha256(path: Path) -> str:
    """Return the hex-encoded SHA-256 digest of *path*."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _detect_mime(path: Path) -> str:
    """Best-effort MIME type detection using the file extension."""
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def import_assets(
    campaign_slug: str,
    post: Post,
    source_paths: list[str | Path],
) -> list[MediaAsset]:
    """Copy source files into the campaign media directory and create asset records.

    Parameters
    ----------
    campaign_slug:
        Slug of the owning campaign (used as directory name).
    post:
        The ``Post`` these assets belong to.
    source_paths:
        Absolute or relative paths to the original files.

    Returns
    -------
    List of ``MediaAsset`` instances (not yet committed — caller manages session).

    Raises
    ------
    FileNotFoundError
        If a source file does not exist.
    ValueError
        If a file fails platform validation.
    """
    media_dir = Path("campaigns") / campaign_slug / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    assets: list[MediaAsset] = []
    for src in source_paths:
        src_path = Path(src)
        if not src_path.exists():
            raise FileNotFoundError(f"Source file not found: {src_path}")

        # Copy to campaign media dir (preserve filename, avoid overwrites)
        dest = media_dir / src_path.name
        counter = 1
        while dest.exists():
            dest = media_dir / f"{src_path.stem}_{counter}{src_path.suffix}"
            counter += 1
        shutil.copy2(src_path, dest)

        # Hash + MIME
        sha = _sha256(dest)
        mime = _detect_mime(dest)
        size = dest.stat().st_size

        # Validate against platform rules
        result = validate_for_platform(dest, post.platform)
        if not result.valid:
            dest.unlink()  # clean up the copy
            raise ValueError(
                f"File {src_path.name} failed validation for "
                f"{post.platform.value}: {'; '.join(result.errors)}"
            )

        asset = MediaAsset(
            post_id=str(post.id),
            file_path=str(dest),
            original_path=str(src_path),
            sha256_hash=sha,
            mime_type=mime,
            size_bytes=size,
        )
        assets.append(asset)

    return assets


def verify_asset(media_asset: MediaAsset) -> bool:
    """Re-hash the file on disk and compare to the stored SHA-256 digest."""
    path = Path(media_asset.file_path)
    if not path.exists():
        return False
    return _sha256(path) == media_asset.sha256_hash
