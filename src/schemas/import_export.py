"""Pydantic schemas for import/export."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ImportRequest(BaseModel):
    schema_version: str = "1.0"
    campaign: dict[str, Any]
    assets: list[dict[str, Any]] = Field(default_factory=list)
    posts: list[dict[str, Any]] = Field(default_factory=list)
    asset_dir: Optional[str] = None


class QuickStartRequest(BaseModel):
    slug: str = Field(..., min_length=3, max_length=255)
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    timezone: str = "UTC"
    folder_path: str
    platform: str = "twitter"
    rrule: Optional[str] = None
    posting_windows: Optional[list[dict[str, Any]]] = None
