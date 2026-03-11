"""JSON campaign import logic for Campaign Cannon.

Validates, deduplicates, and persists campaign data from a CampaignImportRequest.
Supports dry-run mode for previewing imports without writing to the database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog

from campaign_cannon.api.errors import DuplicateError, ImportValidationError
from campaign_cannon.api.schemas import (
    CampaignImportRequest,
    CampaignImportResponse,
    DryRunPostPreview,
    DryRunResponse,
)
from campaign_cannon.db.models import Campaign, CampaignStatus, MediaAsset, Post, PostState
from campaign_cannon.engine.dedup import check_duplicate, generate_idempotency_key
from campaign_cannon.import_.validator import validate_import
from campaign_cannon.media.pipeline import import_assets

logger = structlog.get_logger("campaign_cannon.import")


def import_campaign(
    session,
    payload: CampaignImportRequest,
    dry_run: bool = False,
) -> CampaignImportResponse | DryRunResponse:
    """Import a campaign from a validated request payload.

    Args:
        session: SQLAlchemy session.
        payload: The campaign import request.
        dry_run: If True, validate and preview without writing to DB.

    Returns:
        CampaignImportResponse on success, or DryRunResponse if dry_run=True.

    Raises:
        ImportValidationError: If payload validation fails.
        DuplicateError: If campaign slug already exists.
    """
    # Step 1: Validate payload
    validation = validate_import(payload, check_media_exists=not dry_run)
    if not validation.valid:
        raise ImportValidationError(
            errors=validation.errors,
            warnings=validation.warnings,
        )

    warnings = list(validation.warnings)

    # Step 2: Generate idempotency keys for preview/dedup
    campaign_id = uuid.uuid4()
    post_previews: list[DryRunPostPreview] = []
    idempotency_keys: list[str] = []

    for post_data in payload.posts:
        key = generate_idempotency_key(
            campaign_slug=payload.slug,
            post_slug=post_data.slug,
            platform=post_data.platform.value,
            scheduled_at=post_data.scheduled_at.isoformat(),
        )
        idempotency_keys.append(key)
        post_previews.append(
            DryRunPostPreview(
                slug=post_data.slug,
                platform=post_data.platform,
                scheduled_at=post_data.scheduled_at,
                body_length=len(post_data.body),
                media_count=len(post_data.media_paths),
                idempotency_key=key,
            )
        )

    # Step 3: Dry-run returns preview only
    if dry_run:
        return DryRunResponse(
            valid=True,
            name=payload.name,
            slug=payload.slug,
            post_count=len(payload.posts),
            posts=post_previews,
            errors=[],
            warnings=warnings,
        )

    # Step 4: Check for duplicate campaign slug
    from sqlalchemy import select

    existing = session.execute(
        select(Campaign).where(Campaign.slug == payload.slug)
    ).scalar_one_or_none()
    if existing:
        raise DuplicateError(f"Campaign with slug {payload.slug!r} already exists")

    # Step 5: Create Campaign record
    campaign = Campaign(
        id=campaign_id,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        status=CampaignStatus.DRAFT,
        metadata=payload.metadata,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(campaign)

    # Step 6: Create Post records
    for i, post_data in enumerate(payload.posts):
        key = idempotency_keys[i]

        # Check for idempotency key duplicates (warn, don't block)
        is_dup = check_duplicate(session, key)
        if is_dup:
            warnings.append(
                f"Post {post_data.slug!r} has duplicate idempotency key — "
                "may have been imported before"
            )

        post = Post(
            id=uuid.uuid4(),
            campaign_id=campaign_id,
            slug=post_data.slug,
            platform=post_data.platform,
            title=post_data.title,
            body=post_data.body,
            scheduled_at=post_data.scheduled_at,
            state=PostState.SCHEDULED,
            idempotency_key=key,
            retry_count=0,
            max_retries=3,
            version=1,
            metadata=post_data.metadata,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(post)

        # Step 7: Import media assets
        if post_data.media_paths:
            assets = import_assets(
                post_id=post.id,
                media_paths=post_data.media_paths,
                base_path=payload.media_base_path,
            )
            for asset in assets:
                session.add(asset)

    logger.info(
        "campaign_import_complete",
        campaign_id=str(campaign_id),
        slug=payload.slug,
        post_count=len(payload.posts),
        warnings=warnings,
    )

    return CampaignImportResponse(
        campaign_id=campaign_id,
        name=payload.name,
        slug=payload.slug,
        post_count=len(payload.posts),
        warnings=warnings,
        dry_run=False,
    )
