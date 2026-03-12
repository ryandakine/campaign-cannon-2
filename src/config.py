"""Campaign Cannon 2 — Configuration loader.

Loads config from config.toml + environment variables (.env).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import tomli
from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG: dict[str, Any] | None = None


def _load_toml() -> dict[str, Any]:
    global _CONFIG
    if _CONFIG is None:
        config_path = _ROOT / "config.toml"
        if config_path.exists():
            with open(config_path, "rb") as f:
                _CONFIG = tomli.load(f)
        else:
            _CONFIG = {}
    return _CONFIG


def _get(section: str, key: str, default: Any = None) -> Any:
    cfg = _load_toml()
    return cfg.get(section, {}).get(key, default)


# --- General ---
API_HOST: str = _get("general", "api_host", "127.0.0.1")
API_PORT: int = int(_get("general", "api_port", 8000))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", _get("general", "log_level", "INFO"))
DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

# --- Scheduler ---
SCHEDULER_ENABLED: bool = _get("scheduler", "enabled", True)
CHECK_INTERVAL_SEC: int = int(_get("scheduler", "check_interval_sec", 60))
MAX_RETRIES: int = int(_get("scheduler", "max_retries", 3))
BACKOFF_BASE_SEC: int = int(_get("scheduler", "backoff_base_sec", 60))
MISSED_POST_WINDOW_MIN: int = int(_get("scheduler", "missed_post_window_min", 30))
CATCH_UP_MAX_LATENESS_MIN: int = int(_get("scheduler", "catch_up_max_lateness_min", 1440))
LOCK_TTL_SEC: int = int(_get("scheduler", "lock_ttl_sec", 300))

# --- Rate limits ---
TWITTER_TWEETS_PER_3H: int = int(_get("rate_limits", "twitter_tweets_per_3h", 300))
REDDIT_POSTS_PER_MIN: int = int(_get("rate_limits", "reddit_posts_per_minute", 10))

# --- Media ---
MAX_IMAGE_MB: int = int(_get("media", "max_image_mb", 20))
MAX_VIDEO_MB: int = int(_get("media", "max_video_mb", 512))
LOCAL_STORAGE_PATH: Path = Path(_get("media", "local_storage_path", "./campaigns"))

# --- Security ---
ALLOW_REMOTE: bool = os.getenv("ALLOW_REMOTE", str(_get("security", "allow_remote", False))).lower() == "true"
DASHBOARD_ENABLED: bool = os.getenv("DASHBOARD_ENABLED", str(_get("security", "dashboard_enabled", True))).lower() == "true"
API_TOKEN: str | None = os.getenv("API_TOKEN") or None
CORS_ORIGINS: list[str] = _get("security", "cors_origins", ["http://localhost:8000"])

# --- Platform credentials ---
TWITTER_CONSUMER_KEY: str = os.getenv("TWITTER_CONSUMER_KEY", "")
TWITTER_CONSUMER_SECRET: str = os.getenv("TWITTER_CONSUMER_SECRET", "")
TWITTER_ACCESS_TOKEN: str = os.getenv("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_SECRET: str = os.getenv("TWITTER_ACCESS_SECRET", "")

REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USERNAME: str = os.getenv("REDDIT_USERNAME", "")
REDDIT_PASSWORD: str = os.getenv("REDDIT_PASSWORD", "")

# --- Database ---
DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{_ROOT / 'data' / 'campaign_cannon.db'}")
