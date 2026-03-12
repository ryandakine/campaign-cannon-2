"""Import/export routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, require_auth
from src.db.unit_of_work import unit_of_work
from src.schemas.import_export import ImportRequest, QuickStartRequest
from src.services import import_service
from src.services.asset_service import ALLOWED_TYPES, guess_mime_type
from src.services.schedule_service import filter_posting_windows, generate_schedule

router = APIRouter(prefix="/api/v1/campaigns", tags=["import-export"], dependencies=[Depends(require_auth)])


@router.post("/import-json", status_code=201)
async def import_json(body: ImportRequest) -> dict:
    async with unit_of_work() as session:
        asset_dir = Path(body.asset_dir) if body.asset_dir else None
        campaign = await import_service.import_from_json(
            session,
            data=body.model_dump(),
            asset_dir=asset_dir,
        )
        return {
            "message": "Campaign imported successfully",
            "campaign_slug": campaign.slug,
            "campaign_id": campaign.id,
        }


@router.get("/{slug}/export")
async def export_campaign(slug: str, db: AsyncSession = Depends(get_db)) -> dict:
    return await import_service.export_campaign(db, slug)


@router.post("/quick-start", status_code=201)
async def quick_start(body: QuickStartRequest) -> dict:
    """Quick-start a campaign from a local folder."""
    folder = Path(body.folder_path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Folder not found: {body.folder_path}")

    # Build import data from folder contents
    assets = []
    media_files = []
    for f in sorted(folder.iterdir()):
        if f.is_file():
            mime = guess_mime_type(f.name)
            if mime and mime in ALLOWED_TYPES:
                assets.append({"filename": f.name, "mime_type": mime})
                media_files.append(f)

    # Generate schedule: use rrule if provided, otherwise space 1 hour apart
    now = datetime.now(timezone.utc) + timedelta(minutes=5)
    if body.rrule:
        schedule = generate_schedule(rrule_str=body.rrule, start_dt=now, count=len(assets))
        if body.posting_windows:
            schedule = filter_posting_windows(schedule, body.posting_windows)
    else:
        schedule = [now + timedelta(hours=i) for i in range(len(assets))]

    posts = []
    for i, f in enumerate(media_files):
        scheduled_at = schedule[i].isoformat() if i < len(schedule) else schedule[-1].isoformat()
        posts.append({
            "asset_filename": f.name,
            "platform": body.platform,
            "copy": f.stem.replace("-", " ").replace("_", " ").title(),
            "scheduled_at": scheduled_at,
        })

    import_data = {
        "schema_version": "1.0",
        "campaign": {
            "slug": body.slug,
            "name": body.name,
            "description": body.description,
            "timezone": body.timezone,
        },
        "assets": assets,
        "posts": posts,
    }

    async with unit_of_work() as session:
        campaign = await import_service.import_from_json(session, data=import_data, asset_dir=folder)
        return {
            "message": "Campaign created via quick-start",
            "campaign_slug": campaign.slug,
            "campaign_id": campaign.id,
            "assets_found": len(assets),
            "posts_created": len(posts),
        }
