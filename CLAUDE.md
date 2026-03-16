# Campaign Cannon 2 — AI Assistant Guide

## Project Overview

Campaign Cannon is a bulletproof social media automation engine. It schedules and posts content to Twitter/X and Reddit, tracks delivery with guaranteed atomicity, enforces persistent platform rate limits, and exposes the entire system to AI agents via a fully-implemented MCP stdio server.

This is a ground-up rebuild (v2) with stricter correctness guarantees than the original.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 |
| API Framework | FastAPI + Uvicorn |
| Database | SQLite (async SQLAlchemy 2.0 + aiosqlite) |
| Social APIs | Tweepy (Twitter/X), PRAW (Reddit) |
| Scheduler | APScheduler |
| MCP Server | mcp>=1.0.0 (9 tools, stdio transport) |
| Validation | Pydantic v2 |
| Config | TOML + .env |
| Logging | structlog |
| Containerization | Docker + docker-compose (multi-stage, non-root) |

## Repository Structure

```
src/
  api/          FastAPI app, routes, dependencies, schemas
  db/           Async engine, SQLAlchemy models, unit_of_work context manager
  services/     Business logic: campaign, post, execution, rate_limit, schedule, asset, import, dashboard
  adapters/     Platform adapters — Twitter and Reddit posting implementations
  scheduler/    APScheduler periodic jobs (stale lock cleanup, etc.)
  worker/       Post execution loop
  mcp_server/   MCP stdio server with 9 tools
  schemas/      Pydantic v2 request/response models
  exceptions.py Typed exception hierarchy
templates/      Jinja2 dashboard HTML
static/         CSS + JS assets
tests/          pytest-asyncio test suite
run.py          Main entry point (starts uvicorn + scheduler together)
```

## Key Commands

```bash
# Install
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Configure
cp .env.example .env   # Fill in Twitter/Reddit API credentials

# Run API server (REST + dashboard)
python run.py          # http://127.0.0.1:8000

# Run standalone MCP server
python -m src.mcp_server.server

# Docker (production)
docker compose up api

# Docker (dev, hot reload)
docker compose up dev

# Docker (MCP server)
docker compose up mcp-server
```

## Testing

```bash
pytest tests/ -v
pytest tests/ --cov=src --cov-report=term-missing
docker compose run test
```

Test files cover: campaign service, post service, execution service, rate limit service, state machines, API integration. All tests are async (pytest-asyncio).

## Architecture Patterns

### Unit of Work
All database mutations go through the UnitOfWork context manager in src/db/. This guarantees atomicity — never bypass it with raw sessions.

```python
async with UnitOfWork() as uow:
    await uow.campaigns.add(campaign)
    await uow.commit()
```

### State Machine
Post and campaign states follow a strict transition table. Always use can_transition_to() before mutating state. Never set state directly without going through the state machine.

Valid post states: queued → executing → completed / failed
Valid campaign states: draft → active → paused → completed / archived

### Rate Limiting
Rate limits are persistent (stored in SQLite), not in-memory. The RateLimitService must be consulted before every post attempt. Do not add sleep-based throttling — the rate limit service handles backoff.

### MCP Server
The MCP server at src/mcp_server/server.py exposes 9 tools to AI agents. When adding new capabilities, consider whether they should be exposed as MCP tools. The MCP server runs independently of the REST API and can be started without it.

## Environment Variables

| Variable | Description |
|----------|-------------|
| TWITTER_API_KEY | Twitter/X API key |
| TWITTER_API_SECRET | Twitter/X API secret |
| TWITTER_ACCESS_TOKEN | Twitter/X access token |
| TWITTER_ACCESS_SECRET | Twitter/X access token secret |
| REDDIT_CLIENT_ID | Reddit app client ID |
| REDDIT_CLIENT_SECRET | Reddit app client secret |
| REDDIT_USERNAME | Reddit account username |
| REDDIT_PASSWORD | Reddit account password |
| DATABASE_URL | SQLite path (default: sqlite+aiosqlite:///./campaign_cannon.db) |

## Important Constraints

- All database access must be async. Never use synchronous SQLAlchemy sessions.
- Never bypass the UnitOfWork pattern for writes — it exists to prevent partial state.
- State transitions must go through the state machine — never set .status directly.
- Rate limits are stored, not computed — do not re-derive them from API responses.
- The REST API and MCP server share the same database but can run independently.
- Docker images run as non-root — do not add steps that require root.

## Adding New Platforms

1. Create an adapter in src/adapters/ implementing the PlatformAdapter abstract interface.
2. Register it in the adapter factory.
3. Add rate limit config for the platform in src/services/rate_limit.py.
4. Add credentials to .env.example and document them above.
5. Add integration tests in tests/.
