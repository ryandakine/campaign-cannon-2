# CAMPAIGN CANNON 2
## Universal Automated Social Media Campaign Engine with AI Agent API
### Product Requirements Document — Version 4.0
### March 11, 2026 | Ryan Brenny | On-Site Intelligence LLC

---

## 1. Executive Summary

Campaign Cannon 2 is a ground-up rebuild of the Campaign Cannon social media campaign execution engine. It is a single-node, API-first system for scheduled organic social posting. It accepts prepared campaign assets and copy from upstream tools or AI agents, generates or imports schedules, and executes posts across supported platforms at the correct time with full logging, retries, idempotency, and safe crash recovery.

An MCP (Model Context Protocol) server via stdio transport is included so AI agents can create campaigns, import content, schedule posts, pause/resume execution, and monitor outcomes programmatically.

### What's New in V2
- **Fully async architecture** — no sync/async mixing; single consistent database pattern
- **Proper transaction boundaries** — guaranteed rollback on failure, no orphan records
- **Persistent rate-limit tracking** — survives restarts, prevents burst-posting after recovery
- **Complete MCP server** — all 9+ tools fully implemented and tested
- **Working dashboard backend** — real API endpoints powering all dashboard widgets
- **Robust lock management** — automatic stale-lock cleanup with configurable TTL
- **Comprehensive error taxonomy** — typed exceptions, actionable error messages
- **Full type safety** — strict mypy compliance throughout
- **Timezone-aware throughout** — all datetimes stored and compared as UTC
- **DeliveryAttempt audit trail** — every attempt persisted, never lost

---

## 2. Vision Statement

Enable any AI agent or human operator to launch multi-platform social campaigns with zero manual posting. The system serves as the reliable delivery layer between content preparation (Pomelli, manual work, or other agents) and live social platforms.

---

## 3. Objectives & Success Criteria

### Primary Objectives
- Accept prepared campaign assets and copy from upstream tools or AI agents
- Generate or import schedules
- Execute posts across supported platforms at the correct time
- Provide logging, retries, and safe recovery

### Success Metrics
- Zero duplicate posts across restarts (dedup_key enforcement)
- 99.5% on-time delivery within 60-second tolerance
- Sub-5-minute setup for new campaign
- <1s API response time for status checks
- 95%+ test coverage on core services
- Zero P0 issues at launch

---

## 4. Scope

### In Scope (V2)
- Campaign CRUD (create, read, update, delete)
- Schedule generation (recurrence rules, timezone, posting windows)
- Import: JSON, quick-start folder
- Execution engine: locking, retries, idempotency
- Platform adapters: Twitter/X, Reddit
- Post record lifecycle (state machine)
- Delivery attempt logging (persisted)
- Rate-limit tracking (persisted to DB)
- Dashboard (read-only, with working backend)
- REST API + MCP server (stdio)
- Automatic stale-lock cleanup
- Proper transaction boundaries

### Out of Scope (V2)
- Content generation or creative AI
- Engagement monitoring (replies, DMs)
- Analytics dashboards (impressions, CTR)
- A/B testing
- Ad campaign integration
- Broad platform coverage (TikTok, LinkedIn, etc.)

### Future Phases
- V3: Import via UI upload, engagement response templates, basic analytics
- V4: Adapters for TikTok, LinkedIn, Bluesky; campaign cloning

---

## 5. Core User Workflows

### 5.1 Quick-Start Flow
1. Provide campaign metadata, local asset folder path, and scheduling rules
2. System validates assets and payload
3. System creates campaign in draft status
4. System copies all referenced assets into `./campaigns/{campaign_slug}/media/`, generates sha256 hashes, and creates MediaAsset records (original folder is never modified)
5. System creates post records
6. System generates schedule
7. If validation passes, campaign can be activated
8. If validation fails, campaign remains draft with actionable errors

### 5.2 Live Campaign Mutation Rules
- Add/remove posts: allowed if status is draft or active
- Reschedule single post: allowed; updates scheduled_at
- Pause campaign: allowed from active; moves to paused
- Resume campaign: allowed from paused; re-evaluates "now" for catch-up
- Cancel campaign: allowed anytime; moves to cancelled, unlocks all pending posts

---

## 6. State Machine

