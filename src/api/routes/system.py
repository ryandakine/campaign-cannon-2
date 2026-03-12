"""System health routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from src.api.deps import get_db

router = APIRouter(prefix="/api/v1", tags=["system"])


@router.get("/status")
async def system_status(db: AsyncSession = Depends(get_db)) -> dict:
    """System health check."""
    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    return {
        "status": "ok" if db_ok else "degraded",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": "connected" if db_ok else "disconnected",
    }
