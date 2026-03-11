"""Core publish orchestrator.

``publish_post(post_id)`` is THE function called by the scheduler for every
post.  It implements the full publish pipeline:

    lock → verify state → dedup check → transition to PUBLISHING →
    rate-limit check → adapter.publish() → handle result → log

This function NEVER raises unhandled exceptions.  All failures are logged
and the post is transitioned to FAILED (with optional retry).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)

# Concurrency gate — initialised by init_publisher() from config.
_semaphore: threading.Semaphore | None = None


def init_publisher(max_concurrent: int = 3) -> None:
    """Initialise the publisher's concurrency semaphore.

    Call once at app startup (after reading config).
    """
    global _semaphore
    _semaphore = threading.Semaphore(max_concurrent)
    logger.info("publisher_initialized", max_concurrent=max_concurrent)


def publish_post(post_id: str) -> None:
    """Publish a single post — called by APScheduler.

    This is the top-level entry point.  It acquires a concurrency semaphore
    slot, opens a DB session with BEGIN IMMEDIATE, and runs the full
    publish pipeline.  All exceptions are caught and logged.

    Args:
        post_id: UUID string of the Post to publish.
    """
    global _semaphore
    if _semaphore is None:
        init_publisher()
    assert _semaphore is not None

    log = logger.bind(post_id=post_id)
    log.info("publish_start")

    if not _semaphore.acquire(timeout=30):
        log.warning("publish_semaphore_timeout")
        return

    try:
        _do_publish(post_id, log)
    except Exception:
        log.exception("publish_unhandled_error")
    finally:
        _semaphore.release()


def _do_publish(post_id: str, log) -> None:
    """Inner publish logic — runs inside the semaphore."""
    from campaign_cannon.adapters.registry import get_adapter
    from campaign_cannon.config.credentials import decrypt_credentials, get_credential
    from campaign_cannon.db.connection import get_session
    from campaign_cannon.db.models import Post, PostLog, PostState
    from campaign_cannon.engine.dedup import check_duplicate, detect_content_duplicate
    from campaign_cannon.engine.rate_limiter import get_rate_limiter
    from campaign_cannon.engine.retry import schedule_retry, send_to_dead_letter, should_retry
    from campaign_cannon.engine.state_machine import (
        ConflictError,
        InvalidTransitionError,
        transition,
    )

    session: Session = get_session()
    try:
        # Use BEGIN IMMEDIATE for row-level locking (SQLite)
        session.execute(sa_text("BEGIN IMMEDIATE"))
    except Exception:
        # If the session doesn't support raw BEGIN (e.g. already in transaction),
        # proceed — the ORM session is still usable.
        pass

    try:
        # 1. Fetch post
        post = session.get(Post, post_id)
        if post is None:
            log.error("publish_post_not_found")
            return

        # 2. Verify state is QUEUED
        if post.state != PostState.QUEUED:
            log.info("publish_skip_wrong_state", state=str(post.state))
            return

        # 3. Idempotency check
        if post.idempotency_key:
            existing = check_duplicate(session, post.idempotency_key)
            if existing and existing.id != post.id and existing.platform_post_id:
                log.info(
                    "publish_skip_duplicate",
                    existing_post_id=str(existing.id),
                    platform_post_id=existing.platform_post_id,
                )
                return

        # 3b. Content duplicate warning (advisory only)
        if post.body:
            dupes = detect_content_duplicate(
                session,
                platform=str(post.platform),
                body_text=post.body,
            )
            # Exclude self
            dupes = [d for d in dupes if d.id != post.id]
            if dupes:
                log.warning(
                    "publish_content_duplicate_warning",
                    duplicate_ids=[str(d.id) for d in dupes],
                )

        # 4. Transition QUEUED → PUBLISHING
        try:
            transition(session, post, PostState.PUBLISHING)
        except (InvalidTransitionError, ConflictError) as exc:
            log.warning("publish_transition_failed", error=str(exc))
            return

        session.commit()

        # 5. Rate limit check
        platform_key = post.platform.value if hasattr(post.platform, "value") else str(post.platform)
        limiter = get_rate_limiter(platform_key)
        if not limiter.acquire():
            wait = limiter.wait_time()
            log.info("publish_rate_limited", wait_seconds=round(wait, 1))
            # Revert to QUEUED so the scheduler can retry later
            try:
                transition(session, post, PostState.QUEUED)
                session.commit()
            except Exception:
                log.exception("publish_rate_limit_revert_failed")
                session.rollback()
            # The scheduler will pick this up again on next run
            return

        # 6. Get adapter + credentials
        try:
            cred = get_credential(session, platform_key)
            decrypted = decrypt_credentials(cred)
            adapter = get_adapter(platform_key, decrypted)
        except Exception as exc:
            log.error("publish_adapter_init_failed", error=str(exc))
            _transition_to_failed(session, post, str(exc), log)
            return

        # 7. Publish!
        media_assets = list(post.media_assets) if hasattr(post, "media_assets") else []
        result = adapter.publish(post, media_assets)

        # 8. Save rate limiter state
        try:
            limiter.save_state(session)
        except Exception:
            log.warning("publish_rate_limit_save_failed")

        # 9. Handle result
        if result.success:
            post.platform_post_id = result.platform_post_id
            post.platform_post_url = result.platform_post_url
            post.published_at = datetime.now(timezone.utc)
            try:
                transition(session, post, PostState.POSTED)
            except (InvalidTransitionError, ConflictError) as exc:
                log.error("publish_success_transition_failed", error=str(exc))

            _log_event(
                session,
                post,
                from_state=PostState.PUBLISHING,
                to_state=PostState.POSTED,
                metadata={
                    "platform_post_id": result.platform_post_id,
                    "platform_post_url": result.platform_post_url,
                },
            )
            session.commit()
            log.info(
                "publish_success",
                platform_post_id=result.platform_post_id,
                url=result.platform_post_url,
            )
        else:
            # Failure path
            error_detail = {
                "error_code": result.error_code,
                "error_message": result.error_message,
                "retryable": result.retryable,
            }
            post.error_detail = error_detail

            try:
                transition(session, post, PostState.FAILED)
            except (InvalidTransitionError, ConflictError):
                log.exception("publish_fail_transition_failed")

            _log_event(
                session,
                post,
                from_state=PostState.PUBLISHING,
                to_state=PostState.FAILED,
                error_detail=result.error_message,
                metadata=error_detail,
            )
            session.commit()

            # Retry logic
            if result.retryable and should_retry(post):
                log.info(
                    "publish_scheduling_retry",
                    retry_count=post.retry_count,
                )
                schedule_retry(session, post)
                session.commit()
            elif not result.retryable or not should_retry(post):
                log.warning("publish_dead_letter", error=result.error_message)
                send_to_dead_letter(session, post)
                session.commit()

            log.warning(
                "publish_failed",
                error_code=result.error_code,
                error_message=result.error_message,
                retryable=result.retryable,
            )

    except Exception:
        log.exception("publish_pipeline_error")
        session.rollback()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _transition_to_failed(session, post, error_msg: str, log) -> None:
    """Move post to FAILED state with error details."""
    from campaign_cannon.db.models import PostState
    from campaign_cannon.engine.state_machine import transition

    try:
        post.error_detail = {"error_message": error_msg}
        transition(session, post, PostState.FAILED)
        _log_event(
            session,
            post,
            from_state=PostState.PUBLISHING,
            to_state=PostState.FAILED,
            error_detail=error_msg,
        )
        session.commit()
    except Exception:
        log.exception("publish_transition_to_failed_error")
        session.rollback()


def _log_event(
    session,
    post,
    from_state,
    to_state,
    error_detail: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Write a PostLog audit entry."""
    from campaign_cannon.db.models import PostLog

    entry = PostLog(
        post_id=post.id,
        from_state=from_state,
        to_state=to_state,
        timestamp=datetime.now(timezone.utc),
        error_detail=error_detail,
        metadata=metadata or {},
    )
    session.add(entry)


# Need sqlalchemy.text for raw SQL
from sqlalchemy import text as sa_text  # noqa: E402
