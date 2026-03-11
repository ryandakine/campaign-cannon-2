"""Stuck-post recovery job.

Finds posts that have been stuck in PUBLISHING for longer than the
configured timeout and resets them to QUEUED so they can be retried.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from campaign_cannon.config.settings import get_settings
from campaign_cannon.db.models import Post, PostState
from campaign_cannon.engine.state_machine import force_transition


def recover_stuck_posts(
    session: Session,
    timeout_seconds: int | None = None,
) -> int:
    """Reset posts stuck in PUBLISHING back to QUEUED.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    timeout_seconds:
        How long a post may stay in PUBLISHING before being considered
        stuck. Defaults to ``settings.stuck_post_timeout`` (300 s).

    Returns
    -------
    Number of posts recovered.
    """
    if timeout_seconds is None:
        timeout_seconds = get_settings().stuck_post_timeout

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)

    stuck_posts: list[Post] = (
        session.query(Post)
        .filter(
            Post.state == PostState.PUBLISHING,
            Post.updated_at < cutoff,
        )
        .all()
    )

    recovered = 0
    for post in stuck_posts:
        force_transition(
            session,
            str(post.id),
            PostState.QUEUED,
            reason=f"auto-recovery: stuck in PUBLISHING for >{timeout_seconds}s",
        )
        recovered += 1

    return recovered
