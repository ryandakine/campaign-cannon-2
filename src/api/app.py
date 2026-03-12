"""FastAPI app factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config import CORS_ORIGINS, DEBUG
from src.db.database import close_db, init_db
from src.exceptions import CampaignCannonError

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle."""
    from src.scheduler.scheduler import scheduler, start_scheduler

    logger.info("starting_campaign_cannon", version="2.0.0")
    await init_db()
    start_scheduler()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await close_db()
    logger.info("campaign_cannon_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Campaign Cannon 2",
        description="Universal Automated Social Media Campaign Engine",
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS — restricted to configured origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global exception handler
    @app.exception_handler(CampaignCannonError)
    async def campaign_error_handler(request: Request, exc: CampaignCannonError) -> JSONResponse:
        status_map = {
            "NOT_FOUND": 404,
            "SLUG_CONFLICT": 409,
            "VALIDATION_ERROR": 400,
            "INVALID_STATE_TRANSITION": 400,
            "RATE_LIMIT_EXCEEDED": 429,
            "AUTH_ERROR": 401,
        }
        status = status_map.get(exc.code, 500)
        return JSONResponse(
            status_code=status,
            content={"error": exc.code, "message": exc.message},
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", error=str(exc), path=request.url.path)
        detail = str(exc) if DEBUG else "Internal server error"
        return JSONResponse(
            status_code=500,
            content={"error": "INTERNAL_ERROR", "message": detail},
        )

    # Routes
    from src.api.routes import campaigns, dashboard, import_export, posts, system

    app.include_router(campaigns.router)
    app.include_router(posts.router)
    app.include_router(import_export.router)
    app.include_router(dashboard.router)
    app.include_router(system.router)

    # Static files
    import os
    static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static")
    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    return app
