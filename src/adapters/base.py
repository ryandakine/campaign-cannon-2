"""Base adapter — abstract interface for platform posting."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PostResult:
    """Result from a platform post attempt."""

    success: bool
    platform_post_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    provider_status_code: int | None = None
    is_retryable: bool = False
    request_fingerprint: str | None = None


class BaseAdapter(ABC):
    """Abstract base for platform adapters."""

    platform: str = ""

    @abstractmethod
    async def post(
        self,
        copy: str,
        *,
        media_path: Path | None = None,
        subreddit: str | None = None,
        hashtags: list[str] | None = None,
        target_account: str | None = None,
        idempotency_key: str | None = None,
        **kwargs: Any,
    ) -> PostResult:
        """Post content to the platform. Returns PostResult."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if the adapter has valid credentials."""
        ...
