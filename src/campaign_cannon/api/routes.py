"""REST API routes for Campaign Cannon v3.1 — all endpoints under /api/v1."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from campaign_cannon.api.errors import (
    CampaignNotFoundError,
    DuplicateError,
    InvalidStateError,
    PostNotFoundError,
)
from campaign_cannon.api.schemas import (
    CampaignActivateResponse,
    CampaignImportRequest,
    CampaignImportResponse,
    CampaignListItem,
    CampaignListResponse,
    CampaignStatusResponse,
    DryRunResponse,
    ForceTransitionRequest,
    ForceTransitionResponse,
    HealthResponse,
    PauseResumeResponse,
    PostSummary,
)
from campaign_cannon.db.connection import get_session
from campaign_cannon.db.models import Campaign, CampaignStatus, Post, PostState
from campaign_cannon.engine.scheduler import (
    get_upcoming_jobs,
    pause_campaign,
    resume_campaign,
    schedule_campaign,
)
from campaign_cannon.engine.state_machine import transition
from campaign_cannon.import_.json_import import import_campaign

logger = structlog.get_logger("campaign_cannon.api.routes")

router = APIRouter(prefix="/api/v1", tags=["campaigns"])


# ── Helpers ─────────────────────────────────────────────────────────────────


def _get_campaign(session, campaign_id: UUID) -> Campaign:
    """Fetch a campaign by ID or raise CampaignNotFoundError."""
    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        raise CampaignNotFoundError(campaign_id)
    return campaign


def _get_post(session, post_id: UUID) -> Post:
    """Fetch a post by ID or raise PostNotFoundError."""
    post = session.get(Post, post_id)
    if post is None:
        raise PostNotFoundError(post_id)
    return post


def _build_post_summary(post: Post) -> PostSummary:
    """Build a PostSummary from a Post ORM object."""
    return PostSummary(
        id=post.id,
        slug=post.slug,
        platform=post.platform,
        state=post.state,
        scheduled_at=post.scheduled_at,
        published_at=post.published_at,
        platform_post_url=post.platform_post_url,
        error_detail=post.error_detail,
    )


def _build_status_response(campaign: Campaign, posts: list[Post]) -> CampaignStatusResponse:
    """Build a CampaignStatusResponse from a Campaign and its posts."""
    posts_by_state: dict[str, int] = {}
    for post in posts:
        state_name = post.state.value if hasattr(post.state, "value") else str(post.state)
        posts_by_state[state_name] = posts_by_state.get(state_name, 0) + 1

    now = datetime.now(timezone.utc)
    next_scheduled = sorted(
        [p for p in posts if p.state in (PostState.SCHEDULED, PostState.QUEUED)],
        key=lambda p: p.scheduled_at,
    )[:5]
    recently_completed = sorted(
        [p for p in posts if p.state in (PostState.POSTED, PostState.DEAD_LETTER)],
        key=lambda p: (p.published_at or p.updated_at or now),
        reverse=True,
    )[:5]

    return CampaignStatusResponse(
        id=campaign.id,
        name=campaign.name,
        slug=campaign.slug,
        status=campaign.status,
        total_posts=len(posts),
        posts_by_state=posts_by_state,
        next_scheduled=[_build_post_summary(p) for p in next_scheduled],
        recently_completed=[_build_post_summary(p) for p in recently_completed],
        activated_at=campaign.activated_at,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


# ── Campaign Import ────────────────────────────────────────────────────────


@router.post("/campaigns", status_code=201, response_model=CampaignImportResponse)
def create_campaign(
    payload: CampaignImportRequest,
    dry_run: bool = Query(False, description="Preview import without writing to DB"),
) -> CampaignImportResponse | DryRunResponse:
    """Import a new campaign with posts and media assets."""
    with get_session() as session:
        result = import_campaign(session, payload, dry_run=dry_run)
        if dry_run:
            return result  # type: ignore[return-value]
        session.commit()
        logger.info(
            "campaign_imported",
            campaign_id=str(result.campaign_id),
            post_count=result.post_count,
        )
        return result


# ── Campaign Activate ──────────────────────────────────────────────────────


@router.post(
    "/campaigns/{campaign_id}/activate",
    response_model=CampaignActivateResponse,
)
def activate_campaign(campaign_id: UUID) -> CampaignActivateResponse:
    """Activate a DRAFT campaign — schedules all posts via APScheduler."""
    with get_session() as session:
        campaign = _get_campaign(session, campaign_id)
        if campaign.status != CampaignStatus.DRAFT:
            raise InvalidStateError(
                f"Campaign must be in DRAFT status to activate (current: {campaign.status.value})"
            )

        schedule_campaign(session, campaign)
        campaign.status = CampaignStatus.ACTIVE
        campaign.activated_at = datetime.now(timezone.utc)
        session.commit()

        posts = list(
            session.execute(
                select(Post).where(Post.campaign_id == campaign_id)
            ).scalars()
        )
        scheduled_posts = [
            p for p in posts if p.state in (PostState.SCHEDULED, PostState.QUEUED)
        ]
        next_post_at = (
            min(p.scheduled_at for p in scheduled_posts) if scheduled_posts else None
        )

        logger.info("campaign_activated", campaign_id=str(campaign_id))
        return CampaignActivateResponse(
            campaign_id=campaign.id,
            status="ACTIVE",
            posts_scheduled=len(scheduled_posts),
            next_post_at=next_post_at,
        )


# ── Campaign Status ────────────────────────────────────────────────────────


@router.get(
    "/campaigns/{campaign_id}/status",
    response_model=CampaignStatusResponse,
)
def get_campaign_status(campaign_id: UUID) -> CampaignStatusResponse:
    """Get current campaign status with post breakdown."""
    with get_session() as session:
        campaign = _get_campaign(session, campaign_id)
        posts = list(
            session.execute(
                select(Post).where(Post.campaign_id == campaign_id)
            ).scalars()
        )
        return _build_status_response(campaign, posts)


# ── Campaign Pause ─────────────────────────────────────────────────────────


@router.post(
    "/campaigns/{campaign_id}/pause",
    response_model=PauseResumeResponse,
)
def pause_campaign_endpoint(campaign_id: UUID) -> PauseResumeResponse:
    """Pause an ACTIVE campaign — removes scheduler jobs, keeps DB state."""
    with get_session() as session:
        campaign = _get_campaign(session, campaign_id)
        if campaign.status != CampaignStatus.ACTIVE:
            raise InvalidStateError(
                f"Campaign must be ACTIVE to pause (current: {campaign.status.value})"
            )

        pause_campaign(session, campaign)
        campaign.status = CampaignStatus.PAUSED
        session.commit()

        logger.info("campaign_paused", campaign_id=str(campaign_id))
        return PauseResumeResponse(
            campaign_id=campaign.id,
            status=CampaignStatus.PAUSED,
            message="Campaign paused. Scheduled jobs removed. Use /resume to re-schedule.",
        )


# ── Campaign Resume ────────────────────────────────────────────────────────


@router.post(
    "/campaigns/{campaign_id}/resume",
    response_model=PauseResumeResponse,
)
def resume_campaign_endpoint(campaign_id: UUID) -> PauseResumeResponse:
    """Resume a PAUSED campaign — re-creates scheduler jobs."""
    with get_session() as session:
        campaign = _get_campaign(session, campaign_id)
        if campaign.status != CampaignStatus.PAUSED:
            raise InvalidStateError(
                f"Campaign must be PAUSED to resume (current: {campaign.status.value})"
            )

        resume_campaign(session, campaign)
        campaign.status = CampaignStatus.ACTIVE
        session.commit()

        logger.info("campaign_resumed", campaign_id=str(campaign_id))
        return PauseResumeResponse(
            campaign_id=campaign.id,
            status=CampaignStatus.ACTIVE,
            message="Campaign resumed. Scheduled jobs re-created.",
        )


# ── List Campaigns ─────────────────────────────────────────────────────────


@router.get("/campaigns", response_model=CampaignListResponse)
def list_campaigns(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: CampaignStatus | None = Query(None, description="Filter by campaign status"),
) -> CampaignListResponse:
    """List all campaigns with optional filtering and pagination."""
    with get_session() as session:
        query = select(Campaign)
        count_query = select(func.count(Campaign.id))

        if status is not None:
            query = query.where(Campaign.status == status)
            count_query = count_query.where(Campaign.status == status)

        # Exclude soft-deleted campaigns
        query = query.where(Campaign.status != CampaignStatus.ARCHIVED)
        count_query = count_query.where(Campaign.status != CampaignStatus.ARCHIVED)

        total = session.execute(count_query).scalar() or 0
        campaigns = list(
            session.execute(
                query.order_by(Campaign.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).scalars()
        )

        items = []
        for c in campaigns:
            post_count = (
                session.execute(
                    select(func.count(Post.id)).where(Post.campaign_id == c.id)
                ).scalar()
                or 0
            )
            items.append(
                CampaignListItem(
                    id=c.id,
                    name=c.name,
                    slug=c.slug,
                    status=c.status,
                    total_posts=post_count,
                    created_at=c.created_at,
                    activated_at=c.activated_at,
                )
            )

        return CampaignListResponse(
            campaigns=items,
            total=total,
            page=page,
            page_size=page_size,
        )


# ── List Posts for Campaign ────────────────────────────────────────────────


@router.get("/campaigns/{campaign_id}/posts", response_model=list[PostSummary])
def list_campaign_posts(campaign_id: UUID) -> list[PostSummary]:
    """List all posts for a campaign."""
    with get_session() as session:
        _get_campaign(session, campaign_id)  # ensure campaign exists
        posts = list(
            session.execute(
                select(Post)
                .where(Post.campaign_id == campaign_id)
                .order_by(Post.scheduled_at)
            ).scalars()
        )
        return [_build_post_summary(p) for p in posts]


# ── Export Campaign ────────────────────────────────────────────────────────


@router.get("/campaigns/{campaign_id}/export")
def export_campaign(campaign_id: UUID) -> dict:
    """Export a campaign as re-importable JSON."""
    with get_session() as session:
        campaign = _get_campaign(session, campaign_id)
        posts = list(
            session.execute(
                select(Post)
                .where(Post.campaign_id == campaign_id)
                .order_by(Post.scheduled_at)
            ).scalars()
        )

        return {
            "name": campaign.name,
            "slug": campaign.slug,
            "description": campaign.description,
            "metadata": campaign.metadata,
            "posts": [
                {
                    "slug": p.slug,
                    "platform": p.platform.value if hasattr(p.platform, "value") else p.platform,
                    "title": p.title,
                    "body": p.body,
                    "scheduled_at": p.scheduled_at.isoformat(),
                    "subreddit": getattr(p, "subreddit", None),
                    "metadata": p.metadata,
                    "media_paths": [
                        asset.original_path
                        for asset in getattr(p, "media_assets", [])
                    ],
                }
                for p in posts
            ],
        }


# ── Delete Campaign ────────────────────────────────────────────────────────


@router.delete("/campaigns/{campaign_id}", status_code=200)
def delete_campaign(campaign_id: UUID) -> dict:
    """Soft-delete a campaign (set status to ARCHIVED, cancel pending jobs)."""
    with get_session() as session:
        campaign = _get_campaign(session, campaign_id)
        if campaign.status == CampaignStatus.ARCHIVED:
            raise InvalidStateError("Campaign is already archived")

        # Cancel pending scheduler jobs if active
        if campaign.status == CampaignStatus.ACTIVE:
            pause_campaign(session, campaign)

        campaign.status = CampaignStatus.ARCHIVED
        session.commit()

        logger.info("campaign_deleted", campaign_id=str(campaign_id))
        return {"campaign_id": str(campaign_id), "status": "ARCHIVED", "message": "Campaign archived"}


# ── Force Transition ───────────────────────────────────────────────────────


@router.post(
    "/campaigns/{campaign_id}/posts/{post_id}/force-transition",
    response_model=ForceTransitionResponse,
)
def force_transition(
    campaign_id: UUID,
    post_id: UUID,
    body: ForceTransitionRequest,
) -> ForceTransitionResponse:
    """Admin override: force a post to a specific state."""
    with get_session() as session:
        _get_campaign(session, campaign_id)  # ensure campaign exists
        post = _get_post(session, post_id)

        if post.campaign_id != campaign_id:
            raise PostNotFoundError(post_id)

        previous_state = post.state
        transition(session, post, body.target_state, reason=body.reason, force=True)
        session.commit()

        logger.warning(
            "force_transition",
            post_id=str(post_id),
            from_state=previous_state.value,
            to_state=body.target_state.value,
            reason=body.reason,
        )
        return ForceTransitionResponse(
            post_id=post.id,
            previous_state=previous_state,
            new_state=body.target_state,
            reason=body.reason,
        )


# ── Health Check ───────────────────────────────────────────────────────────


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health_check() -> HealthResponse:
    """System health: scheduler status, uptime, next scheduled jobs."""
    import time

    from campaign_cannon.api.app import _startup_time

    uptime = time.time() - _startup_time if _startup_time else 0.0

    try:
        upcoming = get_upcoming_jobs(limit=5)
        scheduler_running = True
    except Exception:
        upcoming = []
        scheduler_running = False

    return HealthResponse(
        status="ok",
        version="3.1.0",
        uptime_seconds=round(uptime, 2),
        scheduler_running=scheduler_running,
        next_jobs=upcoming,
    )
