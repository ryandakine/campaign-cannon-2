"""LinkedIn platform adapter using httpx for direct API calls.

Uses the LinkedIn Marketing API v2 (UGC Posts endpoint) with OAuth2
bearer-token authentication.  There is no reliable official Python SDK,
so we use httpx directly.

publish() NEVER raises — all errors are captured in PlatformResult.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import httpx
import structlog

from campaign_cannon.adapters.base import BaseAdapter, PlatformResult

if TYPE_CHECKING:
    from campaign_cannon.db.models import MediaAsset, Platform, Post

logger = structlog.get_logger(__name__)

_LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
_UGC_POSTS_URL = f"{_LINKEDIN_API_BASE}/ugcPosts"
_UPLOAD_URL = f"{_LINKEDIN_API_BASE}/assets?action=registerUpload"
_ME_URL = f"{_LINKEDIN_API_BASE}/me"

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class LinkedInAdapter(BaseAdapter):
    """Adapter for LinkedIn using httpx with OAuth2 bearer token.

    Credentials dict must contain:
        - access_token: str (OAuth2 bearer token)
        - person_urn: str (e.g. "urn:li:person:XXXXXXX")

    Optional:
        - refresh_token: str
        - client_id: str
        - client_secret: str
        (needed for token refresh flow)
    """

    def __init__(self, credentials: dict[str, str]) -> None:
        self._credentials = credentials
        self._access_token: str = credentials["access_token"]
        self._person_urn: str = credentials["person_urn"]

    # -- helpers -------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

    def _refresh_token_if_needed(self) -> bool:
        """Attempt to refresh the OAuth2 token.

        Returns True if a new token was obtained, False otherwise.
        Requires refresh_token, client_id, and client_secret in credentials.
        """
        refresh_token = self._credentials.get("refresh_token")
        client_id = self._credentials.get("client_id")
        client_secret = self._credentials.get("client_secret")

        if not all([refresh_token, client_id, client_secret]):
            return False

        try:
            resp = httpx.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            logger.info("linkedin_token_refreshed")
            return True
        except Exception:
            logger.exception("linkedin_token_refresh_failed")
            return False

    # -- BaseAdapter implementation -----------------------------------------

    @property
    def platform(self) -> Platform:
        from campaign_cannon.db.models import Platform

        return Platform.LINKEDIN

    def publish(self, post: Post, media_assets: list[MediaAsset]) -> PlatformResult:
        """Publish a LinkedIn UGC post (text or text + image)."""
        try:
            if media_assets:
                return self._publish_with_image(post, media_assets[0])
            return self._publish_text(post)
        except httpx.HTTPStatusError as exc:
            return self._handle_http_error(exc)
        except httpx.TimeoutException:
            logger.warning("linkedin_timeout")
            return PlatformResult.fail(
                error_code="TIMEOUT",
                error_message="LinkedIn API request timed out",
                retryable=True,
            )
        except Exception as exc:
            logger.exception("linkedin_unexpected_error", error=str(exc))
            return PlatformResult.fail(
                error_code="UNEXPECTED",
                error_message=str(exc),
                retryable=True,
            )

    def validate_credentials(self) -> bool:
        """Verify credentials by calling GET /v2/me."""
        try:
            resp = httpx.get(
                _ME_URL,
                headers=self._headers(),
                timeout=_TIMEOUT,
            )
            return resp.status_code == 200
        except Exception:
            logger.exception("linkedin_credential_validation_failed")
            return False

    def delete_post(self, platform_post_id: str) -> bool:
        """Best-effort UGC post deletion.

        LinkedIn UGC delete: DELETE /v2/ugcPosts/{post-urn}
        """
        try:
            url = f"{_UGC_POSTS_URL}/{platform_post_id}"
            resp = httpx.delete(
                url,
                headers=self._headers(),
                timeout=_TIMEOUT,
            )
            return resp.status_code in (200, 204, 404)
        except Exception:
            logger.exception("linkedin_delete_failed", post_id=platform_post_id)
            return False

    # -- publishing helpers --------------------------------------------------

    def _build_ugc_payload(
        self,
        text: str,
        media_urn: Optional[str] = None,
    ) -> dict[str, Any]:
        """Build the UGC post JSON payload."""
        share_content: dict[str, Any] = {
            "shareCommentary": {"text": text},
            "shareMediaCategory": "NONE",
        }

        if media_urn:
            share_content["shareMediaCategory"] = "IMAGE"
            share_content["media"] = [
                {
                    "status": "READY",
                    "media": media_urn,
                }
            ]

        return {
            "author": self._person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": share_content,
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC",
            },
        }

    def _publish_text(self, post: Post) -> PlatformResult:
        """Publish a text-only UGC post."""
        payload = self._build_ugc_payload(text=post.body or "")
        resp = httpx.post(
            _UGC_POSTS_URL,
            json=payload,
            headers=self._headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()

        data = resp.json()
        post_urn = data.get("id", "")
        post_url = self._urn_to_url(post_urn)

        logger.info("linkedin_published", post_urn=post_urn, url=post_url)
        return PlatformResult.ok(
            platform_post_id=post_urn,
            platform_post_url=post_url,
        )

    def _upload_image(self, media_asset: MediaAsset) -> str:
        """Upload an image to LinkedIn and return the asset URN.

        Two-step process:
        1. Register upload → get upload URL + asset URN
        2. PUT the binary image to the upload URL
        """
        # Step 1: register
        register_payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": self._person_urn,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }

        resp = httpx.post(
            _UPLOAD_URL,
            json=register_payload,
            headers=self._headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        reg_data = resp.json()

        upload_url = (
            reg_data["value"]["uploadMechanism"]
            ["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]
            ["uploadUrl"]
        )
        asset_urn = reg_data["value"]["asset"]

        # Step 2: upload binary
        with open(media_asset.file_path, "rb") as f:
            image_data = f.read()

        upload_headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": media_asset.mime_type or "application/octet-stream",
        }
        resp = httpx.put(
            upload_url,
            content=image_data,
            headers=upload_headers,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        resp.raise_for_status()

        logger.info("linkedin_image_uploaded", asset_urn=asset_urn)
        return asset_urn

    def _publish_with_image(
        self,
        post: Post,
        media_asset: MediaAsset,
    ) -> PlatformResult:
        """Upload image, then publish a UGC post referencing it."""
        asset_urn = self._upload_image(media_asset)
        payload = self._build_ugc_payload(text=post.body or "", media_urn=asset_urn)

        resp = httpx.post(
            _UGC_POSTS_URL,
            json=payload,
            headers=self._headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()

        data = resp.json()
        post_urn = data.get("id", "")
        post_url = self._urn_to_url(post_urn)

        logger.info(
            "linkedin_published_with_image",
            post_urn=post_urn,
            asset_urn=asset_urn,
            url=post_url,
        )
        return PlatformResult.ok(
            platform_post_id=post_urn,
            platform_post_url=post_url,
        )

    # -- error handling ------------------------------------------------------

    def _handle_http_error(self, exc: httpx.HTTPStatusError) -> PlatformResult:
        """Map LinkedIn HTTP errors to PlatformResult."""
        status = exc.response.status_code
        body = exc.response.text

        if status == 401:
            # Try token refresh once
            if self._refresh_token_if_needed():
                logger.info("linkedin_retrying_after_token_refresh")
                return PlatformResult.fail(
                    error_code="401_REFRESHED",
                    error_message="Token refreshed — caller should retry",
                    retryable=True,
                )
            return PlatformResult.fail(
                error_code="401",
                error_message="LinkedIn credentials invalid or expired",
                retryable=False,
            )

        if status == 429:
            logger.warning("linkedin_rate_limited")
            return PlatformResult.fail(
                error_code="429",
                error_message="LinkedIn rate limit hit",
                retryable=True,
            )

        retryable = status >= 500
        logger.warning(
            "linkedin_http_error",
            status=status,
            body=body[:500],
        )
        return PlatformResult.fail(
            error_code=str(status),
            error_message=f"LinkedIn API error {status}: {body[:200]}",
            retryable=retryable,
        )

    @staticmethod
    def _urn_to_url(urn: str) -> str:
        """Convert a LinkedIn activity URN to a public post URL.

        URN format: urn:li:share:123456789 or urn:li:ugcPost:123456789
        """
        # Extract the numeric ID from the URN
        parts = urn.split(":")
        if len(parts) >= 4:
            activity_id = parts[-1]
            return f"https://www.linkedin.com/feed/update/{urn}"
        return f"https://www.linkedin.com/feed/update/{urn}"