### Campaign States
```
draft → active (activate)
active → paused (pause)
paused → active (resume)
active → completed (all posts posted or cancelled)
any → cancelled (cancel)
```

### Post States
```
draft → pending → locked → posting → posted
              ↓           ↓
        retry_scheduled   failed (after max retries)
              ↓
          cancelled
              ↓
           missed (if catch_up=false and window expired)
```

---

## 7. Functional Requirements

### 7.1 Campaign Management
- Create campaign with metadata
- Update campaign (draft only for core fields)
- Activate/pause/resume/cancel
- List campaigns with filters
- Get campaign status with post breakdown

### 7.2 Schedule Generation
- Recurrence rules (RRULE compatible)
- Timezone support (all stored as UTC)
- Posting windows (business hours, etc.)
- Platform-specific rate limits respected

### 7.3 Import/Export
- JSON import with schema validation
- Quick-start folder import
- Campaign export as JSON template

### 7.4 Execution Engine
- Locking mechanism (lock_token + locked_at + worker_id)
- Automatic stale-lock cleanup (configurable TTL, default 5 min)
- Idempotency (dedup_key per post, unique constraint)
- Retry with exponential backoff (configurable base + max retries)
- Missed post handling (catch_up mode with configurable max lateness)
- DeliveryAttempt persisted for every attempt (audit trail)

### 7.5 Platform Adapters

#### Twitter/X
- OAuth 1.0a authentication
- Tweet with media (images, video)
- Thread support (future)
- Rate limit: 300 tweets per 3 hours (tracked in DB)

#### Reddit
- OAuth2 script app authentication
- Post to subreddits
- Title/body format
- Rate limit: 10 posts per minute (tracked in DB)

---

## 8. Data Model

### Campaign
- id (UUID, PK)
- slug (unique, indexed)
- name
- description
- profile_id (FK, nullable)
- status (enum: draft, active, paused, completed, cancelled)
- timezone (str, default 'UTC')
- catch_up (boolean, default false)
- created_at (datetime, UTC)
- updated_at (datetime, UTC)

### CampaignProfile
- id (UUID, PK)
- slug (unique)
- name
- platforms (JSON list)
- default_subreddits (JSON)
- default_hashtags (JSON)
- cadence (JSON)
- posting_windows (JSON)
- created_at (datetime, UTC)
- updated_at (datetime, UTC)

### MediaAsset
- id (UUID, PK)
- campaign_id (FK)
- original_filename
- storage_key (path)
- mime_type
- size_bytes
- sha256 (unique per campaign)
- width, height (nullable)
- duration_sec (nullable)
- status (enum: pending, validating, ready, error, placeholder)
- created_at (datetime, UTC)

### Post
- id (UUID, PK)
- campaign_id (FK)
- asset_id (FK, nullable)
- platform (enum: twitter, reddit)
- target_account (str, nullable)
- copy (text)
- subreddit (str, nullable, for reddit)
- hashtags (JSON, nullable)
- scheduled_at (datetime, UTC)
- status (enum: draft, pending, locked, posting, posted, retry_scheduled, failed, cancelled, missed)
- posted_at (datetime, nullable)
- platform_post_id (str, nullable)
- retry_count (int, default 0)
- max_retries (int, default 3)
- error (text, nullable)
- dedup_key (unique, critical for idempotency)
- lock_token (UUID, nullable)
- locked_at (datetime, nullable)
- worker_id (str, nullable)
- created_at (datetime, UTC)
- updated_at (datetime, UTC)

### DeliveryAttempt
- id (UUID, PK)
- post_id (FK)
- attempt_number (int)
- started_at (datetime, UTC)
- finished_at (datetime, nullable)
- outcome (enum: success, retryable_failure, permanent_failure)
- error_code (str, nullable)
- error_message (text, nullable)
- provider_status_code (int, nullable)
- idempotency_key (str)
- request_fingerprint (str, nullable)

### RateLimitLog
- id (UUID, PK)
- platform (str)
- window_start (datetime, UTC)
- window_duration_sec (int)
- calls_made (int)
- calls_limit (int)
- updated_at (datetime, UTC)

---

## 9. API Specification

### REST Endpoints

