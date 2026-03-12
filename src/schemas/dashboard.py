"""Pydantic schemas for dashboard API."""

from __future__ import annotations

from pydantic import BaseModel


class DashboardSummary(BaseModel):
    total: int
    by_status: dict[str, int]


class RateLimitStatus(BaseModel):
    platform: str
    calls_made: int
    calls_limit: int
    remaining: int
    window_duration_sec: int
    headroom_pct: float
