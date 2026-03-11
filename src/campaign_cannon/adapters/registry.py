"""Adapter registry — maps Platform enum values to adapter classes.

Provides a factory function ``get_adapter()`` that instantiates the
correct adapter with decrypted credentials.  Extending to a new platform
only requires adding one entry to ``ADAPTER_MAP``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from campaign_cannon.adapters.base import BaseAdapter
from campaign_cannon.adapters.linkedin import LinkedInAdapter
from campaign_cannon.adapters.reddit import RedditAdapter
from campaign_cannon.adapters.twitter import TwitterAdapter

if TYPE_CHECKING:
    from campaign_cannon.db.models import Platform

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Platform → Adapter class mapping
# ---------------------------------------------------------------------------
# Use string keys so this works even before Agent 1's Platform enum lands.
# At runtime the enum values resolve to these strings.

ADAPTER_MAP: dict[str, type[BaseAdapter]] = {
    "TWITTER": TwitterAdapter,
    "REDDIT": RedditAdapter,
    "LINKEDIN": LinkedInAdapter,
}


def get_adapter(platform: Platform | str, credentials: dict[str, str]) -> BaseAdapter:
    """Instantiate the correct adapter for *platform* with *credentials*.

    Args:
        platform: A Platform enum member or its string value
                  (e.g. Platform.TWITTER or "TWITTER").
        credentials: Decrypted credential dict for the platform.

    Returns:
        An initialised BaseAdapter subclass ready to publish.

    Raises:
        ValueError: If no adapter is registered for the platform.
    """
    key = platform.value if hasattr(platform, "value") else str(platform)
    adapter_cls = ADAPTER_MAP.get(key)

    if adapter_cls is None:
        raise ValueError(
            f"No adapter registered for platform '{key}'. "
            f"Available: {list(ADAPTER_MAP.keys())}"
        )

    logger.debug("adapter_instantiated", platform=key, adapter=adapter_cls.__name__)
    return adapter_cls(credentials=credentials)


def register_adapter(platform_key: str, adapter_cls: type[BaseAdapter]) -> None:
    """Register a new adapter class for a platform.

    Useful for plugins or test doubles.

    Args:
        platform_key: Platform string key (e.g. "MASTODON").
        adapter_cls: A BaseAdapter subclass.
    """
    ADAPTER_MAP[platform_key] = adapter_cls
    logger.info("adapter_registered", platform=platform_key, adapter=adapter_cls.__name__)
