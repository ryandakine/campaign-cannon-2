# Campaign Cannon v3.1

Bulletproof social media automation engine. JSON-first campaign import, state machine execution, multi-platform adapters.

> "Reliable delivery engine only — not another marketing brain."

## Status: Under Construction 🚧

## Architecture

```
Pomelli (content) → JSON Import → Campaign Cannon → Twitter/X, Reddit, LinkedIn
                                        ↓
                              State Machine + Scheduler
                              SQLite + APScheduler
                              REST API + MCP Server
```

## Quick Start

```bash
cp .env.example .env
# Fill in your API credentials
pip install -e ".[dev]"
campaign-cannon
```

## Tech Stack

- Python 3.11+
- SQLAlchemy 2.0 + Alembic (SQLite with WAL)
- FastAPI + Uvicorn
- APScheduler 3.x
- Tweepy, PRAW, httpx (platform adapters)
- Pydantic v2 (config + validation)
- structlog (JSON logging)
