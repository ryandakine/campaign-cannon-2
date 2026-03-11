"""Idempotency key generation and duplicate detection.

Prevents double-publishing by:
1. Generating deterministic SHA-256 idempotency keys per post.
2. Checking for existing posts with the same key before publishing.
3. Detecting near-duplicate content to the same platform within a time window.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from campaign_cannon.db.models import Post

logger = structlog.get_logger(__name__)


def generate_idempotency_key(
    campaign_id: str,
    post_slug: str,
    platform: str,
    scheduled_at: datetime,
) -> str:
    """Generate a deterministic idempotency key for a post.

    The key is a SHA-256 hex digest of the composite:
        "{campaign_id}:{post_slug}:{platform}:{scheduled_at.isoformat()}"

    This guarantees that re-importing the same campaign data produces
    identical keys, preventing duplicate publishes.

    Args:
        campaign_id: UUID of the campaign.
        post_slug: Slug or unique identifier within the campaign.
        platform: Platform name (e.g. "TWITTER").
        scheduled_at: Scheduled publish time.

    Returns:
        64-character hex digest string.
    """
    payload = f"{campaign_id}:{post_slug}:{platform}:{scheduled_at.isoformat()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def check_duplicate(session: Session, idempotency_key: str) -> Optional[Post]:
    """Check if a post with this idempotency key already exists.

    Args:
        session: Active SQLAlchemy session.
        idempotency_key: The key to look up.

    Returns:
        The existing Post if found, None otherwise.
    """
    from campaign_cannon.db.models import Post

    existing = (
        session.query(Post)
        .filter(Post.idempotency_key == idempotency_key)
        .first()
    )
    if existing:
        logger.info(
            "duplicate_detected",
            idempotency_key=idempotency_key,
            post_id=str(existing.id),
            state=str(existing.state),
        )
    return existing


def _hash_body(body_text: str) -> str:
    """Hash body text for content-duplicate comparison.

    Normalises whitespace before hashing so minor formatting changes
    don't defeat duplicate detection.
    """
    normalised = " ".join(body_text.split()).strip().lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def detect_content_duplicate(
    session: Session,
    platform: str,
    body_text: str,
    window_hours: int = 24,
) -> list[Post]:
    """Find posts with identical body text to the same platform within a time window.

    This is advisory (returns matches but does not block publishing).
    Callers may log a warning or surface it in the UI.

    Args:
        session: Active SQLAlchemy session.
        platform: Platform name to scope the search.
        body_text: The text content to check.
        window_hours: Look-back window in hours (default 24).

    Returns:
        List of Post objects that are potential duplicates.
    """
    from campaign_cannon.db.models import Post, PostState

    body_hash = _hash_body(body_text)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    # We need to hash each candidate's body for comparison.  For efficiency we
    # filter by platform + recent time window first, then compare hashes in
    # Python.  With SQLite there's no native SHA-256 function.
    candidates = (
        session.query(Post)
        .filter(
            Post.platform == platform,
            Post.scheduled_at >= cutoff,
            Post.state.in_([
                PostState.QUEUED,
                PostState.PUBLISHING,
                PostState.POSTED,
            ]),
        )
        .all()
    )

    duplicates = [
        p for p in candidates
        if p.body and _hash_body(p.body) == body_hash
    ]

    if duplicates:
        logger.warning(
            "content_duplicates_found",
            platform=platform,
            duplicate_count=len(duplicates),
            post_ids=[str(p.id) for p in duplicates],
            window_hours=window_hours,
        )

    return duplicates