#### Campaigns
- `POST /api/v1/campaigns` — Create campaign
- `GET /api/v1/campaigns` — List campaigns (filterable by status)
- `GET /api/v1/campaigns/{slug}` — Get campaign detail
- `PUT /api/v1/campaigns/{slug}` — Update campaign (draft only)
- `POST /api/v1/campaigns/{slug}/activate` — Activate
- `POST /api/v1/campaigns/{slug}/pause` — Pause
- `POST /api/v1/campaigns/{slug}/resume` — Resume
- `POST /api/v1/campaigns/{slug}/cancel` — Cancel

#### Quick Start
- `POST /api/v1/campaigns/quick-start` — Folder-based quick start

#### Import/Export
- `POST /api/v1/campaigns/import-json` — Import from JSON
- `GET /api/v1/campaigns/{slug}/export` — Export as JSON

#### Posts
- `GET /api/v1/campaigns/{slug}/posts` — List posts (filterable)
- `PUT /api/v1/campaigns/{slug}/posts/{post_id}` — Update post
- `DELETE /api/v1/campaigns/{slug}/posts/{post_id}` — Remove post

#### Dashboard Data
- `GET /api/v1/dashboard/summary` — Campaign status breakdown
- `GET /api/v1/dashboard/next-due` — Next due posts
- `GET /api/v1/dashboard/recent-failures` — Recent failures
- `GET /api/v1/dashboard/retry-queue` — Retry queue
- `GET /api/v1/dashboard/rate-limits` — Rate limit headroom

#### System
- `GET /api/v1/status` — System health check

### MCP Server (stdio)

Tools available:
- `campaign_create` — Create new campaign
- `campaign_import` — Import from JSON
- `campaign_activate` — Activate campaign
- `campaign_pause` — Pause campaign
- `campaign_resume` — Resume campaign
- `campaign_cancel` — Cancel campaign
- `campaign_status` — Get detailed status
- `post_list` — List posts with filters
- `post_update` — Update post fields

---

## 10. Asset Validation Defaults

### Twitter/X
- Images: ≤ 5 MB (JPEG, PNG, GIF, WebP)
- Videos: ≤ 512 MB (MP4)
- Aspect ratio: ≤ 2:1

### Reddit
- Images: ≤ 20 MB (subreddit-dependent)

---

## 11. Security Requirements

- API binds to localhost by default
- Remote access requires `ALLOW_REMOTE=true` in .env
- Optional `API_TOKEN` for Bearer token auth when remote enabled
- Secrets never logged (filtered from structured logs)
- Dockerfile uses multi-stage build, runs as non-root (UID 1000)
- Upload path traversal prevented via filename sanitization + realpath check
- MIME type and file size validation required
- Dashboard disabled when `ALLOW_REMOTE=true` unless `DASHBOARD_ENABLED=true`
- CORS restricted to configured origins only

---

## 12. Observability

### Dashboard (read-only at /dashboard)
- Campaigns by status (with counts)
- Next due posts
- Recent failures
- Retry queue
- Missed posts
- Per-platform activity summary
- Rate limit headroom gauges
- One-click "Export campaign as JSON" button
- Auto-refresh with configurable interval

### Logging
- Structured JSON logs (structlog)
- Per-delivery-attempt logging
- Error categorization (retryable vs permanent)
- Request fingerprinting
- No secrets in logs

---

## 13. Configuration

### .env.example
```bash
# Twitter/X OAuth
TWITTER_CONSUMER_KEY=
TWITTER_CONSUMER_SECRET=
TWITTER_ACCESS_TOKEN=
TWITTER_ACCESS_SECRET=

# Reddit OAuth2
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USERNAME=
REDDIT_PASSWORD=

# API Security
API_TOKEN=
ALLOW_REMOTE=false
DASHBOARD_ENABLED=true

# Deployment
DEBUG=false
LOG_LEVEL=INFO
```

### config.toml
```toml
[general]
api_host = "127.0.0.1"
api_port = 8000
log_level = "INFO"

[scheduler]
check_interval_sec = 60
max_retries = 3
backoff_base_sec = 60
missed_post_window_min = 30
catch_up_max_lateness_min = 1440
lock_ttl_sec = 300

[rate_limits]
twitter_tweets_per_3h = 300
reddit_posts_per_minute = 10

[media]
max_image_mb = 20
max_video_mb = 512
local_storage_path = "./campaigns"

[security]
allow_remote = false
dashboard_enabled = true
cors_origins = ["http://localhost:8000"]
```

