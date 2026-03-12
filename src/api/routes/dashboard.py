"""Dashboard data routes — powers the read-only dashboard UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, require_auth
from src.config import DASHBOARD_ENABLED
from src.services import dashboard_service

router = APIRouter(tags=["dashboard"])

templates = Jinja2Templates(directory="templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> HTMLResponse:
    if not DASHBOARD_ENABLED:
        return HTMLResponse("<h1>Dashboard disabled</h1>", status_code=403)
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/api/v1/dashboard/summary")
async def dashboard_summary(db: AsyncSession = Depends(get_db), _auth: None = Depends(require_auth)) -> dict:
    return await dashboard_service.get_summary(db)


@router.get("/api/v1/dashboard/next-due")
async def dashboard_next_due(limit: int = 10, db: AsyncSession = Depends(get_db), _auth: None = Depends(require_auth)) -> list:
    return await dashboard_service.get_next_due(db, limit=limit)


@router.get("/api/v1/dashboard/recent-failures")
async def dashboard_recent_failures(limit: int = 10, db: AsyncSession = Depends(get_db), _auth: None = Depends(require_auth)) -> list:
    return await dashboard_service.get_recent_failures(db, limit=limit)


@router.get("/api/v1/dashboard/retry-queue")
async def dashboard_retry_queue(limit: int = 20, db: AsyncSession = Depends(get_db), _auth: None = Depends(require_auth)) -> list:
    return await dashboard_service.get_retry_queue(db, limit=limit)


@router.get("/api/v1/dashboard/rate-limits")
async def dashboard_rate_limits(db: AsyncSession = Depends(get_db), _auth: None = Depends(require_auth)) -> list:
    return await dashboard_service.get_rate_limits(db)


@router.get("/api/v1/dashboard/missed-posts")
async def dashboard_missed_posts(limit: int = 10, db: AsyncSession = Depends(get_db), _auth: None = Depends(require_auth)) -> list:
    return await dashboard_service.get_missed_posts(db, limit=limit)
