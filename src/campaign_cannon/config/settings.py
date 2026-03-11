"""Application settings for Campaign Cannon.

Loads configuration from .env (secrets) and config.toml (non-secrets),
with environment variables taking precedence. All env vars use the
``CANNON_`` prefix.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_toml_defaults() -> dict:
    """Load config.toml and flatten into a dict suitable for Pydantic defaults."""
    candidates = [
        Path("config.toml"),
        Path(__file__).resolve().parents[3] / "config.toml",
    ]
    for path in candidates:
        if path.exists():
            with open(path, "rb") as f:
                raw = tomllib.load(f)
            flat: dict = {}
            for section_values in raw.values():
                if isinstance(section_values, dict):
                    flat.update(section_values)
            return flat
    return {}


_TOML = _load_toml_defaults()


class Settings(BaseSettings):
    """Central settings for Campaign Cannon, validated by Pydantic."""

    model_config = SettingsConfigDict(
        env_prefix="CANNON_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── General ────────────────────────────────────────────────────────
    app_name: str = _TOML.get("app_name", "Campaign Cannon")
    version: str = _TOML.get("version", "3.1.0")
    log_level: str = _TOML.get("log_level", "INFO")
    log_format: str = _TOML.get("log_format", "json")

    # ── Database ───────────────────────────────────────────────────────
    db_path: str = _TOML.get("path", "./data/campaign_cannon.db")

    # ── Master encryption key (Fernet base64-encoded) ──────────────────
    master_key: str = Field(default="")

    # ── Scheduler ──────────────────────────────────────────────────────
    misfire_grace_time: int = _TOML.get("misfire_grace_time", 300)
    max_concurrent_publishes: int = _TOML.get("max_concurrent_publishes", 3)
    stuck_post_timeout: int = _TOML.get("stuck_post_timeout", 300)

    # ── Retry ──────────────────────────────────────────────────────────
    max_retries: int = _TOML.get("max_retries", 3)
    backoff_base: int = _TOML.get("backoff_base", 30)
    backoff_multiplier: int = _TOML.get("backoff_multiplier", 4)

    # ── Rate limits ────────────────────────────────────────────────────
    twitter_posts_per_window: int = _TOML.get("twitter_posts_per_window", 300)
    twitter_window_seconds: int = _TOML.get("twitter_window_seconds", 10800)
    reddit_posts_per_minute: int = _TOML.get("reddit_posts_per_minute", 1)
    linkedin_posts_per_day: int = _TOML.get("linkedin_posts_per_day", 100)

    # ── Media ──────────────────────────────────────────────────────────
    max_image_size_mb: int = _TOML.get("max_image_size_mb", 20)
    max_video_size_mb: int = _TOML.get("max_video_size_mb", 512)

    # ── API ────────────────────────────────────────────────────────────
    api_host: str = _TOML.get("host", "0.0.0.0")
    api_port: int = _TOML.get("port", 8000)

    # ── Platform credentials (loaded from env) ─────────────────────────
    twitter_client_id: Optional[str] = Field(default=None, alias="TWITTER_CLIENT_ID")
    twitter_client_secret: Optional[str] = Field(default=None, alias="TWITTER_CLIENT_SECRET")
    twitter_access_token: Optional[str] = Field(default=None, alias="TWITTER_ACCESS_TOKEN")
    twitter_access_token_secret: Optional[str] = Field(
        default=None, alias="TWITTER_ACCESS_TOKEN_SECRET"
    )
    reddit_client_id: Optional[str] = Field(default=None, alias="REDDIT_CLIENT_ID")
    reddit_client_secret: Optional[str] = Field(default=None, alias="REDDIT_CLIENT_SECRET")
    reddit_username: Optional[str] = Field(default=None, alias="REDDIT_USERNAME")
    reddit_password: Optional[str] = Field(default=None, alias="REDDIT_PASSWORD")
    linkedin_client_id: Optional[str] = Field(default=None, alias="LINKEDIN_CLIENT_ID")
    linkedin_client_secret: Optional[str] = Field(default=None, alias="LINKEDIN_CLIENT_SECRET")
    linkedin_access_token: Optional[str] = Field(default=None, alias="LINKEDIN_ACCESS_TOKEN")

    # ── Alert webhook ──────────────────────────────────────────────────
    alert_webhook_url: Optional[str] = Field(default=None)

    @field_validator("db_path")
    @classmethod
    def _ensure_db_dir_exists(cls, v: str) -> str:
        """Create the parent directory for the database file if needed."""
        db_dir = Path(v).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
