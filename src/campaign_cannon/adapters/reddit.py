"""Reddit platform adapter using PRAW with OAuth2 script app.

Reddit OAuth2 script app uses username/password flow.  If Reddit deprecates
this post-2026, the adapter will be updated to a refresh-token flow with
zero API-surface changes.

publish() NEVER raises — all errors are captured in PlatformResult.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from campaign_cannon.adapters.base import BaseAdapter, PlatformResult

if TYPE_CHECKING:
    from campaign_cannon.db.models import MediaAsset, Platform, Post

logger = structlog.get_logger(__name__)

# Lazy import to avoid hard dependency at import time.
_praw = None


def _get_praw():
    global _praw
    if _praw is None:
        import praw  # type: ignore[import-untyped]

        _praw = praw
    return _praw


class RedditAdapter(BaseAdapter):
    """Adapter for Reddit using PRAW.

    Credentials dict must contain:
        - client_id: str
        - client_secret: str
        - username: str
        - password: str
        - user_agent: str (optional — defaults to "CampaignCannon/3.1")

    Post metadata may include:
        - subreddit: str (required — e.g. "marketing")
        - post_type: "text" | "link" | "image" (default "text")
    """

    def __init__(self, credentials: dict[str, str]) -> None:
        self._credentials = credentials
        self._reddit: Any = None

    # -- lazy client ---------------------------------------------------------

    def _ensure_client(self) -> None:
        if self._reddit is not None:
            return
        praw = _get_praw()
        self._reddit = praw.Reddit(
            client_id=self._credentials["client_id"],
            client_secret=self._credentials["client_secret"],
            username=self._credentials["username"],
            password=self._credentials["password"],
            user_agent=self._credentials.get("user_agent", "CampaignCannon/3.1"),
        )

    # -- BaseAdapter implementation -----------------------------------------

    @property
    def platform(self) -> Platform:
        from campaign_cannon.db.models import Platform

        return Platform.REDDIT

    def publish(self, post: Post, media_assets: list[MediaAsset]) -> PlatformResult:
        """Publish a Reddit post (text, link, or image)."""
        try:
            self._ensure_client()

            metadata: dict = post.metadata or {}
            subreddit_name = metadata.get("subreddit")
            if not subreddit_name:
                return PlatformResult.fail(
                    error_code="MISSING_SUBREDDIT",
                    error_message="post.metadata must include 'subreddit'",
                    retryable=False,
                )

            subreddit = self._reddit.subreddit(subreddit_name)

            # Reddit requires a title — fall back to first 100 chars of body.
            title = post.title or (post.body or "")[:100]
            if not title:
                return PlatformResult.fail(
                    error_code="MISSING_TITLE",
                    error_message="Reddit requires a title (post.title or body[:100])",
                    retryable=False,
                )

            post_type = metadata.get("post_type", "text")

            if post_type == "link":
                submission = subreddit.submit(title=title, url=post.body)
            elif post_type == "image" and media_assets:
                submission = subreddit.submit_image(
                    title=title,
                    image_path=media_assets[0].file_path,
                )
            else:
                # Default: text post
                submission = subreddit.submit(title=title, selftext=post.body or "")

            post_id = str(submission.id)
            post_url = f"https://www.reddit.com{submission.permalink}"

            logger.info(
                "reddit_published",
                submission_id=post_id,
                subreddit=subreddit_name,
                url=post_url,
            )
            return PlatformResult.ok(
                platform_post_id=post_id,
                platform_post_url=post_url,
            )

        except Exception as exc:
            return self._handle_exception(exc)

    def validate_credentials(self) -> bool:
        """Verify credentials by fetching the authenticated user."""
        try:
            self._ensure_client()
            user = self._reddit.user.me()
            return user is not None
        except Exception:
            logger.exception("reddit_credential_validation_failed")
            return False

    def delete_post(self, platform_post_id: str) -> bool:
        """Best-effort post deletion."""
        try:
            self._ensure_client()
            submission = self._reddit.submission(id=platform_post_id)
            submission.delete()
            return True
        except Exception:
            logger.exception("reddit_delete_failed", submission_id=platform_post_id)
            return False

    # -- internal helpers ---------------------------------------------------

    def _handle_exception(self, exc: Exception) -> PlatformResult:
        """Map PRAW / network exceptions to PlatformResult."""
        praw = _get_praw()

        error_str = str(exc)

        # PRAW wraps HTTP errors in specific exception types
        if isinstance(exc, praw.exceptions.RedditAPIException):
            # Check for rate limiting
            for item in getattr(exc, "items", []):
                if getattr(item, "error_type", "") == "RATELIMIT":
                    logger.warning("reddit_rate_limited", detail=error_str)
                    return PlatformResult.fail(
                        error_code="429",
                        error_message=f"Reddit rate limit: {error_str}",
                        retryable=True,
                    )
            logger.warning("reddit_api_error", detail=error_str)
            return PlatformResult.fail(
                error_code="REDDIT_API_ERROR",
                error_message=error_str,
                retryable=False,
            )

        # prawcore HTTP errors
        try:
            import prawcore  # type: ignore[import-untyped]

            if isinstance(exc, prawcore.exceptions.ResponseException):
                status = getattr(exc, "response", None)
                status_code = getattr(status, "status_code", 0) if status else 0
                retryable = status_code in (429, 500, 502, 503, 504)
                logger.warning(
                    "reddit_http_error",
                    status=status_code,
                    detail=error_str,
                )
                return PlatformResult.fail(
                    error_code=str(status_code),
                    error_message=error_str,
                    retryable=retryable,
                )

            if isinstance(exc, prawcore.exceptions.RequestException):
                logger.warning("reddit_request_error", detail=error_str)
                return PlatformResult.fail(
                    error_code="NETWORK_ERROR",
                    error_message=error_str,
                    retryable=True,
                )
        except ImportError:
            pass

        # Fallback
        logger.exception("reddit_unexpected_error", error=error_str)
        return PlatformResult.fail(
            error_code="UNEXPECTED",
            error_message=error_str,
            retryable=True,
        )
