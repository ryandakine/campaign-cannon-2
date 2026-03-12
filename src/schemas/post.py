"""Pydantic schemas for post API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PostCreate(BaseModel):
    platform: str = Field(..., pattern=r"^(twitter|reddit)$")
    copy: str = Field(..., min_length=1)
    scheduled_at: datetime
    asset_id: Optional[str] = None
    target_account: Optional[str] = None
    subreddit: Optional[str] = None
    hashtags: Optional[str] = None


class PostUpdate(BaseModel):
    copy: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    subreddit: Optional[str] = None
    hashtags: Optional[str] = None
    target_account: Optional[str] = None


class PostResponse(BaseModel):
    id: str
    campaign_id: str
    platform: str
    copy: str
    scheduled_at: datetime
    status: str
    posted_at: Optional[datetime]
    platform_post_id: Optional[str]
    retry_count: int
    error: Optional[str]
    subreddit: Optional[str]
    target_account: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PostListResponse(BaseModel):
    posts: list[PostResponse]
    total: int
