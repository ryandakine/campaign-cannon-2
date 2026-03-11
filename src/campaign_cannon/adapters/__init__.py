"""Platform adapters for Campaign Cannon.

Each adapter implements BaseAdapter and handles publishing to a specific
social media platform.  Use ``get_adapter()`` from the registry to
instantiate the correct adapter by platform.
"""

from campaign_cannon.adapters.base import BaseAdapter, PlatformResult
from campaign_cannon.adapters.linkedin import LinkedInAdapter
from campaign_cannon.adapters.reddit import RedditAdapter
from campaign_cannon.adapters.registry import get_adapter, register_adapter
from campaign_cannon.adapters.twitter import TwitterAdapter

__all__ = [
    "BaseAdapter",
    "PlatformResult",
    "TwitterAdapter",
    "RedditAdapter",
    "LinkedInAdapter",
    "get_adapter",
    "register_adapter",
]
