"""Import service — JSON import with full transactional safety."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Campaign, MediaAsset, AssetStatus, Platform, Post
from src.services import campaign_service, post_service, asset_service
from src.exceptions import ImportError_, ValidationError

logger = structlog.get_logger()

SUPPORTED_SCHEMA_VERSIONS = {"1.0"}


async def import_from_json(
    session: AsyncSession,
    data: dict[str, Any],
    asset_dir: Path | None = None,
) -> Campaign:
    """Import a campaign from JSON data.

    Everything happens in the caller's transaction (unit_of_work).
    If anything fails, the entire import is rolled back — no orphan records.
    """
    schema_version = data.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ImportError_(f"Unsupported schema version: {schema_version}. Supported: {SUPPORTED_SCHEMA_VERSIONS}")

    campaign_data = data.get("campaign", {})
    assets_data = data.get("assets", [])
    posts_data = data.get("posts", [])

    if not campaign_data.get("slug"):
        raise ValidationError("Campaign slug is required")
    if not campaign_data.get("name"):
        raise ValidationError("Campaign name is required")

    # Create campaign
    campaign = await campaign_service.create_campaign(
        session,
        slug=campaign_data["slug"],
        name=campaign_data["name"],
        description=campaign_data.get("description"),
        timezone_str=campaign_data.get("timezone", "UTC"),
        catch_up=campaign_data.get("catch_up", False),
    )

    # Process assets
    asset_map: dict[str, MediaAsset] = {}  # filename -> MediaAsset
    for asset_data in assets_data:
        filename = asset_data.get("filename")
        if not filename:
            continue

        mime_type = asset_data.get("mime_type") or asset_service.guess_mime_type(filename)
        if not mime_type:
            raise ImportError_(f"Cannot determine MIME type for: {filename}")

        storage_key = f"{campaign.slug}/media/{filename}"
        sha256 = ""

        # Copy file if asset_dir provided
        if asset_dir:
            source = asset_dir / filename
            if source.exists():
                dest, sha256 = asset_service.copy_asset_to_campaign(
                    source, campaign.slug, filename
                )
                size_bytes = dest.stat().st_size
            else:
                logger.warning("asset_not_found", filename=filename)
                size_bytes = 0
                sha256 = "placeholder"
        else:
            size_bytes = 0
            sha256 = "placeholder"

        media_asset = MediaAsset(
            campaign_id=campaign.id,
            original_filename=filename,
            storage_key=storage_key,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=sha256,
            status=AssetStatus.ready if sha256 != "placeholder" else AssetStatus.placeholder,
        )
        session.add(media_asset)
        await session.flush()
        asset_map[filename] = media_asset

    # Create posts
    for post_data in posts_data:
        platform_str = post_data.get("platform", "twitter")
        try:
            platform = Platform(platform_str)
        except ValueError:
            raise ImportError_(f"Unsupported platform: {platform_str}")

        scheduled_at_str = post_data.get("scheduled_at")
        if not scheduled_at_str:
            raise ImportError_("Post scheduled_at is required")

        scheduled_at = datetime.fromisoformat(scheduled_at_str.replace("Z", "+00:00"))
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)

        copy = post_data.get("copy", "")
        if not copy:
            raise ImportError_("Post copy text is required")

        # Resolve asset
        asset_id = None
        asset_filename = post_data.get("asset_filename")
        if asset_filename and asset_filename in asset_map:
            asset_id = asset_map[asset_filename].id

        await post_service.create_post(
            session,
            campaign_id=campaign.id,
            platform=platform,
            copy=copy,
            scheduled_at=scheduled_at,
            asset_id=asset_id,
            subreddit=post_data.get("subreddit"),
            hashtags=json.dumps(post_data.get("hashtags")) if post_data.get("hashtags") else None,
            target_account=post_data.get("target_account"),
        )

    logger.info(
        "campaign_imported",
        slug=campaign.slug,
        assets=len(asset_map),
        posts=len(posts_data),
    )
    return campaign


async def export_campaign(session: AsyncSession, slug: str) -> dict[str, Any]:
    """Export a campaign as a JSON-safe dict."""
    campaign = await campaign_service.get_campaign(session, slug)

    assets = []
    for asset in campaign.assets:
        assets.append({
            "filename": asset.original_filename,
            "mime_type": asset.mime_type,
            "sha256": asset.sha256,
            "size_bytes": asset.size_bytes,
        })

    posts = []
    for post in campaign.posts:
        post_dict: dict[str, Any] = {
            "platform": post.platform.value,
            "copy": post.copy,
            "scheduled_at": post.scheduled_at.isoformat(),
            "status": post.status.value,
        }
        if post.subreddit:
            post_dict["subreddit"] = post.subreddit
        if post.hashtags:
            post_dict["hashtags"] = json.loads(post.hashtags) if isinstance(post.hashtags, str) else post.hashtags
        if post.target_account:
            post_dict["target_account"] = post.target_account
        if post.asset_id:
            for asset in campaign.assets:
                if asset.id == post.asset_id:
                    post_dict["asset_filename"] = asset.original_filename
                    break
        posts.append(post_dict)

    return {
        "schema_version": "1.0",
        "campaign": {
            "slug": campaign.slug,
            "name": campaign.name,
            "description": campaign.description,
            "timezone": campaign.timezone,
            "catch_up": campaign.catch_up,
        },
        "assets": assets,
        "posts": posts,
    }
