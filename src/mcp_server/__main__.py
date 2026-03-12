"""Campaign Cannon 2 — MCP server entry point."""

import asyncio

from src.mcp_server.server import run_server

if __name__ == "__main__":
    asyncio.run(run_server())
