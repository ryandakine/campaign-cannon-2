"""Campaign CRUD + state transition routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, require_auth
from src.db.models import CampaignStatus
from src.schemas.campaign import (
    CampaignCreate,
    CampaignListResponse,
    CampaignResponse,
    CampaignUpdate,
)
from src.services import campaign_service

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"], dependencies=[Depends(require_auth)])


def _campaign_to_response(c: object) -> CampaignResponse:
    return CampaignResponse.model_validate(c)


@router.post("", response_model=CampaignResponse, status_code=201)
async def create_campaign(body: CampaignCreate, db: AsyncSession = Depends(get_db)) -> CampaignResponse:
    async with db.begin():
        campaign = await campaign_service.create_campaign(
            db,
            slug=body.slug,
            name=body.name,
            description=body.description,
            timezone_str=body.timezone,
            catch_up=body.catch_up,
            profile_id=body.profile_id,
        )
        return _campaign_to_response(campaign)


@router.get("", response_model=CampaignListResponse)
async def list_campaigns(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> CampaignListResponse:
    status_enum = CampaignStatus(status) if status else None
    campaigns = await campaign_service.list_campaigns(db, status=status_enum, limit=limit, offset=offset)
    return CampaignListResponse(
        campaigns=[_campaign_to_response(c) for c in campaigns],
        total=len(campaigns),
    )


@router.get("/{slug}", response_model=CampaignResponse)
async def get_campaign(slug: str, db: AsyncSession = Depends(get_db)) -> CampaignResponse:
    campaign = await campaign_service.get_campaign(db, slug)
    return _campaign_to_response(campaign)


@router.put("/{slug}", response_model=CampaignResponse)
async def update_campaign(
    slug: str, body: CampaignUpdate, db: AsyncSession = Depends(get_db)
) -> CampaignResponse:
    async with db.begin():
        campaign = await campaign_service.update_campaign(
            db,
            slug,
            name=body.name,
            description=body.description,
            timezone_str=body.timezone,
            catch_up=body.catch_up,
        )
        return _campaign_to_response(campaign)


@router.post("/{slug}/activate", response_model=CampaignResponse)
async def activate_campaign(slug: str, db: AsyncSession = Depends(get_db)) -> CampaignResponse:
    async with db.begin():
        campaign = await campaign_service.activate_campaign(db, slug)
        return _campaign_to_response(campaign)


@router.post("/{slug}/pause", response_model=CampaignResponse)
async def pause_campaign(slug: str, db: AsyncSession = Depends(get_db)) -> CampaignResponse:
    async with db.begin():
        campaign = await campaign_service.pause_campaign(db, slug)
        return _campaign_to_response(campaign)


@router.post("/{slug}/resume", response_model=CampaignResponse)
async def resume_campaign(slug: str, db: AsyncSession = Depends(get_db)) -> CampaignResponse:
    async with db.begin():
        campaign = await campaign_service.resume_campaign(db, slug)
        return _campaign_to_response(campaign)


@router.post("/{slug}/cancel", response_model=CampaignResponse)
async def cancel_campaign(slug: str, db: AsyncSession = Depends(get_db)) -> CampaignResponse:
    async with db.begin():
        campaign = await campaign_service.cancel_campaign(db, slug)
        return _campaign_to_response(campaign)


@router.get("/{slug}/status")
async def campaign_status(slug: str, db: AsyncSession = Depends(get_db)) -> dict:
    return await campaign_service.get_campaign_status(db, slug)
