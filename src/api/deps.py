"""Dependency injection for FastAPI routes."""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import ALLOW_REMOTE, API_TOKEN
from src.db.database import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def require_auth(request: Request) -> None:
    """Enforce Bearer token auth when remote access is enabled."""
    if not ALLOW_REMOTE:
        return  # Localhost-only, no auth needed

    if not API_TOKEN:
        return  # No token configured

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = auth_header[7:]
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
