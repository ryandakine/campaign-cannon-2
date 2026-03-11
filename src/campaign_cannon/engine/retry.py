"""Exponential-backoff retry logic for failed posts.

Default schedule: 30 s → 120 s → 480 s (base=30, multiplier=4).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from campaign_cannon.config.settings import get_settings
from campaign_cannon.db.models import Post, PostState
from campaign_cannon.engine.state_machine import transition


def should_retry(post: Post) -> bool:
    """Return True if the post has retries remaining."""
    return post.retry_count < post.max_retries


def next_retry_delay(post: Post) -> timedelta:
    """Calculate the backoff delay for the next retry attempt.

    Formula: base * (multiplier ** retry_count) seconds.
    """
    settings = get_settings()
    seconds = settings.backoff_base * (settings.backoff_multiplier ** post.retry_count)
    return timedelta(seconds=seconds)


def schedule_retry(session: Session, post: Post) -> datetime:
    """Move a FAILED post through RETRY → QUEUED and schedule the next attempt.

    Returns the new ``scheduled_at`` time for the post.

    Raises ``InvalidTransitionError`` if the post is not in FAILED state.
    """
    # FAILED → RETRY
    transition(session, str(post.id), PostState.RETRY)

    delay = next_retry_delay(post)
    post.retry_count += 1
    post.scheduled_at = datetime.now(timezone.utc) + delay

    # RETRY → QUEUED
    transition(session, str(post.id), PostState.QUEUED)

    return post.scheduled_at


def send_to_dead_letter(session: Session, post: Post) -> Post:
    """Move a FAILED post to DEAD_LETTER (terminal failure).

    Returns the updated post.
    """
    return transition(
        session,
        str(post.id),
        PostState.DEAD_LETTER,
        error_detail={"reason": "max retries exceeded", "retry_count": post.retry_count},
    )
