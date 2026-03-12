"""Post management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, require_auth
from src.db.models import Platform, PostStatus
from src.schemas.post import PostListResponse, PostResponse, PostUpdate
from src.services import campaign_service, post_service

router = APIRouter(
    prefix="/api/v1/campaigns/{slug}/posts",
    tags=["posts"],
    dependencies=[Depends(require_auth)],
)


def _post_to_response(p: object) -> PostResponse:
    return PostResponse.model_validate(p)


@router.get("", response_model=PostListResponse)
async def list_posts(
    slug: str,
    status: str | None = None,
    platform: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> PostListResponse:
    campaign = await campaign_service.get_campaign(db, slug)

    status_enum = PostStatus(status) if status else None
    platform_enum = Platform(platform) if platform else None

    posts = await post_service.list_posts(
        db, campaign.id, status=status_enum, platform=platform_enum, limit=limit, offset=offset
    )
    return PostListResponse(
        posts=[_post_to_response(p) for p in posts],
        total=len(posts),
    )


@router.put("/{post_id}", response_model=PostResponse)
async def update_post(
    slug: str, post_id: str, body: PostUpdate, db: AsyncSession = Depends(get_db)
) -> PostResponse:
    async with db.begin():
        await post_service.get_post_with_campaign(db, slug, post_id)
        post = await post_service.update_post(
            db,
            post_id,
            copy=body.copy,
            scheduled_at=body.scheduled_at,
            subreddit=body.subreddit,
            hashtags=body.hashtags,
            target_account=body.target_account,
        )
        return _post_to_response(post)


@router.delete("/{post_id}", status_code=204)
async def delete_post(slug: str, post_id: str, db: AsyncSession = Depends(get_db)) -> None:
    async with db.begin():
        await post_service.get_post_with_campaign(db, slug, post_id)
        await post_service.delete_post(db, post_id)
