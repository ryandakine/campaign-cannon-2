# Campaign Cannon 2

Universal Automated Social Media Campaign Engine with AI Agent API.

Ground-up rebuild of Campaign Cannon v1 — async-only database, complete MCP server, persistent rate limits, guaranteed delivery tracking, and a real-time dashboard.

## What's New in v2

| Area | v1 Problem | v2 Fix |
|------|-----------|--------|
| Database | Mixed sync/async engines | Async-only via `aiosqlite` |
| Transactions | Missing rollback guarantees | `unit_of_work()` context manager |
| Delivery tracking | `DeliveryAttempt` not persisted | Atomic persist in same transaction |
| Rate limits | In-memory only, lost on restart | Persisted in `rate_limit_logs` table |
| MCP server | Incomplete, truncated tools | All 9 tools fully implemented |
| Post service | Missing entirely | Full CRUD with dedup keys |
| Dashboard | No backend | Complete service + REST + UI |
| Exceptions | Missing classes, bare `except` | Typed hierarchy with status codes |
| Stale locks | No cleanup | Automatic cleanup scheduler job |
| State machines | Documented but not enforced | `can_transition_to()` + dict lookups |

## Quick Start

```bash
# Clone and set up
git clone <repo-url> && cd campaign-cannon-2
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env with your Twitter/Reddit credentials

# Run
python run.py
# API available at http://127.0.0.1:8000
# Dashboard at http://127.0.0.1:8000/api/v1/dashboard
```

## Architecture

```
campaign-cannon-2/
├── src/
│   ├── api/              # FastAPI app, routes, deps, schemas
│   │   ├── app.py        # App factory + lifespan
│   │   ├── deps.py       # DB session + auth dependencies
│   │   └── routes/       # campaigns, posts, import/export, dashboard, system
│   ├── db/               # Async-only database layer
│   │   ├── database.py   # Engine + session factory
│   │   ├── models.py     # SQLAlchemy 2.0 models + enums + state machines
│   │   └── unit_of_work.py  # Transaction context manager
│   ├── services/         # Business logic (no HTTP concerns)
│   │   ├── campaign_service.py
│   │   ├── post_service.py
│   │   ├── execution_service.py
│   │   ├── rate_limit_service.py
│   │   ├── schedule_service.py
│   │   ├── asset_service.py
│   │   ├── import_service.py
│   │   └── dashboard_service.py
│   ├── adapters/         # Platform posting (Twitter, Reddit)
│   ├── scheduler/        # APScheduler periodic jobs
│   ├── worker/           # Post execution loop
│   ├── mcp_server/       # MCP stdio server (9 tools)
│   ├── schemas/          # Pydantic v2 request/response models
│   ├── config.py         # TOML + env config loader
│   └── exceptions.py     # Typed exception hierarchy
├── templates/            # Dashboard HTML (Jinja2)
├── static/               # CSS + JS for dashboard
├── tests/                # pytest-asyncio test suite
├── run.py                # Entry point (uvicorn + scheduler)
├── config.toml           # Application configuration
├── Dockerfile            # Multi-stage, non-root
└── docker-compose.yml    # api, mcp-server, dev, test
```

## API Endpoints

### Campaigns
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/campaigns` | Create campaign |
| GET | `/api/v1/campaigns` | List campaigns |
| GET | `/api/v1/campaigns/{slug}` | Get campaign |
| PUT | `/api/v1/campaigns/{slug}` | Update draft campaign |
| POST | `/api/v1/campaigns/{slug}/activate` | Activate |
| POST | `/api/v1/campaigns/{slug}/pause` | Pause |
| POST | `/api/v1/campaigns/{slug}/resume` | Resume |
| POST | `/api/v1/campaigns/{slug}/cancel` | Cancel |
| GET | `/api/v1/campaigns/{slug}/status` | Detailed status |

### Posts
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/campaigns/{slug}/posts` | List posts |
| PUT | `/api/v1/campaigns/{slug}/posts/{id}` | Update post |
| DELETE | `/api/v1/campaigns/{slug}/posts/{id}` | Delete post |

### Import/Export
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/import` | Import from JSON |
| GET | `/api/v1/campaigns/{slug}/export` | Export campaign |
| POST | `/api/v1/quick-start` | Create + activate in one call |

### Dashboard
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/dashboard` | Dashboard UI |
| GET | `/api/v1/dashboard/summary` | Campaign summary |
| GET | `/api/v1/dashboard/next-due` | Next due posts |
| GET | `/api/v1/dashboard/recent-failures` | Recent failures |
| GET | `/api/v1/dashboard/retry-queue` | Retry queue |
| GET | `/api/v1/dashboard/rate-limits` | Rate limit status |
| GET | `/api/v1/dashboard/missed-posts` | Missed posts |

## MCP Server

The MCP server exposes 9 tools for AI agent integration:

- `campaign_create` — Create a new campaign
- `campaign_import` — Import campaign from JSON
- `campaign_activate` / `campaign_pause` / `campaign_resume` / `campaign_cancel`
- `campaign_status` — Get detailed status
- `post_list` — List posts for a campaign
- `post_update` — Update a post

Run standalone:
```bash
python -m src.mcp_server.server
```

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ --cov=src --cov-report=term-missing

# Single test file
python -m pytest tests/test_campaign_service.py -v
```

## Docker

```bash
# Production
docker compose up api

# Development (with hot reload)
docker compose up dev

# Run tests
docker compose run test

# MCP server
docker compose up mcp-server
```

## Configuration

Edit `config.toml` for application settings and `.env` for secrets.

Key environment variables:
- `TWITTER_CONSUMER_KEY`, `TWITTER_CONSUMER_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_SECRET`
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD`
- `API_TOKEN` — Bearer token for remote API access
- `DATABASE_URL` — Override database connection string
- `DEBUG` — Enable debug mode and hot reload

## License

MIT
