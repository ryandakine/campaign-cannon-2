"""Campaign Cannon MCP (Machine Control Protocol) server package."""

from campaign_cannon.mcp.server import run_stdio_server
from campaign_cannon.mcp.tools import (
    MCPError,
    MCPResult,
    tool_activate_campaign,
    tool_get_campaign_status,
    tool_import_campaign,
    tool_pause_campaign,
    tool_resume_campaign,
)

__all__ = [
    "run_stdio_server",
    "MCPError",
    "MCPResult",
    "tool_activate_campaign",
    "tool_get_campaign_status",
    "tool_import_campaign",
    "tool_pause_campaign",
    "tool_resume_campaign",
]
