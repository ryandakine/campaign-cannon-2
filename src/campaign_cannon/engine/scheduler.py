"""APScheduler-based campaign scheduler with SQLite job store.

Manages the lifecycle of scheduled publish jobs:
- ``start_scheduler()`` / ``shutdown_scheduler()`` — app startup / shutdown
- ``schedule_campaign()`` — queue all SCHEDULED posts for a campaign
- ``pause_campaign()`` / ``resume_campaign()`` — remove / re-create jobs
- ``get_upcoming_jobs()`` — inspect the queue

The scheduler uses a separate SQLite database for its job store so that
APScheduler's internal schema doesn't interfere with the application DB.
"""

from __future__ import annotations

import atexit
import signal
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED  # type: ignore[import-untyped]
from apscheduler.executors.pool import ThreadPoolExecutor  # type: ignore[import-untyped]
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore  # type: ignore[import-untyped]
from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level scheduler singleton
# ---------------------------------------------------------------------------

_scheduler: BackgroundScheduler | None = None
_shutdown_event = threading.Event()


def _job_prefix(campaign_id: str) -> str:
    """Standard prefix for APScheduler job IDs belonging to a campaign."""
    return f"campaign:{campaign_id}:post:"


def _job_id(campaign_id: str, post_id: str) -> str:
    """Deterministic job ID for a post within a campaign."""
    return f"{_job_prefix(campaign_id)}{post_id}"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def start_scheduler(
    db_url: str = "sqlite:///data/scheduler_jobs.db",
    misfire_grace_time: int = 300,
    max_workers: int = 3,
) -> BackgroundScheduler:
    """Initialise and start the background scheduler.

    Args:
        db_url: SQLAlchemy URL for the APScheduler job store.
        misfire_grace_time: Seconds after scheduled time that a job is still
                           considered valid (default 300 = 5 min).
        max_workers: Thread pool size for concurrent job execution.

    Returns:
        The running BackgroundScheduler instance.
    """
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.warning("scheduler_already_running")
        return _scheduler

    jobstores = {
        "default": SQLAlchemyJobStore(url=db_url),
    }
    executors = {
        "default": ThreadPoolExecutor(max_workers=max_workers),
    }
    job_defaults = {
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": misfire_grace_time,
    }

    _scheduler = BackgroundScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
        timezone="UTC",
    )

    # Listen for missed / errored jobs
    _scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
    _scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)

    _scheduler.start(paused=False)
    atexit.register(lambda: shutdown_scheduler(wait=True))

    # Register SIGTERM for graceful shutdown
    try:
        signal.signal(signal.SIGTERM, _sigterm_handler)
    except (ValueError, OSError):
        # Can't set signal handler outside main thread — that's fine.
        pass

    logger.info(
        "scheduler_started",
        db_url=db_url,
        misfire_grace_time=misfire_grace_time,
        max_workers=max_workers,
    )
    return _scheduler


def shutdown_scheduler(wait: bool = True) -> None:
    """Gracefully shut down the scheduler.

    Args:
        wait: If True, wait for in-flight jobs to finish.
    """
    global _scheduler
    if _scheduler is None or not _scheduler.running:
        return

    logger.info("scheduler_shutting_down", wait=wait)
    _scheduler.shutdown(wait=wait)
    _shutdown_event.set()
    logger.info("scheduler_stopped")


def get_scheduler() -> BackgroundScheduler | None:
    """Return the current scheduler instance (may be None if not started)."""
    return _scheduler


# ---------------------------------------------------------------------------
# Campaign operations
# ---------------------------------------------------------------------------


def schedule_campaign(session: Session, campaign_id: str) -> int:
    """Schedule all SCHEDULED posts for a campaign.

    Fetches posts in SCHEDULED state, creates one APScheduler job per post
    at its ``scheduled_at`` time, and transitions each post to QUEUED.

    Args:
        session: Active SQLAlchemy session.
        campaign_id: UUID string of the campaign.

    Returns:
        Number of jobs scheduled.
    """
    from campaign_cannon.db.models import Post, PostState
    from campaign_cannon.engine.state_machine import transition

    _ensure_running()

    posts = (
        session.query(Post)
        .filter(
            Post.campaign_id == campaign_id,
            Post.state == PostState.SCHEDULED,
        )
        .order_by(Post.scheduled_at)
        .all()
    )

    count = 0
    for post in posts:
        run_date = post.scheduled_at
        if run_date is None:
            logger.warning(
                "scheduler_skip_no_date",
                post_id=str(post.id),
                campaign_id=campaign_id,
            )
            continue

        # Ensure the run_date is timezone-aware (UTC)
        if run_date.tzinfo is None:
            run_date = run_date.replace(tzinfo=timezone.utc)

        job_id = _job_id(campaign_id, str(post.id))

        _scheduler.add_job(  # type: ignore[union-attr]
            func="campaign_cannon.engine.publisher:publish_post",
            trigger="date",
            run_date=run_date,
            id=job_id,
            args=[str(post.id)],
            replace_existing=True,
            name=f"publish:{post.platform}:{str(post.id)[:8]}",
        )

        # Transition SCHEDULED → QUEUED
        try:
            transition(session, post, PostState.QUEUED)
        except Exception:
            logger.exception(
                "scheduler_transition_failed",
                post_id=str(post.id),
            )
            continue

        count += 1

    session.commit()
    logger.info(
        "campaign_scheduled",
        campaign_id=campaign_id,
        jobs_created=count,
    )
    return count


