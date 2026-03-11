"""Engine — state machine, retry logic, stuck-post recovery, scheduler, publisher, dedup, rate limiter."""

from campaign_cannon.engine.recovery import recover_stuck_posts
from campaign_cannon.engine.retry import (
    next_retry_delay,
    schedule_retry,
    send_to_dead_letter,
    should_retry,
)
from campaign_cannon.engine.state_machine import (
    ALLOWED_TRANSITIONS,
    ConflictError,
    InvalidTransitionError,
    StateError,
    force_transition,
    transition,
)
from campaign_cannon.engine.dedup import (
    check_duplicate,
    detect_content_duplicate,
    generate_idempotency_key,
)
from campaign_cannon.engine.publisher import init_publisher, publish_post
from campaign_cannon.engine.rate_limiter import RateLimiter, get_rate_limiter
from campaign_cannon.engine.scheduler import (
    get_upcoming_jobs,
    pause_campaign,
    resume_campaign,
    schedule_campaign,
    shutdown_scheduler,
    start_scheduler,
)

__all__ = [
    # Phase 1 — state machine, retry, recovery
    "ALLOWED_TRANSITIONS",
    "ConflictError",
    "InvalidTransitionError",
    "StateError",
    "force_transition",
    "next_retry_delay",
    "recover_stuck_posts",
    "schedule_retry",
    "send_to_dead_letter",
    "should_retry",
    "transition",
    # Phase 2 — scheduler
    "start_scheduler",
    "shutdown_scheduler",
    "schedule_campaign",
    "pause_campaign",
    "resume_campaign",
    "get_upcoming_jobs",
    # Phase 2 — publisher
    "init_publisher",
    "publish_post",
    # Phase 2 — dedup
    "generate_idempotency_key",
    "check_duplicate",
    "detect_content_duplicate",
    # Phase 2 — rate limiter
    "RateLimiter",
    "get_rate_limiter",
]
