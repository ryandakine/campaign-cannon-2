"""Pydantic schemas for campaign API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CampaignCreate(BaseModel):
    slug: str = Field(..., min_length=3, max_length=255, pattern=r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$")
    name: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    timezone: str = "UTC"
    catch_up: bool = False
    profile_id: Optional[str] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    timezone: Optional[str] = None
    catch_up: Optional[bool] = None


class CampaignResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: Optional[str]
    status: str
    timezone: str
    catch_up: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CampaignListResponse(BaseModel):
    campaigns: list[CampaignResponse]
    total: int
