"""Campaign Cannon 2 — Typed exception hierarchy.

All application exceptions descend from CampaignCannonError.
"""

from __future__ import annotations


class CampaignCannonError(Exception):
    """Base for all Campaign Cannon errors."""

    def __init__(self, message: str = "", code: str = "INTERNAL_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


# --- Validation ---
class ValidationError(CampaignCannonError):
    def __init__(self, message: str = "Validation failed") -> None:
        super().__init__(message, "VALIDATION_ERROR")


class SlugConflictError(CampaignCannonError):
    def __init__(self, slug: str) -> None:
        super().__init__(f"Campaign with slug '{slug}' already exists", "SLUG_CONFLICT")


# --- State ---
class StateTransitionError(CampaignCannonError):
    def __init__(self, current: str, target: str, entity: str = "campaign") -> None:
        super().__init__(
            f"Cannot transition {entity} from '{current}' to '{target}'",
            "INVALID_STATE_TRANSITION",
        )


# --- Not found ---
class NotFoundError(CampaignCannonError):
    def __init__(self, entity: str, identifier: str) -> None:
        super().__init__(f"{entity} '{identifier}' not found", "NOT_FOUND")


# --- Locking ---
class LockError(CampaignCannonError):
    def __init__(self, message: str = "Failed to acquire lock") -> None:
        super().__init__(message, "LOCK_ERROR")


# --- Adapter / platform ---
class AdapterError(CampaignCannonError):
    def __init__(self, message: str = "Platform adapter error", code: str = "ADAPTER_ERROR") -> None:
        super().__init__(message, code)


class AuthenticationError(AdapterError):
    def __init__(self, platform: str) -> None:
        super().__init__(f"Authentication failed for {platform}", "AUTH_ERROR")


class RateLimitExceededError(AdapterError):
    def __init__(self, platform: str, retry_after: int | None = None) -> None:
        msg = f"Rate limit exceeded for {platform}"
        if retry_after:
            msg += f" (retry after {retry_after}s)"
        super().__init__(msg, "RATE_LIMIT_EXCEEDED")
        self.retry_after = retry_after


class PostingError(AdapterError):
    def __init__(self, platform: str, detail: str = "") -> None:
        super().__init__(f"Posting to {platform} failed: {detail}", "POSTING_ERROR")


class MediaValidationError(AdapterError):
    def __init__(self, detail: str = "") -> None:
        super().__init__(f"Media validation failed: {detail}", "MEDIA_VALIDATION_ERROR")


# --- Import ---
class ImportError_(CampaignCannonError):
    def __init__(self, message: str = "Import failed") -> None:
        super().__init__(message, "IMPORT_ERROR")
