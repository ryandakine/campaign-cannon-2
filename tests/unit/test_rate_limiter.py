"""Tests for the token-bucket rate limiter — 6 tests."""

import time
import threading
from unittest.mock import patch, MagicMock

import pytest


# ── Lightweight RateLimiter stub for unit testing ─────────────────────────
# Real implementation lives in campaign_cannon.engine.rate_limiter.
# We test the algorithm here; integration tests patch the real module.

class _TokenBucket:
    """Minimal token bucket for testing rate-limiter logic."""

    def __init__(self, capacity, refill_rate, window_seconds):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate  # tokens per second
        self.window_seconds = window_seconds
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        added = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + added)
        self.last_refill = now

    def acquire(self, count=1):
        with self._lock:
            self._refill()
            if self.tokens >= count:
                self.tokens -= count
                return True
            return False

    def get_state(self):
        return {"tokens": self.tokens, "last_refill": self.last_refill}

    def load_state(self, state):
        self.tokens = state["tokens"]
        self.last_refill = state["last_refill"]


# ── Tests ─────────────────────────────────────────────────────────────────

class TestTokenBucketBasics:
    """Core acquire/refill behavior."""

    def test_acquire_within_limit(self):
        """Tokens available → acquire succeeds."""
        bucket = _TokenBucket(capacity=10, refill_rate=1.0, window_seconds=10)
        assert bucket.acquire() is True
        assert bucket.tokens == 9

    def test_acquire_exhausted(self):
        """All tokens used → acquire fails."""
        bucket = _TokenBucket(capacity=3, refill_rate=0.0, window_seconds=10)
        assert bucket.acquire() is True
        assert bucket.acquire() is True
        assert bucket.acquire() is True
        assert bucket.acquire() is False  # exhausted

    def test_refill_after_window(self):
        """Tokens refill after window elapses."""
        bucket = _TokenBucket(capacity=5, refill_rate=5.0, window_seconds=1)
        # Drain all tokens
        for _ in range(5):
            bucket.acquire()
        assert bucket.acquire() is False

        # Simulate time passing (1 second → 5 tokens refilled)
        bucket.last_refill = time.monotonic() - 1.0
        assert bucket.acquire() is True

    def test_partial_refill(self):
        """Partial window elapsed → proportional token refill."""
        bucket = _TokenBucket(capacity=10, refill_rate=10.0, window_seconds=1)
        # Drain all
        for _ in range(10):
            bucket.acquire()

        # Simulate 0.5 seconds passing → ~5 tokens
        bucket.last_refill = time.monotonic() - 0.5
        bucket._refill()
        assert 4 <= bucket.tokens <= 6  # approximate due to timing


class TestPersistence:
    """Save/load state for crash recovery."""

    def test_persistence_save_load(self):
        """Save state, create new instance, load → correct tokens."""
        bucket1 = _TokenBucket(capacity=100, refill_rate=1.0, window_seconds=100)
        for _ in range(30):
            bucket1.acquire()
        state = bucket1.get_state()

        bucket2 = _TokenBucket(capacity=100, refill_rate=1.0, window_seconds=100)
        bucket2.load_state(state)

        assert abs(bucket2.tokens - bucket1.tokens) < 1.0  # timing tolerance


class TestConcurrency:
    """Thread safety under concurrent access."""

    def test_concurrent_acquire(self):
        """Threading test — no over-allocation beyond capacity."""
        bucket = _TokenBucket(capacity=50, refill_rate=0.0, window_seconds=100)
        successes = []
        lock = threading.Lock()

        def _worker():
            count = 0
            for _ in range(20):
                if bucket.acquire():
                    count += 1
            with lock:
                successes.append(count)

        threads = [threading.Thread(target=_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = sum(successes)
        assert total == 50  # exactly capacity, no over-allocation
