"""MCP tool implementations for Campaign Cannon.

Thin wrappers around the same logic used by the REST API routes,
with structured error responses optimized for AI agent consumption.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import UUID

import structlog
from sqlalchemy import select

from campaign_cannon.api.errors import (
    CampaignNotFoundError,
    DuplicateError,
    ImportValidationError,
    InvalidStateError,
)
from campaign_cannon.api.schemas import CampaignImportRequest
from campaign_cannon.db.connection import get_session
from campaign_cannon.db.models import Campaign, CampaignStatus, Post, PostState
from campaign_cannon.engine.scheduler import (
    pause_campaign as _pause_campaign,
    resume_campaign as _resume_campaign,
    schedule_campaign,
)
from campaign_cannon.import_.json_import import import_campaign

logger = structlog.get_logger("campaign_cannon.mcp.tools")


# ── MCP Error Model ────────────────────────────────────────────────────────


@dataclass
class MCPError:
    """Structured error response for MCP tool failures."""

    error_code: str
    message: str
    retryable: bool
    suggestion: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MCPResult:
    """Structured success response for MCP tool results."""

    success: bool
    data: dict
    warnings: list[str] | None = None

    def to_dict(self) -> dict:
        result = {"success": self.success, "data": self.data}
        if self.warnings:
            result["warnings"] = self.warnings
        return result


# ── Tool Implementations ───────────────────────────────────────────────────


def tool_import_campaign(payload: dict) -> dict:
    """Import a campaign from JSON payload.

    Args:
        payload: Dict matching CampaignImportRequest schema.

    Returns:
        MCPResult or MCPError as dict.
    """
    try:
        request = CampaignImportRequest(**payload)
    except Exception as exc:
        return MCPError(
            error_code="VALIDATION_ERROR",
            message=f"Invalid import payload: {exc}",
            retryable=False,
            suggestion="Check required fields: name, slug, posts (with slug, platform, body, scheduled_at)",
        ).to_dict()

    try:
        with get_session() as session:
            result = import_campaign(session, request, dry_run=False)
            session.commit()
            return MCPResult(
                success=True,
                data={
                    "campaign_id": str(result.campaign_id),
                    "name": result.name,
                    "slug": result.slug,
                    "post_count": result.post_count,
                },
                warnings=result.warnings or None,
            ).to_dict()
    except ImportValidationError as exc:
        return MCPError(
            error_code="IMPORT_VALIDATION_FAILED",
            message="; ".join(exc.errors),
            retryable=False,
            suggestion="Fix the validation errors and retry the import",
        ).to_dict()
    except DuplicateError as exc:
        return MCPError(
            error_code="DUPLICATE_CAMPAIGN",
            message=str(exc),
            retryable=False,
            suggestion="Use a different campaign slug, or delete the existing campaign first",
        ).to_dict()
    except Exception as exc:
        logger.exception("mcp_import_error", error=str(exc))
        return MCPError(
            error_code="INTERNAL_ERROR",
            message="Unexpected error during import",
            retryable=True,
            suggestion="Try again in 60 seconds",
        ).to_dict()


def tool_activate_campaign(campaign_id: str) -> dict:
    """Activate a DRAFT campaign to start scheduling posts.

    Args:
        campaign_id: UUID string of the campaign.

    Returns:
        MCPResult or MCPError as dict.
    """
    try:
        cid = UUID(campaign_id)
    except ValueError:
        return MCPError(
            error_code="INVALID_ID",
            message=f"Invalid campaign ID format: {campaign_id!r}",
            retryable=False,
            suggestion="Provide a valid UUID (e.g., from import_campaign result)",
        ).to_dict()

    try:
        with get_session() as session:
            campaign = session.get(Campaign, cid)
            if campaign is None:
                return MCPError(
                    error_code="CAMPAIGN_NOT_FOUND",
                    message=f"Campaign {campaign_id} not found",
                    retryable=False,
                    suggestion="Check the campaign ID or import a new campaign",
                ).to_dict()

            if campaign.status != CampaignStatus.DRAFT:
                return MCPError(
                    error_code="INVALID_STATE",
                    message=f"Campaign is {campaign.status.value}, must be DRAFT to activate",
                    retryable=False,
                    suggestion=(
                        "Use pause_campaign + resume_campaign for ACTIVE campaigns, "
                        "or import a new campaign"
                    ),
                ).to_dict()

            schedule_campaign(session, campaign)
            campaign.status = CampaignStatus.ACTIVE
            campaign.activated_at = datetime.now(timezone.utc)
            session.commit()

            posts = list(
                session.execute(
                    select(Post).where(Post.campaign_id == cid)
                ).scalars()
            )
            scheduled = [p for p in posts if p.state in (PostState.SCHEDULED, PostState.QUEUED)]
            next_at = min(p.scheduled_at for p in scheduled).isoformat() if scheduled else None

            return MCPResult(
                success=True,
                data={
                    "campaign_id": campaign_id,
                    "status": "ACTIVE",
                    "posts_scheduled": len(scheduled),
                    "next_post_at": next_at,
                },
            ).to_dict()
    except Exception as exc:
        logger.exception("mcp_activate_error", error=str(exc))
        return MCPError(
            error_code="INTERNAL_ERROR",
            message="Unexpected error during activation",
            retryable=True,
            suggestion="Try again in 60 seconds",
        ).to_dict()


def tool_get_campaign_status(campaign_id: str) -> dict:
    """Get current status and post breakdown for a campaign.

    Args:
        campaign_id: UUID string of the campaign.

    Returns:
        MCPResult or MCPError as dict.
    """
    try:
        cid = UUID(campaign_id)
    except ValueError:
        return MCPError(
            error_code="INVALID_ID",
            message=f"Invalid campaign ID format: {campaign_id!r}",
            retryable=False,
            suggestion="Provide a valid UUID",
        ).to_dict()

    try:
        with get_session() as session:
            campaign = session.get(Campaign, cid)
            if campaign is None:
                return MCPError(
                    error_code="CAMPAIGN_NOT_FOUND",
                    message=f"Campaign {campaign_id} not found",
                    retryable=False,
                    suggestion="Check the campaign ID",
                ).to_dict()

            posts = list(
                session.execute(
                    select(Post).where(Post.campaign_id == cid)
                ).scalars()
            )

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

            return MCPResult(
                success=True,
                data={
                    "campaign_id": campaign_id,
                    "name": campaign.name,
                    "status": campaign.status.value,
                    "total_posts": len(posts),
                    "posts_by_state": posts_by_state,
                    "next_scheduled": [
                        {
                            "slug": p.slug,
                            "platform": p.platform.value,
                            "scheduled_at": p.scheduled_at.isoformat(),
                        }
                        for p in next_scheduled
                    ],
                    "recently_completed": [
                        {
                            "slug": p.slug,
                            "platform": p.platform.value,
                            "state": p.state.value,
                            "published_at": p.published_at.isoformat() if p.published_at else None,
                        }
                        for p in recently_completed
                    ],
                },
            ).to_dict()
    except Exception as exc:
        logger.exception("mcp_status_error", error=str(exc))
        return MCPError(
            error_code="INTERNAL_ERROR",
            message="Unexpected error fetching status",
            retryable=True,
            suggestion="Try again in 60 seconds",
        ).to_dict()


def tool_pause_campaign(campaign_id: str) -> dict:
    """Pause an ACTIVE campaign — removes scheduler jobs, keeps DB state.

    Args:
        campaign_id: UUID string of the campaign.

    Returns:
        MCPResult or MCPError as dict.
    """
    try:
        cid = UUID(campaign_id)
    except ValueError:
        return MCPError(
            error_code="INVALID_ID",
            message=f"Invalid campaign ID format: {campaign_id!r}",
            retryable=False,
            suggestion="Provide a valid UUID",
        ).to_dict()

    try:
        with get_session() as session:
            campaign = session.get(Campaign, cid)
            if campaign is None:
                return MCPError(
                    error_code="CAMPAIGN_NOT_FOUND",
                    message=f"Campaign {campaign_id} not found",
                    retryable=False,
                    suggestion="Check the campaign ID",
                ).to_dict()

            if campaign.status != CampaignStatus.ACTIVE:
                return MCPError(
                    error_code="INVALID_STATE",
                    message=f"Campaign is {campaign.status.value}, must be ACTIVE to pause",
                    retryable=False,
                    suggestion="Only ACTIVE campaigns can be paused",
                ).to_dict()

            _pause_campaign(session, campaign)
            campaign.status = CampaignStatus.PAUSED
            session.commit()

            return MCPResult(
                success=True,
                data={
                    "campaign_id": campaign_id,
                    "status": "PAUSED",
                    "message": "Campaign paused. Use resume_campaign to re-schedule.",
                },
            ).to_dict()
    except Exception as exc:
        logger.exception("mcp_pause_error", error=str(exc))
        return MCPError(
            error_code="INTERNAL_ERROR",
            message="Unexpected error during pause",
            retryable=True,
            suggestion="Try again in 60 seconds",
        ).to_dict()


def tool_resume_campaign(campaign_id: str) -> dict:
    """Resume a PAUSED campaign — re-creates scheduler jobs.

    Args:
        campaign_id: UUID string of the campaign.

    Returns:
        MCPResult or MCPError as dict.
    """
    try:
        cid = UUID(campaign_id)
    except ValueError:
        return MCPError(
            error_code="INVALID_ID",
            message=f"Invalid campaign ID format: {campaign_id!r}",
            retryable=False,
            suggestion="Provide a valid UUID",
        ).to_dict()

    try:
        with get_session() as session:
            campaign = session.get(Campaign, cid)
            if campaign is None:
                return MCPError(
                    error_code="CAMPAIGN_NOT_FOUND",
                    message=f"Campaign {campaign_id} not found",
                    retryable=False,
                    suggestion="Check the campaign ID",
                ).to_dict()

            if campaign.status != CampaignStatus.PAUSED:
                return MCPError(
                    error_code="INVALID_STATE",
                    message=f"Campaign is {campaign.status.value}, must be PAUSED to resume",
                    retryable=False,
                    suggestion="Only PAUSED campaigns can be resumed",
                ).to_dict()

            _resume_campaign(session, campaign)
            campaign.status = CampaignStatus.ACTIVE
            session.commit()

            return MCPResult(
                success=True,
                data={
                    "campaign_id": campaign_id,
                    "status": "ACTIVE",
                    "message": "Campaign resumed. Scheduled jobs re-created.",
                },
            ).to_dict()
    except Exception as exc:
        logger.exception("mcp_resume_error", error=str(exc))
        return MCPError(
            error_code="INTERNAL_ERROR",
            message="Unexpected error during resume",
            retryable=True,
            suggestion="Try again in 60 seconds",
        ).to_dict()
