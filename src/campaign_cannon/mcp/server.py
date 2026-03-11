"""MCP (Machine Control Protocol) stdio server for Campaign Cannon v3.1.

Provides 5 lifecycle tools for AI agent integration:
  - import_campaign
  - activate_campaign
  - get_campaign_status
  - pause_campaign
  - resume_campaign

Run via: python -m campaign_cannon.mcp.server
"""

from __future__ import annotations

import json
import sys

import structlog

from campaign_cannon.mcp.tools import (
    tool_activate_campaign,
    tool_get_campaign_status,
    tool_import_campaign,
    tool_pause_campaign,
    tool_resume_campaign,
)

logger = structlog.get_logger("campaign_cannon.mcp.server")

BANNER = "Campaign Cannon MCP (Machine Control Protocol) Server v3.1"

# ── Tool Registry ───────────────────────────────────────────────────────────

TOOLS = {
    "import_campaign": {
        "description": "Import a new campaign with posts and media assets",
        "input_schema": {
            "type": "object",
            "required": ["name", "slug", "posts"],
            "properties": {
                "name": {"type": "string", "description": "Campaign display name"},
                "slug": {
                    "type": "string",
                    "description": "URL-safe unique identifier (lowercase, hyphens)",
                },
                "description": {"type": "string", "description": "Campaign description"},
                "posts": {
                    "type": "array",
                    "description": "List of posts to import",
                    "items": {
                        "type": "object",
                        "required": ["slug", "platform", "body", "scheduled_at"],
                        "properties": {
                            "slug": {"type": "string"},
                            "platform": {
                                "type": "string",
                                "enum": ["TWITTER", "REDDIT", "LINKEDIN"],
                            },
                            "title": {"type": "string", "description": "Required for Reddit"},
                            "body": {"type": "string"},
                            "scheduled_at": {
                                "type": "string",
                                "description": "ISO 8601 datetime with timezone",
                            },
                            "media_paths": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "subreddit": {"type": "string"},
                            "metadata": {"type": "object"},
                        },
                    },
                },
                "media_base_path": {"type": "string"},
                "metadata": {"type": "object"},
            },
        },
        "handler": tool_import_campaign,
    },
    "activate_campaign": {
        "description": "Activate a DRAFT campaign to start scheduling posts via APScheduler",
        "input_schema": {
            "type": "object",
            "required": ["campaign_id"],
            "properties": {
                "campaign_id": {
                    "type": "string",
                    "description": "UUID of the campaign to activate",
                },
            },
        },
        "handler": lambda args: tool_activate_campaign(args["campaign_id"]),
    },
    "get_campaign_status": {
        "description": "Get current campaign status with post state breakdown",
        "input_schema": {
            "type": "object",
            "required": ["campaign_id"],
            "properties": {
                "campaign_id": {
                    "type": "string",
                    "description": "UUID of the campaign",
                },
            },
        },
        "handler": lambda args: tool_get_campaign_status(args["campaign_id"]),
    },
    "pause_campaign": {
        "description": "Pause an ACTIVE campaign — removes scheduler jobs, keeps DB state",
        "input_schema": {
            "type": "object",
            "required": ["campaign_id"],
            "properties": {
                "campaign_id": {
                    "type": "string",
                    "description": "UUID of the campaign to pause",
                },
            },
        },
        "handler": lambda args: tool_pause_campaign(args["campaign_id"]),
    },
    "resume_campaign": {
        "description": "Resume a PAUSED campaign — re-creates scheduler jobs",
        "input_schema": {
            "type": "object",
            "required": ["campaign_id"],
            "properties": {
                "campaign_id": {
                    "type": "string",
                    "description": "UUID of the campaign to resume",
                },
            },
        },
        "handler": lambda args: tool_resume_campaign(args["campaign_id"]),
    },
}


# ── JSON-RPC Protocol ───────────────────────────────────────────────────────


def _make_response(id: int | str | None, result: dict) -> dict:
    """Build a JSON-RPC 2.0 success response."""
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _make_error(id: int | str | None, code: int, message: str, data: dict | None = None) -> dict:
    """Build a JSON-RPC 2.0 error response."""
    error: dict = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": id, "error": error}


def handle_request(request: dict) -> dict:
    """Process a single JSON-RPC request.

    Supports the MCP protocol methods:
      - initialize: handshake
      - tools/list: enumerate available tools
      - tools/call: execute a tool
    """
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return _make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "campaign-cannon",
                "version": "3.1.0",
            },
        })

    if method == "notifications/initialized":
        # Client acknowledgment — no response needed for notifications
        return _make_response(req_id, {})

    if method == "tools/list":
        tool_list = []
        for name, tool_def in TOOLS.items():
            tool_list.append({
                "name": name,
                "description": tool_def["description"],
                "inputSchema": tool_def["input_schema"],
            })
        return _make_response(req_id, {"tools": tool_list})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name not in TOOLS:
            return _make_error(
                req_id, -32601, f"Unknown tool: {tool_name}",
                {"available": list(TOOLS.keys())},
            )

        tool = TOOLS[tool_name]
        handler = tool["handler"]

        try:
            # For import_campaign, pass the full arguments dict
            if tool_name == "import_campaign":
                result = handler(arguments)
            else:
                result = handler(arguments)
            return _make_response(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}],
            })
        except Exception as exc:
            logger.exception("tool_execution_error", tool=tool_name, error=str(exc))
            return _make_error(req_id, -32000, f"Tool execution failed: {exc}")

    return _make_error(req_id, -32601, f"Unknown method: {method}")


# ── Stdio Transport ─────────────────────────────────────────────────────────


def run_stdio_server() -> None:
    """Run the MCP server over stdin/stdout using JSON-RPC 2.0."""
    print(BANNER, file=sys.stderr)
    logger.info("mcp_server_started", transport="stdio")

    # Initialize database and scheduler for standalone MCP usage
    from campaign_cannon.db.connection import init_db
    from campaign_cannon.engine.scheduler import start_scheduler

    init_db()
    start_scheduler()

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                error_response = _make_error(None, -32700, f"Parse error: {exc}")
                sys.stdout.write(json.dumps(error_response) + "\n")
                sys.stdout.flush()
                continue

            response = handle_request(request)
            sys.stdout.write(json.dumps(response, default=str) + "\n")
            sys.stdout.flush()
    except KeyboardInterrupt:
        logger.info("mcp_server_shutdown", reason="keyboard_interrupt")
    finally:
        from campaign_cannon.engine.scheduler import shutdown_scheduler

        shutdown_scheduler()
        logger.info("mcp_server_stopped")


if __name__ == "__main__":
    run_stdio_server()
