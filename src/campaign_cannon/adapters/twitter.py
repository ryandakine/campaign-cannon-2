"""Twitter/X platform adapter using Tweepy with OAuth2 user-context.

Rate limit note: X free tier allows 300 posts / 3 hours.  Tracked by the
engine's rate_limiter module.  Upgrade to Basic tier if you need higher
throughput.

publish() NEVER raises — all errors are captured in PlatformResult.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Optional

import structlog

from campaign_cannon.adapters.base import BaseAdapter, PlatformResult

if TYPE_CHECKING:
    from campaign_cannon.db.models import MediaAsset, Platform, Post

logger = structlog.get_logger(__name__)

# Tweepy is an optional runtime dependency — imported lazily so that
# environments without tweepy installed fail at publish-time, not import-time.
_tweepy = None


def _get_tweepy():
    global _tweepy
    if _tweepy is None:
        import tweepy  # type: ignore[import-untyped]

        _tweepy = tweepy
    return _tweepy


class TwitterAdapter(BaseAdapter):
    """Adapter for Twitter/X using Tweepy OAuth2 user-context.

    Credentials dict must contain:
        - bearer_token: str
        - consumer_key: str
        - consumer_secret: str
        - access_token: str
        - access_token_secret: str
    """

    def __init__(self, credentials: dict[str, str]) -> None:
        self._credentials = credentials
        self._client: Any = None
        self._api: Any = None  # v1.1 API for media upload

    # -- lazy client setup ---------------------------------------------------

    def _ensure_client(self) -> None:
        """Build tweepy Client and API objects on first use."""
        if self._client is not None:
            return
        tweepy = _get_tweepy()
        self._client = tweepy.Client(
            bearer_token=self._credentials.get("bearer_token"),
            consumer_key=self._credentials["consumer_key"],
            consumer_secret=self._credentials["consumer_secret"],
            access_token=self._credentials["access_token"],
            access_token_secret=self._credentials["access_token_secret"],
            wait_on_rate_limit=False,
        )
        # v1.1 auth is needed for media upload
        auth = tweepy.OAuth1UserHandler(
            consumer_key=self._credentials["consumer_key"],
            consumer_secret=self._credentials["consumer_secret"],
            access_token=self._credentials["access_token"],
            access_token_secret=self._credentials["access_token_secret"],
        )
        self._api = tweepy.API(auth)

    # -- BaseAdapter implementation -----------------------------------------

    @property
    def platform(self) -> Platform:
        from campaign_cannon.db.models import Platform

        return Platform.TWITTER

    def publish(self, post: Post, media_assets: list[MediaAsset]) -> PlatformResult:
        """Publish a tweet (text, image, or thread).

        Thread detection: if post.metadata contains ``"thread": true`` and the
        body has multiple paragraphs separated by ``\\n---\\n``, each paragraph
        is posted as a separate tweet in a reply chain.
        """
        try:
            self._ensure_client()

            metadata = post.metadata or {}
            is_thread = metadata.get("thread", False)

            if is_thread:
                return self._publish_thread(post, media_assets)

            return self._publish_single(post, media_assets)

        except Exception as exc:
            return self._handle_exception(exc)

    def validate_credentials(self) -> bool:
        """Verify credentials by calling GET /2/users/me."""
        try:
            self._ensure_client()
            resp = self._client.get_me()
            return resp is not None and resp.data is not None
        except Exception:
            logger.exception("twitter_credential_validation_failed")
            return False

    def delete_post(self, platform_post_id: str) -> bool:
        """Best-effort tweet deletion."""
        try:
            self._ensure_client()
            self._client.delete_tweet(int(platform_post_id))
            return True
        except Exception:
            logger.exception("twitter_delete_failed", tweet_id=platform_post_id)
            return False

    # -- internal helpers ---------------------------------------------------

    def _upload_media(self, media_assets: list[MediaAsset]) -> list[int]:
        """Upload images via v1.1 API, return media_ids."""
        media_ids: list[int] = []
        for asset in media_assets:
            media = self._api.media_upload(filename=asset.file_path)
            media_ids.append(media.media_id)
        return media_ids

    def _publish_single(
        self,
        post: Post,
        media_assets: list[MediaAsset],
        in_reply_to: Optional[int] = None,
    ) -> PlatformResult:
        """Publish a single tweet, optionally as a reply."""
        kwargs: dict[str, Any] = {"text": post.body}

        if media_assets:
            media_ids = self._upload_media(media_assets)
            kwargs["media_ids"] = media_ids

        if in_reply_to:
            kwargs["in_reply_to_tweet_id"] = in_reply_to

        resp = self._client.create_tweet(**kwargs)
        tweet_id = str(resp.data["id"])
        tweet_url = f"https://x.com/i/status/{tweet_id}"

        logger.info("twitter_published", tweet_id=tweet_id, url=tweet_url)
        return PlatformResult.ok(
            platform_post_id=tweet_id,
            platform_post_url=tweet_url,
        )

    def _publish_thread(
        self,
        post: Post,
        media_assets: list[MediaAsset],
    ) -> PlatformResult:
        """Publish a thread of tweets.

        Body is split on ``\\n---\\n``.  Media is attached only to the first
        tweet.  Returns the PlatformResult for the first tweet (head of thread).
        """
        parts = [p.strip() for p in (post.body or "").split("\n---\n") if p.strip()]
        if not parts:
            return PlatformResult.fail("EMPTY_BODY", "Thread body is empty")

        # First tweet — with media
        first_kwargs: dict[str, Any] = {"text": parts[0]}
        if media_assets:
            first_kwargs["media_ids"] = self._upload_media(media_assets)

        resp = self._client.create_tweet(**first_kwargs)
        head_id = int(resp.data["id"])
        head_url = f"https://x.com/i/status/{head_id}"
        previous_id = head_id

        # Subsequent tweets
        for part in parts[1:]:
            resp = self._client.create_tweet(
                text=part,
                in_reply_to_tweet_id=previous_id,
            )
            previous_id = int(resp.data["id"])

        logger.info(
            "twitter_thread_published",
            head_tweet_id=str(head_id),
            tweet_count=len(parts),
        )
        return PlatformResult.ok(
            platform_post_id=str(head_id),
            platform_post_url=head_url,
            metadata={"thread_length": len(parts)},
        )

    def _handle_exception(self, exc: Exception) -> PlatformResult:
        """Map tweepy / network exceptions to PlatformResult."""
        tweepy = _get_tweepy()

        if isinstance(exc, tweepy.TooManyRequests):
            reset_time = None
            try:
                reset_epoch = int(exc.response.headers.get("x-rate-limit-reset", 0))
                if reset_epoch:
                    from datetime import datetime, timezone

                    reset_time = datetime.fromtimestamp(reset_epoch, tz=timezone.utc)
            except (ValueError, TypeError):
                pass

            logger.warning("twitter_rate_limited", reset=str(reset_time))
            return PlatformResult.fail(
                error_code="429",
                error_message="Twitter rate limit hit",
                retryable=True,
                rate_limit_reset=reset_time,
            )

        if isinstance(exc, tweepy.Forbidden):
            # 403 often means duplicate content
            msg = str(exc)
            logger.warning("twitter_forbidden", detail=msg)
            return PlatformResult.fail(
                error_code="403",
                error_message=f"Forbidden: {msg}",
                retryable=False,
            )

        if isinstance(exc, tweepy.Unauthorized):
            logger.error("twitter_unauthorized")
            return PlatformResult.fail(
                error_code="401",
                error_message="Twitter credentials invalid or expired",
                retryable=False,
            )

        if isinstance(exc, tweepy.TweepyException):
            logger.exception("twitter_api_error", error=str(exc))
            return PlatformResult.fail(
                error_code="TWEEPY_ERROR",
                error_message=str(exc),
                retryable=True,
            )

        # Unexpected error
        logger.exception("twitter_unexpected_error", error=str(exc))
        return PlatformResult.fail(
            error_code="UNEXPECTED",
            error_message=str(exc),
            retryable=True,
        )
