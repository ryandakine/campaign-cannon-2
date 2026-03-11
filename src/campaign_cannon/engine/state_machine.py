"""Post state machine with optimistic locking.

Defines the allowed transition graph, ``transition()`` for normal
state changes with version checks, and ``force_transition()`` for
admin overrides.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from campaign_cannon.db.models import Post, PostLog, PostState


# ── Exceptions ─────────────────────────────────────────────────────────


class StateError(Exception):
    """Base exception for state-machine errors."""


class InvalidTransitionError(StateError):
    """Raised when a transition is not allowed by the state graph."""


class ConflictError(StateError):
    """Raised when the optimistic-lock version does not match."""


# ── Transition graph ───────────────────────────────────────────────────

ALLOWED_TRANSITIONS: dict[PostState, list[PostState]] = {
    PostState.DRAFT: [PostState.SCHEDULED],
    PostState.SCHEDULED: [PostState.QUEUED],
    PostState.QUEUED: [PostState.PUBLISHING],
    PostState.PUBLISHING: [PostState.POSTED, PostState.FAILED],
    PostState.FAILED: [PostState.RETRY, PostState.DEAD_LETTER],
    PostState.RETRY: [PostState.QUEUED],
    PostState.POSTED: [],
    PostState.DEAD_LETTER: [],
}


# ── Public API ─────────────────────────────────────────────────────────


def transition(
    session: Session,
    post_id: str,
    to_state: PostState,
    *,
    expected_version: int | None = None,
    error_detail: dict | None = None,
) -> Post:
    """Transition a post to *to_state* with optimistic locking.

    Parameters
    ----------
    session:
        Active SQLAlchemy session (caller manages transaction).
    post_id:
        UUID of the post to transition.
    to_state:
        Target state.
    expected_version:
        If supplied, the post's current ``version`` must match.
        If ``None``, the version read from the DB is used (still
        incremented atomically).
    error_detail:
        Optional JSON-serialisable error info stored on the post
        and in the audit log entry.

    Returns
    -------
    The updated ``Post`` instance.

    Raises
    ------
    InvalidTransitionError
        If the transition is not allowed by the state graph.
    ConflictError
        If expected_version doesn't match the current version (lost update).
    """
    # SQLite equivalent of SELECT … FOR UPDATE: start an IMMEDIATE transaction
    session.execute(text("BEGIN IMMEDIATE"))

    post: Post | None = session.get(Post, str(post_id))
    if post is None:
        raise StateError(f"Post {post_id} not found")

    # Validate transition
    allowed = ALLOWED_TRANSITIONS.get(post.state, [])
    if to_state not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition from {post.state.value} to {to_state.value}. "
            f"Allowed: {[s.value for s in allowed]}"
        )

    # Optimistic lock check
    if expected_version is not None and post.version != expected_version:
        raise ConflictError(
            f"Version conflict on Post {post_id}: "
            f"expected {expected_version}, found {post.version}"
        )

    from_state = post.state

    # Apply state change
    post.state = to_state
    post.version += 1
    post.updated_at = datetime.now(timezone.utc)
    if error_detail is not None:
        post.error_detail = error_detail

    # Audit log
    log_entry = PostLog(
        post_id=str(post.id),
        from_state=from_state.value,
        to_state=to_state.value,
        error_detail=error_detail,
    )
    session.add(log_entry)
    session.flush()

    return post


def force_transition(
    session: Session,
    post_id: str,
    to_state: PostState,
    reason: str,
) -> Post:
    """Admin override: transition a post to *to_state* regardless of the graph.

    A ``PostLog`` entry is created with the reason stored in metadata.
    """
    session.execute(text("BEGIN IMMEDIATE"))

    post: Post | None = session.get(Post, str(post_id))
    if post is None:
        raise StateError(f"Post {post_id} not found")

    from_state = post.state

    post.state = to_state
    post.version += 1
    post.updated_at = datetime.now(timezone.utc)

    log_entry = PostLog(
        post_id=str(post.id),
        from_state=from_state.value,
        to_state=to_state.value,
        metadata_={"forced": True, "reason": reason},
    )
    session.add(log_entry)
    session.flush()

    return post
