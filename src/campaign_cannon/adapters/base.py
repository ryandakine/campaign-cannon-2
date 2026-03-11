"""Base adapter interface for platform publishing.

All platform adapters inherit from BaseAdapter and implement publish(),
validate_credentials(), and delete_post(). The publish() method must
NEVER raise — all errors are captured in PlatformResult.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from campaign_cannon.db.models import MediaAsset, Platform, Post


@dataclass
class PlatformResult:
    """Outcome of a single publish attempt.

    Every adapter.publish() call returns one of these — never raises.
    """

    success: bool
    platform_post_id: Optional[str] = None
    platform_post_url: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retryable: bool = False
    rate_limit_reset: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        platform_post_id: str,
        platform_post_url: Optional[str] = None,
        **kwargs,
    ) -> PlatformResult:
        """Convenience constructor for a successful result."""
        return cls(
            success=True,
            platform_post_id=platform_post_id,
            platform_post_url=platform_post_url,
            **kwargs,
        )

    @classmethod
    def fail(
        cls,
        error_code: str,
        error_message: str,
        retryable: bool = False,
        **kwargs,
    ) -> PlatformResult:
        """Convenience constructor for a failed result."""
        return cls(
            success=False,
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
            **kwargs,
        )


class BaseAdapter(ABC):
    """Abstract base class for platform adapters.

    Subclasses must implement publish(), validate_credentials(), delete_post(),
    and the platform property.  The publish() contract is strict: it must
    NEVER raise an exception — all errors are returned via PlatformResult.
    """

    @abstractmethod
    def publish(self, post: Post, media_assets: list[MediaAsset]) -> PlatformResult:
        """Publish a post to the platform.

        Must not raise — always return a PlatformResult.

        Args:
            post: The Post ORM object with body, title, metadata, etc.
            media_assets: List of MediaAsset ORM objects attached to the post.

        Returns:
            PlatformResult with success/failure details.
        """
        ...

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Test if stored credentials are valid.

        Returns:
            True if credentials are working, False otherwise.
        """
        ...

    @abstractmethod
    def delete_post(self, platform_post_id: str) -> bool:
        """Best-effort delete of a published post.

        Used for cleanup (e.g. duplicate removal). Should not raise.

        Args:
            platform_post_id: The platform-native post identifier.

        Returns:
            True if deleted (or already gone), False on failure.
        """
        ...

    @property
    @abstractmethod
    def platform(self) -> Platform:
        """The Platform enum value this adapter handles."""
        ...
