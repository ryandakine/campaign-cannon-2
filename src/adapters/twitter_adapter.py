"""Twitter/X adapter — posting via Tweepy."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import structlog
import tweepy

from src.adapters.base import BaseAdapter, PostResult
from src.config import (
    TWITTER_ACCESS_SECRET,
    TWITTER_ACCESS_TOKEN,
    TWITTER_CONSUMER_KEY,
    TWITTER_CONSUMER_SECRET,
)

logger = structlog.get_logger()


class TwitterAdapter(BaseAdapter):
    platform = "twitter"

    def __init__(self) -> None:
        self._client: tweepy.Client | None = None
        self._api: tweepy.API | None = None

    def is_configured(self) -> bool:
        return all([
            TWITTER_CONSUMER_KEY,
            TWITTER_CONSUMER_SECRET,
            TWITTER_ACCESS_TOKEN,
            TWITTER_ACCESS_SECRET,
        ])

    def _get_client(self) -> tweepy.Client:
        if not self._client:
            self._client = tweepy.Client(
                consumer_key=TWITTER_CONSUMER_KEY,
                consumer_secret=TWITTER_CONSUMER_SECRET,
                access_token=TWITTER_ACCESS_TOKEN,
                access_token_secret=TWITTER_ACCESS_SECRET,
            )
        return self._client

    def _get_api(self) -> tweepy.API:
        """Legacy API v1.1 for media uploads."""
        if not self._api:
            auth = tweepy.OAuth1UserHandler(
                TWITTER_CONSUMER_KEY,
                TWITTER_CONSUMER_SECRET,
                TWITTER_ACCESS_TOKEN,
                TWITTER_ACCESS_SECRET,
            )
            self._api = tweepy.API(auth)
        return self._api

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
        fingerprint = hashlib.sha256(f"{copy}:{media_path}".encode()).hexdigest()[:16]

        try:
            client = self._get_client()

            # Append hashtags to copy
            text = copy
            if hashtags:
                tag_str = " ".join(f"#{h}" if not h.startswith("#") else h for h in hashtags)
                text = f"{copy} {tag_str}"

            media_ids = None
            if media_path and media_path.exists():
                api = self._get_api()
                media = await asyncio.to_thread(api.media_upload, str(media_path))
                media_ids = [media.media_id]

            response = await asyncio.to_thread(client.create_tweet, text=text, media_ids=media_ids)

            tweet_id = str(response.data["id"]) if response.data else None
            logger.info("twitter_post_success", tweet_id=tweet_id)

            return PostResult(
                success=True,
                platform_post_id=tweet_id,
                request_fingerprint=fingerprint,
            )

        except tweepy.TooManyRequests as e:
            logger.warning("twitter_rate_limit", error=str(e))
            return PostResult(
                success=False,
                error_code="RATE_LIMIT",
                error_message=str(e),
                provider_status_code=429,
                is_retryable=True,
                request_fingerprint=fingerprint,
            )

        except tweepy.Unauthorized as e:
            logger.error("twitter_auth_error", error=str(e))
            return PostResult(
                success=False,
                error_code="AUTH_ERROR",
                error_message="Twitter authentication failed",
                provider_status_code=401,
                is_retryable=False,
                request_fingerprint=fingerprint,
            )

        except tweepy.Forbidden as e:
            logger.error("twitter_forbidden", error=str(e))
            return PostResult(
                success=False,
                error_code="FORBIDDEN",
                error_message=str(e),
                provider_status_code=403,
                is_retryable=False,
                request_fingerprint=fingerprint,
            )

        except tweepy.TweepyException as e:
            logger.error("twitter_error", error=str(e))
            return PostResult(
                success=False,
                error_code="TWEEPY_ERROR",
                error_message=str(e),
                is_retryable=True,
                request_fingerprint=fingerprint,
            )

        except Exception as e:
            logger.error("twitter_unexpected_error", error=str(e))
            return PostResult(
                success=False,
                error_code="UNEXPECTED_ERROR",
                error_message=str(e),
                is_retryable=False,
                request_fingerprint=fingerprint,
            )
