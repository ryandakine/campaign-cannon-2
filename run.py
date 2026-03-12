#!/usr/bin/env python3
"""Campaign Cannon 2 — Application entry point."""

from __future__ import annotations

import uvicorn

from src.api.app import create_app
from src.config import API_HOST, API_PORT, DEBUG, LOG_LEVEL

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "run:app",
        host=API_HOST,
        port=API_PORT,
        reload=DEBUG,
        log_level=LOG_LEVEL.lower(),
    )
