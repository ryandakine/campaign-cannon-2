"""Campaign Cannon 2 — Complete MCP server via stdio transport.

All 9 tools fully implemented with proper error handling.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.db.database import init_db
from src.db.unit_of_work import unit_of_work
from src.exceptions import CampaignCannonError
from src.services import campaign_service, import_service, post_service

logger = structlog.get_logger()

mcp = Server("campaign-cannon-2")


def _ok(data: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _error(message: str) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"error": message}, indent=2))]


# ── Tool Definitions ───────────────────────────────────────────────────────


@mcp.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="campaign_create",
            description="Create a new campaign with metadata",
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Unique slug (lowercase, hyphens)"},
                    "name": {"type": "string", "description": "Display name"},
                    "description": {"type": "string", "description": "Optional description"},
                    "timezone": {"type": "string", "description": "Timezone (default UTC)"},
                    "catch_up": {"type": "boolean", "description": "Enable catch-up mode"},
                },
                "required": ["slug", "name"],
            },
        ),
        Tool(
            name="campaign_import",
            description="Import a campaign from JSON data with assets and posts",
            inputSchema={
                "type": "object",
                "properties": {
                    "data": {
                        "type": "object",
                        "description": "Import JSON matching schema_version 1.0",
                    },
                    "asset_dir": {
                        "type": "string",
                        "description": "Optional path to asset directory",
                    },
                },
                "required": ["data"],
            },
        ),
        Tool(
            name="campaign_activate",
            description="Activate a draft campaign, moving all draft posts to pending",
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Campaign slug"},
                },
                "required": ["slug"],
            },
        ),
        Tool(
            name="campaign_pause",
            description="Pause an active campaign",
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Campaign slug"},
                },
                "required": ["slug"],
            },
        ),
        Tool(
            name="campaign_resume",
            description="Resume a paused campaign",
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Campaign slug"},
                },
                "required": ["slug"],
            },
        ),
        Tool(
            name="campaign_cancel",
            description="Cancel a campaign, cancelling all non-terminal posts",
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Campaign slug"},
                },
                "required": ["slug"],
            },
        ),
        Tool(
            name="campaign_status",
            description="Get detailed campaign status including post counts and next due post",
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Campaign slug"},
                },
                "required": ["slug"],
            },
        ),
        Tool(
            name="post_list",
            description="List posts for a campaign with optional filters",
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Campaign slug"},
                    "status": {"type": "string", "description": "Filter by post status"},
                    "platform": {"type": "string", "description": "Filter by platform (twitter/reddit)"},
                    "limit": {"type": "integer", "description": "Max results (default 100)"},
                    "offset": {"type": "integer", "description": "Offset for pagination"},
                },
                "required": ["slug"],
            },
        ),
        Tool(
            name="post_update",
            description="Update a post's content, schedule, or metadata",
            inputSchema={
                "type": "object",
                "properties": {
                    "post_id": {"type": "string", "description": "Post UUID"},
                    "copy": {"type": "string", "description": "New post text"},
                    "scheduled_at": {"type": "string", "description": "New schedule (ISO 8601)"},
                    "subreddit": {"type": "string", "description": "New subreddit"},
                    "hashtags": {"type": "string", "description": "New hashtags (JSON array)"},
                    "target_account": {"type": "string", "description": "New target account"},
                },
                "required": ["post_id"],
            },
        ),
    ]


# ── Tool Handlers ──────────────────────────────────────────────────────────


@mcp.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "campaign_create":
            return await _handle_campaign_create(arguments)
        elif name == "campaign_import":
            return await _handle_campaign_import(arguments)
        elif name == "campaign_activate":
            return await _handle_campaign_activate(arguments)
        elif name == "campaign_pause":
            return await _handle_campaign_pause(arguments)
        elif name == "campaign_resume":
            return await _handle_campaign_resume(arguments)
        elif name == "campaign_cancel":
            return await _handle_campaign_cancel(arguments)
        elif name == "campaign_status":
            return await _handle_campaign_status(arguments)
        elif name == "post_list":
            return await _handle_post_list(arguments)
        elif name == "post_update":
            return await _handle_post_update(arguments)
        else:
            return _error(f"Unknown tool: {name}")
    except CampaignCannonError as e:
        return _error(e.message)
    except Exception as e:
        logger.error("mcp_tool_error", tool=name, error=str(e))
        return _error(f"Internal error: {type(e).__name__}")


async def _handle_campaign_create(args: dict[str, Any]) -> list[TextContent]:
    async with unit_of_work() as session:
        campaign = await campaign_service.create_campaign(
            session,
            slug=args["slug"],
            name=args["name"],
            description=args.get("description"),
            timezone_str=args.get("timezone", "UTC"),
            catch_up=args.get("catch_up", False),
        )
        return _ok({
            "id": campaign.id,
            "slug": campaign.slug,
            "name": campaign.name,
            "status": campaign.status.value,
            "message": f"Campaign '{campaign.slug}' created successfully",
        })


async def _handle_campaign_import(args: dict[str, Any]) -> list[TextContent]:
    data = args["data"]
    asset_dir = Path(args["asset_dir"]) if args.get("asset_dir") else None

    async with unit_of_work() as session:
        campaign = await import_service.import_from_json(session, data=data, asset_dir=asset_dir)
        return _ok({
            "id": campaign.id,
            "slug": campaign.slug,
            "message": f"Campaign '{campaign.slug}' imported successfully",
        })


async def _handle_campaign_activate(args: dict[str, Any]) -> list[TextContent]:
    async with unit_of_work() as session:
        campaign = await campaign_service.activate_campaign(session, args["slug"])
        return _ok({
            "slug": campaign.slug,
            "status": campaign.status.value,
            "message": f"Campaign '{campaign.slug}' activated",
        })


async def _handle_campaign_pause(args: dict[str, Any]) -> list[TextContent]:
    async with unit_of_work() as session:
        campaign = await campaign_service.pause_campaign(session, args["slug"])
        return _ok({
            "slug": campaign.slug,
            "status": campaign.status.value,
            "message": f"Campaign '{campaign.slug}' paused",
        })


async def _handle_campaign_resume(args: dict[str, Any]) -> list[TextContent]:
    async with unit_of_work() as session:
        campaign = await campaign_service.resume_campaign(session, args["slug"])
        return _ok({
            "slug": campaign.slug,
            "status": campaign.status.value,
            "message": f"Campaign '{campaign.slug}' resumed",
        })


async def _handle_campaign_cancel(args: dict[str, Any]) -> list[TextContent]:
    async with unit_of_work() as session:
        campaign = await campaign_service.cancel_campaign(session, args["slug"])
        return _ok({
            "slug": campaign.slug,
            "status": campaign.status.value,
            "message": f"Campaign '{campaign.slug}' cancelled",
        })


async def _handle_campaign_status(args: dict[str, Any]) -> list[TextContent]:
    async with unit_of_work() as session:
        status = await campaign_service.get_campaign_status(session, args["slug"])
        return _ok(status)


async def _handle_post_list(args: dict[str, Any]) -> list[TextContent]:
    from src.db.models import Platform, PostStatus

    slug = args["slug"]
    async with unit_of_work() as session:
        campaign = await campaign_service.get_campaign(session, slug)

        status = PostStatus(args["status"]) if args.get("status") else None
        platform = Platform(args["platform"]) if args.get("platform") else None
        limit = args.get("limit", 100)
        offset = args.get("offset", 0)

        posts = await post_service.list_posts(
            session, campaign.id, status=status, platform=platform, limit=limit, offset=offset
        )

        return _ok({
            "campaign_slug": slug,
            "total": len(posts),
            "posts": [
                {
                    "id": p.id,
                    "platform": p.platform.value,
                    "copy": p.copy[:100],
                    "scheduled_at": p.scheduled_at.isoformat(),
                    "status": p.status.value,
                    "retry_count": p.retry_count,
                    "error": p.error,
                }
                for p in posts
            ],
        })


async def _handle_post_update(args: dict[str, Any]) -> list[TextContent]:
    post_id = args["post_id"]

    scheduled_at = None
    if args.get("scheduled_at"):
        scheduled_at = datetime.fromisoformat(args["scheduled_at"].replace("Z", "+00:00"))
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)

    async with unit_of_work() as session:
        post = await post_service.update_post(
            session,
            post_id,
            copy=args.get("copy"),
            scheduled_at=scheduled_at,
            subreddit=args.get("subreddit"),
            hashtags=args.get("hashtags"),
            target_account=args.get("target_account"),
        )
        return _ok({
            "id": post.id,
            "status": post.status.value,
            "message": f"Post updated successfully",
        })


# ── Server Entry Point ────────────────────────────────────────────────────


async def run_server() -> None:
    """Run the MCP server with stdio transport."""
    await init_db()
    logger.info("mcp_server_starting")

    async with stdio_server() as (read_stream, write_stream):
        await mcp.run(read_stream, write_stream, mcp.create_initialization_options())
