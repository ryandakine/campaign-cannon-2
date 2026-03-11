"""Custom exception classes and FastAPI exception handlers for Campaign Cannon."""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from campaign_cannon.api.schemas import ErrorResponse


# ── Custom Exceptions ───────────────────────────────────────────────────────


class CampaignNotFoundError(Exception):
    """Raised when a campaign ID does not exist."""

    def __init__(self, campaign_id: UUID) -> None:
        self.campaign_id = campaign_id
        super().__init__(f"Campaign {campaign_id} not found")


class PostNotFoundError(Exception):
    """Raised when a post ID does not exist."""

    def __init__(self, post_id: UUID) -> None:
        self.post_id = post_id
        super().__init__(f"Post {post_id} not found")


class InvalidStateError(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class DuplicateError(Exception):
    """Raised when a duplicate campaign slug or idempotency key is detected."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ImportValidationError(Exception):
    """Raised when campaign import payload fails validation."""

    def __init__(
        self,
        errors: list[str],
        warnings: list[str] | None = None,
        field_errors: dict[str, list[str]] | None = None,
    ) -> None:
        self.errors = errors
        self.warnings = warnings or []
        self.field_errors = field_errors
        super().__init__(f"Import validation failed: {'; '.join(errors)}")


# ── Exception Handlers ──────────────────────────────────────────────────────


def register_exception_handlers(app: FastAPI) -> None:
    """Register all custom exception handlers on the FastAPI app."""

    @app.exception_handler(CampaignNotFoundError)
    async def campaign_not_found_handler(
        request: Request, exc: CampaignNotFoundError
    ) -> JSONResponse:
        body = ErrorResponse(error="campaign_not_found", detail=str(exc))
        return JSONResponse(status_code=404, content=body.model_dump(exclude_none=True))

    @app.exception_handler(PostNotFoundError)
    async def post_not_found_handler(
        request: Request, exc: PostNotFoundError
    ) -> JSONResponse:
        body = ErrorResponse(error="post_not_found", detail=str(exc))
        return JSONResponse(status_code=404, content=body.model_dump(exclude_none=True))

    @app.exception_handler(InvalidStateError)
    async def invalid_state_handler(
        request: Request, exc: InvalidStateError
    ) -> JSONResponse:
        body = ErrorResponse(error="invalid_state", detail=exc.message)
        return JSONResponse(status_code=409, content=body.model_dump(exclude_none=True))

    @app.exception_handler(DuplicateError)
    async def duplicate_handler(
        request: Request, exc: DuplicateError
    ) -> JSONResponse:
        body = ErrorResponse(error="duplicate", detail=exc.message)
        return JSONResponse(status_code=409, content=body.model_dump(exclude_none=True))

    @app.exception_handler(ImportValidationError)
    async def import_validation_handler(
        request: Request, exc: ImportValidationError
    ) -> JSONResponse:
        body = ErrorResponse(
            error="import_validation_failed",
            detail="; ".join(exc.errors),
            field_errors=exc.field_errors,
        )
        return JSONResponse(status_code=422, content=body.model_dump(exclude_none=True))

    @app.exception_handler(RequestValidationError)
    async def pydantic_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        field_errors: dict[str, list[str]] = {}
        for err in exc.errors():
            loc = ".".join(str(part) for part in err["loc"] if part != "body")
            field_errors.setdefault(loc, []).append(err["msg"])
        body = ErrorResponse(
            error="validation_error",
            detail="Request validation failed",
            field_errors=field_errors if field_errors else None,
        )
        return JSONResponse(status_code=422, content=body.model_dump(exclude_none=True))

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        body = ErrorResponse(error="http_error", detail=str(exc.detail))
        return JSONResponse(status_code=exc.status_code, content=body.model_dump(exclude_none=True))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        import structlog

        logger = structlog.get_logger("campaign_cannon.api")
        logger.exception("unhandled_exception", error=str(exc))
        body = ErrorResponse(error="internal_error", detail="An unexpected error occurred")
        return JSONResponse(status_code=500, content=body.model_dump(exclude_none=True))
