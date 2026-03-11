"""Pydantic v2 request/response schemas for Campaign Cannon REST API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from campaign_cannon.db.models import CampaignStatus, Platform, PostState


# ── Request Models ──────────────────────────────────────────────────────────


class PostImport(BaseModel):
    """Single post within a campaign import request."""

    slug: str = Field(..., description="Unique post identifier within campaign")
    platform: Platform
    title: str | None = Field(None, description="Post title (required for Reddit)")
    body: str = Field(..., description="Post content text")
    scheduled_at: datetime = Field(..., description="ISO 8601 datetime with timezone")
    media_paths: list[str] = Field(default_factory=list, description="Local file paths for media")
    subreddit: str | None = Field(None, description="Target subreddit (Reddit only)")
    metadata: dict | None = None


class CampaignImportRequest(BaseModel):
    """Full campaign import payload."""

    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]*$", max_length=100)
    description: str | None = None
    posts: list[PostImport] = Field(..., min_length=1)
    media_base_path: str | None = Field(
        None, description="Base path for resolving relative media_paths"
    )
    metadata: dict | None = None


class ForceTransitionRequest(BaseModel):
    """Admin override to force a post state transition."""

    target_state: PostState
    reason: str = Field(..., min_length=1, max_length=500)


# ── Response Models ─────────────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    """Standard error response body."""

    error: str
    detail: str | None = None
    field_errors: dict[str, list[str]] | None = None


class PostSummary(BaseModel):
    """Abbreviated post info for campaign status responses."""

    id: UUID
    slug: str
    platform: Platform
    state: PostState
    scheduled_at: datetime
    published_at: datetime | None = None
    platform_post_url: str | None = None
    error_detail: dict | None = None


class CampaignImportResponse(BaseModel):
    """Response after importing a campaign."""

    campaign_id: UUID
    name: str
    slug: str
    post_count: int
    warnings: list[str] = Field(default_factory=list)
    dry_run: bool = False


class CampaignActivateResponse(BaseModel):
    """Response after activating a campaign."""

    campaign_id: UUID
    status: str = "ACTIVE"
    posts_scheduled: int
    next_post_at: datetime | None = None


class CampaignStatusResponse(BaseModel):
    """Full campaign status with post breakdown."""

    id: UUID
    name: str
    slug: str
    status: CampaignStatus
    total_posts: int
    posts_by_state: dict[str, int]
    next_scheduled: list[PostSummary]
    recently_completed: list[PostSummary]
    activated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CampaignListItem(BaseModel):
    """Abbreviated campaign info for list endpoint."""

    id: UUID
    name: str
    slug: str
    status: CampaignStatus
    total_posts: int
    created_at: datetime
    activated_at: datetime | None = None


class CampaignListResponse(BaseModel):
    """Paginated list of campaigns."""

    campaigns: list[CampaignListItem]
    total: int
    page: int
    page_size: int


class PauseResumeResponse(BaseModel):
    """Response after pausing or resuming a campaign."""

    campaign_id: UUID
    status: CampaignStatus
    message: str


class ForceTransitionResponse(BaseModel):
    """Response after forcing a post state transition."""

    post_id: UUID
    previous_state: PostState
    new_state: PostState
    reason: str


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str = "3.1.0"
    uptime_seconds: float
    scheduler_running: bool
    next_jobs: list[dict]


class DryRunPostPreview(BaseModel):
    """Preview of a single post during dry-run import."""

    slug: str
    platform: Platform
    scheduled_at: datetime
    body_length: int
    media_count: int
    idempotency_key: str


class DryRunResponse(BaseModel):
    """Response for dry-run campaign import."""

    valid: bool
    name: str
    slug: str
    post_count: int
    posts: list[DryRunPostPreview]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
