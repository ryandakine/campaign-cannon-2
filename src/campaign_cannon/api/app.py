"""FastAPI application for Campaign Cannon v3.1."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from campaign_cannon.api.errors import register_exception_handlers
from campaign_cannon.api.routes import router
from campaign_cannon.config.settings import get_settings

logger = structlog.get_logger("campaign_cannon.api")

# Module-level startup time for health endpoint
_startup_time: float = 0.0


# ── Lifespan ────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown hooks."""
    global _startup_time

    settings = get_settings()
    logger.info("startup_begin", app="Campaign Cannon", version="3.1.0")

    # Initialize database (create tables if needed)
    from campaign_cannon.db.connection import init_db

    init_db()
    logger.info("database_initialized")

    # Start APScheduler
    from campaign_cannon.engine.scheduler import start_scheduler

    start_scheduler()
    logger.info("scheduler_started")

    _startup_time = time.time()
    logger.info("startup_complete", host=settings.api_host, port=settings.api_port)

    yield

    # Shutdown
    logger.info("shutdown_begin")

    from campaign_cannon.engine.scheduler import shutdown_scheduler

    shutdown_scheduler()
    logger.info("scheduler_stopped")

    from campaign_cannon.db.connection import close_db

    close_db()
    logger.info("database_closed")

    logger.info("shutdown_complete")


# ── App Factory ─────────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Campaign Cannon",
        version="3.1.0",
        description="Bulletproof social media campaign automation engine",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request ID + logging middleware
    @app.middleware("http")
    async def request_middleware(request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start = time.perf_counter()

        response: Response = await call_next(request)

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Request-ID"] = request_id

        logger.info(
            "request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    # Register exception handlers
    register_exception_handlers(app)

    # Include versioned routes
    app.include_router(router)

    return app


# ── Entrypoint ──────────────────────────────────────────────────────────────

app = create_app()


def main() -> None:
    """Run the Campaign Cannon API server."""
    settings = get_settings()
    uvicorn.run(
        "campaign_cannon.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
