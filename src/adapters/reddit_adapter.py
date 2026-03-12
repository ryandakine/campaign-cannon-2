"""Reddit adapter — posting via PRAW."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import praw
import structlog

from src.adapters.base import BaseAdapter, PostResult
from src.config import (
    REDDIT_CLIENT_ID,
    REDDIT_CLIENT_SECRET,
    REDDIT_PASSWORD,
    REDDIT_USERNAME,
)

logger = structlog.get_logger()


class RedditAdapter(BaseAdapter):
    platform = "reddit"

    def __init__(self) -> None:
        self._reddit: praw.Reddit | None = None

    def is_configured(self) -> bool:
        return all([
            REDDIT_CLIENT_ID,
            REDDIT_CLIENT_SECRET,
            REDDIT_USERNAME,
            REDDIT_PASSWORD,
        ])

    def _get_reddit(self) -> praw.Reddit:
        if not self._reddit:
            self._reddit = praw.Reddit(
                client_id=REDDIT_CLIENT_ID,
                client_secret=REDDIT_CLIENT_SECRET,
                username=REDDIT_USERNAME,
                password=REDDIT_PASSWORD,
                user_agent="CampaignCannon/2.0",
            )
        return self._reddit

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
        if not subreddit:
            return PostResult(
                success=False,
                error_code="MISSING_SUBREDDIT",
                error_message="Subreddit is required for Reddit posts",
                is_retryable=False,
            )

        # Clean subreddit name
        sub_name = subreddit.lstrip("r/").lstrip("/")
        fingerprint = hashlib.sha256(f"{sub_name}:{copy}".encode()).hexdigest()[:16]

        try:
            reddit = self._get_reddit()
            sub = await asyncio.to_thread(reddit.subreddit, sub_name)

            # Extract title from first line or use copy
            lines = copy.strip().split("\n", 1)
            title = lines[0][:300]
            body = lines[1] if len(lines) > 1 else ""

            if media_path and media_path.exists():
                submission = await asyncio.to_thread(
                    sub.submit_image, title=title, image_path=str(media_path)
                )
            elif body:
                submission = await asyncio.to_thread(
                    sub.submit, title=title, selftext=body
                )
            else:
                submission = await asyncio.to_thread(
                    sub.submit, title=title, selftext=copy
                )

            post_id = str(submission.id)
            logger.info("reddit_post_success", submission_id=post_id, subreddit=sub_name)

            return PostResult(
                success=True,
                platform_post_id=post_id,
                request_fingerprint=fingerprint,
            )

        except praw.exceptions.RedditAPIException as e:
            error_items = e.items if hasattr(e, "items") else []
            error_msg = str(e)

            # Check for rate limit
            is_rate_limit = any(
                getattr(item, "error_type", "") == "RATELIMIT"
                for item in error_items
            )

            if is_rate_limit:
                logger.warning("reddit_rate_limit", error=error_msg)
                return PostResult(
                    success=False,
                    error_code="RATE_LIMIT",
                    error_message=error_msg,
                    provider_status_code=429,
                    is_retryable=True,
                    request_fingerprint=fingerprint,
                )

            logger.error("reddit_api_error", error=error_msg)
            return PostResult(
                success=False,
                error_code="REDDIT_API_ERROR",
                error_message=error_msg,
                is_retryable=True,
                request_fingerprint=fingerprint,
            )

        except Exception as e:
            logger.error("reddit_unexpected_error", error=str(e))
            return PostResult(
                success=False,
                error_code="UNEXPECTED_ERROR",
                error_message=str(e),
                is_retryable=False,
                request_fingerprint=fingerprint,
            )