---

## 14. Architecture

### Stack
- Python 3.12+
- FastAPI (REST API)
- SQLAlchemy 2.0 (async-only, aiosqlite)
- APScheduler 3.x (scheduler)
- Tweepy (Twitter)
- PRAW (Reddit)
- structlog (structured logging)
- Pydantic v2 (validation)

### Key Architectural Decisions (improvements over V1)
1. **Async-only database** — no sync SessionLocal, no mixed patterns
2. **Transaction context manager** — `async with unit_of_work()` guarantees atomic commits/rollbacks
3. **Persistent rate limits** — RateLimitLog table queried before every post
4. **Typed exception hierarchy** — `CampaignError → ValidationError | StateError | AdapterError | ...`
5. **Complete audit trail** — DeliveryAttempt committed in same transaction as post status update
6. **Stale lock cleanup** — background job reclaims locks older than `lock_ttl_sec`

### Deployment
- Single-node deployment
- Docker Compose with volumes:
  - `./campaigns` (media)
  - `./data` (SQLite database)
- Zero-downtime restarts via idempotency guarantees

---

## 15. File Structure

```
campaign-cannon-2/
├── src/
│   ├── __init__.py
│   ├── config.py              # Config loading (TOML + env)
│   ├── exceptions.py          # Typed exception hierarchy
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py        # Async engine + session factory
│   │   ├── models.py          # SQLAlchemy 2.0 models
│   │   └── unit_of_work.py    # Transaction context manager
│   ├── services/
│   │   ├── __init__.py
│   │   ├── campaign_service.py
│   │   ├── post_service.py
│   │   ├── schedule_service.py
│   │   ├── execution_service.py
│   │   ├── import_service.py
│   │   ├── asset_service.py
│   │   ├── rate_limit_service.py
│   │   └── dashboard_service.py
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── twitter_adapter.py
│   │   └── reddit_adapter.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py             # FastAPI app factory
│   │   ├── deps.py            # Dependency injection
│   │   ├── middleware.py       # Auth, CORS, error handling
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── campaigns.py
│   │       ├── posts.py
│   │       ├── import_export.py
│   │       ├── dashboard.py
│   │       └── system.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── campaign.py
│   │   ├── post.py
│   │   ├── import_export.py
│   │   └── dashboard.py
│   ├── mcp_server/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   └── server.py
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── scheduler.py
│   └── worker/
│       ├── __init__.py
│       └── post_executor.py
├── campaigns/                  # Media storage
├── data/                      # SQLite database
├── templates/
│   └── dashboard.html
├── static/
│   ├── css/
│   │   └── dashboard.css
│   └── js/
│       └── dashboard.js
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_state_machine.py
│   │   ├── test_campaign_service.py
│   │   ├── test_post_service.py
│   │   ├── test_execution_service.py
│   │   ├── test_rate_limit_service.py
│   │   └── test_asset_service.py
│   └── integration/
│       ├── __init__.py
│       └── test_campaign_lifecycle.py
├── .env.example
├── config.toml
├── pyproject.toml
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── run.py
└── README.md
```

---

## 16. Sample Import JSON

```json
{
  "schema_version": "1.0",
  "campaign": {
    "slug": "pomelli-fitness-launch",
    "name": "Pomelli Fitness Trainer Launch",
    "description": "30-day campaign for AI trainer product",
    "timezone": "America/Denver",
    "profile_slug": "fitness"
  },
  "assets": [
    { "filename": "hero-carousel-01.png", "mime_type": "image/png" },
    { "filename": "before-after.jpg", "mime_type": "image/jpeg" },
    { "filename": "demo-video.mp4", "mime_type": "video/mp4" }
  ],
  "posts": [
    {
      "asset_filename": "hero-carousel-01.png",
      "platform": "twitter",
      "copy": "Just launched my new AI trainer with Pomelli",
      "scheduled_at": "2026-03-15T09:00:00Z"
    },
    {
      "asset_filename": "before-after.jpg",
      "platform": "reddit",
      "subreddit": "r/fitness",
      "copy": "Transformed my body in 30 days with AI trainer. AMA",
      "scheduled_at": "2026-03-15T12:00:00Z"
    }
  ]
}
```

---

*End of PRD v4.0*