def pause_campaign(session: Session, campaign_id: str) -> int:
    """Remove all APScheduler jobs for a campaign's pending posts.

    Does NOT change post states — they stay QUEUED in the DB so that
    ``resume_campaign()`` can re-create the jobs.

    Args:
        session: Active SQLAlchemy session.
        campaign_id: UUID string of the campaign.

    Returns:
        Number of jobs removed.
    """
    from campaign_cannon.db.models import Post, PostState

    _ensure_running()

    posts = (
        session.query(Post)
        .filter(
            Post.campaign_id == campaign_id,
            Post.state == PostState.QUEUED,
        )
        .all()
    )

    count = 0
    for post in posts:
        job_id = _job_id(campaign_id, str(post.id))
        try:
            _scheduler.remove_job(job_id)  # type: ignore[union-attr]
            count += 1
        except Exception:
            # Job may have already fired or been removed
            logger.debug("scheduler_job_not_found", job_id=job_id)

    logger.info(
        "campaign_paused",
        campaign_id=campaign_id,
        jobs_removed=count,
    )
    return count


def resume_campaign(session: Session, campaign_id: str) -> int:
    """Re-create scheduler jobs for all QUEUED posts in a campaign.

    Args:
        session: Active SQLAlchemy session.
        campaign_id: UUID string of the campaign.

    Returns:
        Number of jobs re-scheduled.
    """
    from campaign_cannon.db.models import Post, PostState

    _ensure_running()

    posts = (
        session.query(Post)
        .filter(
            Post.campaign_id == campaign_id,
            Post.state == PostState.QUEUED,
        )
        .order_by(Post.scheduled_at)
        .all()
    )

    count = 0
    now = datetime.now(timezone.utc)
    for post in posts:
        run_date = post.scheduled_at
        if run_date is None:
            continue

        if run_date.tzinfo is None:
            run_date = run_date.replace(tzinfo=timezone.utc)

        # If the scheduled time is in the past, run immediately
        if run_date < now:
            run_date = now

        job_id = _job_id(campaign_id, str(post.id))

        _scheduler.add_job(  # type: ignore[union-attr]
            func="campaign_cannon.engine.publisher:publish_post",
            trigger="date",
            run_date=run_date,
            id=job_id,
            args=[str(post.id)],
            replace_existing=True,
            name=f"publish:{post.platform}:{str(post.id)[:8]}",
        )
        count += 1

    logger.info(
        "campaign_resumed",
        campaign_id=campaign_id,
        jobs_rescheduled=count,
    )
    return count


def get_upcoming_jobs(limit: int = 5) -> list[dict[str, Any]]:
    """Return the next *limit* pending jobs with their scheduled times.

    Returns:
        List of dicts with keys: id, name, run_date, args.
    """
    if _scheduler is None or not _scheduler.running:
        return []

    jobs = _scheduler.get_jobs()
    # Sort by next_run_time and take the first N
    pending = [
        j for j in jobs
        if j.next_run_time is not None
    ]
    pending.sort(key=lambda j: j.next_run_time)

    return [
        {
            "id": j.id,
            "name": j.name,
            "run_date": j.next_run_time.isoformat() if j.next_run_time else None,
            "args": list(j.args) if j.args else [],
        }
        for j in pending[:limit]
    ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_running() -> None:
    """Raise if the scheduler hasn't been started."""
    if _scheduler is None or not _scheduler.running:
        raise RuntimeError(
            "Scheduler is not running. Call start_scheduler() first."
        )


def _sigterm_handler(signum: int, frame: Any) -> None:
    """Handle SIGTERM by signalling a graceful shutdown."""
    logger.info("scheduler_sigterm_received")
    _shutdown_event.set()
    shutdown_scheduler(wait=True)


def _on_job_error(event) -> None:
    """Log APScheduler job execution errors."""
    logger.error(
        "scheduler_job_error",
        job_id=event.job_id,
        exception=str(event.exception),
    )


def _on_job_missed(event) -> None:
    """Log APScheduler missed jobs (beyond misfire_grace_time)."""
    logger.warning(
        "scheduler_job_missed",
        job_id=event.job_id,
        scheduled_run_time=str(event.scheduled_run_time),
    )
