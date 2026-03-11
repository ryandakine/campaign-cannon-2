"""Token-bucket rate limiter with per-platform DB persistence.

Each platform has its own token bucket configured from config.toml.
Tokens are refilled at a steady rate and persisted to SQLite so limits
survive restarts.  The publisher checks acquire() before every publish
and uses wait_time() to schedule backpressure delays.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
import structlog
from sqlalchemy.orm import Mapped, mapped_column

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# SQLAlchemy model for persisting rate limit state
# ---------------------------------------------------------------------------
# Intentionally defined here rather than in db/models.py because this table
# is owned entirely by the rate limiter module and Agent 1 does not need to
# know about it.  At migration time, Alembic will discover it through the
# shared Base metadata.

from sqlalchemy.orm import DeclarativeBase


class _RateLimitBase(DeclarativeBase):
    """Separate declarative base for the rate limit state table.

    During integration the team may fold this into the shared Base.  Using
    a private base keeps Phase 2 self-contained while Agent 1 works in
    parallel.
    """

    pass


class RateLimitState(_RateLimitBase):
    """Persisted token bucket state per platform."""

    __tablename__ = "rate_limit_states"

    platform: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    remaining_tokens: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    last_refill_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    window_seconds: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    max_tokens: Mapped[int] = mapped_column(sa.Integer, nullable=False)


# ---------------------------------------------------------------------------
# Token-bucket implementation
# ---------------------------------------------------------------------------

class RateLimiter:
    """In-memory token bucket with DB persistence.

    Thread-safe via a threading.Lock.  Call save_state() periodically
    (the publisher does this after every publish) and load_state() on
    startup.
    """

    def __init__(
        self,
        platform: str,
        max_tokens: int,
        window_seconds: int,
    ) -> None:
        self._platform = platform
        self._max_tokens = max_tokens
        self._window_seconds = window_seconds
        self._tokens = float(max_tokens)
        self._last_refill = time.monotonic()
        self._last_refill_utc = datetime.now(timezone.utc)
        self._lock = threading.Lock()

    # -- public API ----------------------------------------------------------

    @property
    def platform(self) -> str:
        return self._platform

    def acquire(self, count: int = 1) -> bool:
        """Try to consume *count* tokens.

        Returns True if tokens were consumed, False if insufficient.
        """
        with self._lock:
            self._refill()
            if self._tokens >= count:
                self._tokens -= count
                logger.debug(
                    "rate_limit_acquired",
                    platform=self._platform,
                    consumed=count,
                    remaining=int(self._tokens),
                )
                return True
            logger.info(
                "rate_limit_exhausted",
                platform=self._platform,
                remaining=int(self._tokens),
                requested=count,
            )
            return False

    def wait_time(self) -> float:
        """Seconds until the next token becomes available."""
        with self._lock:
            self._refill()
            if self._tokens >= 1:
                return 0.0
            refill_rate = self._max_tokens / self._window_seconds
            if refill_rate == 0:
                return float(self._window_seconds)
            return (1.0 - self._tokens) / refill_rate

    def remaining(self) -> int:
        """Current token count (after refill)."""
        with self._lock:
            self._refill()
            return int(self._tokens)

    # -- persistence ---------------------------------------------------------

    def save_state(self, session: Session) -> None:
        """Persist current bucket state to DB."""
        with self._lock:
            self._refill()
            state = session.get(RateLimitState, self._platform)
            if state is None:
                state = RateLimitState(
                    platform=self._platform,
                    remaining_tokens=int(self._tokens),
                    last_refill_at=self._last_refill_utc,
                    window_seconds=self._window_seconds,
                    max_tokens=self._max_tokens,
                )
                session.add(state)
            else:
                state.remaining_tokens = int(self._tokens)
                state.last_refill_at = self._last_refill_utc
                state.window_seconds = self._window_seconds
                state.max_tokens = self._max_tokens
            session.flush()

    def load_state(self, session: Session) -> None:
        """Restore bucket state from DB, applying any refill for elapsed time."""
        state = session.get(RateLimitState, self._platform)
        if state is None:
            logger.info(
                "rate_limit_no_saved_state",
                platform=self._platform,
                max_tokens=self._max_tokens,
            )
            return

        with self._lock:
            elapsed = (
                datetime.now(timezone.utc) - state.last_refill_at
            ).total_seconds()
            refill_rate = state.max_tokens / state.window_seconds
            refilled = state.remaining_tokens + elapsed * refill_rate
            self._tokens = min(refilled, float(self._max_tokens))
            self._last_refill = time.monotonic()
            self._last_refill_utc = datetime.now(timezone.utc)
            self._window_seconds = state.window_seconds
            self._max_tokens = state.max_tokens

        logger.info(
            "rate_limit_restored",
            platform=self._platform,
            tokens=int(self._tokens),
            elapsed_since_save=round(elapsed, 1),
        )

    # -- internals -----------------------------------------------------------

    def _refill(self) -> None:
        """Add tokens based on time elapsed since the last refill.

        Must be called while holding self._lock.
        """
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        refill_rate = self._max_tokens / self._window_seconds
        self._tokens = min(
            self._tokens + elapsed * refill_rate,
            float(self._max_tokens),
        )
        self._last_refill = now
        self._last_refill_utc = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Factory / cache
# ---------------------------------------------------------------------------

# Default rate-limit configs per platform (from config.toml values).
# These are used when get_rate_limiter() is called without explicit overrides.
_DEFAULT_LIMITS: dict[str, tuple[int, int]] = {
    "TWITTER": (300, 10800),       # 300 posts / 3 hours
    "REDDIT": (60, 3600),          # ~1/min → 60 per hour
    "LINKEDIN": (100, 86400),      # 100 posts / day
}

_cache: dict[str, RateLimiter] = {}
_cache_lock = threading.Lock()


def get_rate_limiter(
    platform: str,
    max_tokens: Optional[int] = None,
    window_seconds: Optional[int] = None,
) -> RateLimiter:
    """Get (or create) the cached RateLimiter for *platform*.

    On first call the limiter is created with either the provided limits or
    the built-in defaults.  Subsequent calls for the same platform return the
    cached instance.
    """
    with _cache_lock:
        if platform in _cache:
            return _cache[platform]

        if max_tokens is None or window_seconds is None:
            defaults = _DEFAULT_LIMITS.get(platform, (100, 3600))
            max_tokens = max_tokens or defaults[0]
            window_seconds = window_seconds or defaults[1]

        limiter = RateLimiter(
            platform=platform,
            max_tokens=max_tokens,
            window_seconds=window_seconds,
        )
        _cache[platform] = limiter
        logger.info(
            "rate_limiter_created",
            platform=platform,
            max_tokens=max_tokens,
            window_seconds=window_seconds,
        )
        return limiter


def ensure_table(engine: sa.Engine) -> None:
    """Create the rate_limit_states table if it doesn't exist.

    Call once during application startup.
    """
    _RateLimitBase.metadata.create_all(engine)
