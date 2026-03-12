# Campaign Cannon v3.1 — PRD Context for Coding Agents

## What This Is
A bulletproof social media campaign automation engine. It's a **delivery engine only** — not a marketing brain. Content comes from Pomelli (or any JSON source), Campaign Cannon handles reliable scheduling, state management, and multi-platform publishing.

## Core Architecture
- **Python 3.11+** — single-node deployment (one Linux box or Docker)
- **SQLite with WAL mode** — via SQLAlchemy 2.0 + Alembic migrations
- **APScheduler 3.x** — job scheduling with SQLite job store
- **FastAPI** — REST API with 5-call campaign lifecycle
- **MCP Server** — stdio transport for AI agent integration
- **Platform Adapters** — Twitter/X, Reddit, LinkedIn (adapter pattern)
- **Pydantic v2** — config + request/response validation
- **structlog** — JSON-formatted structured logging

## The 5-Call Campaign Lifecycle
1. `POST /api/v1/campaigns` — Import campaign JSON (creates Campaign + Posts + MediaAssets)
2. `POST /api/v1/campaigns/{id}/activate` — Schedule all posts via APScheduler
3. `GET /api/v1/campaigns/{id}/status` — Poll campaign progress
4. `POST /api/v1/campaigns/{id}/pause` — Pause (remove scheduler jobs, keep DB state)
5. `POST /api/v1/campaigns/{id}/resume` — Resume (re-create scheduler jobs)

## State Machine (Post States)
```
DRAFT → SCHEDULED → QUEUED → PUBLISHING → POSTED (terminal success)
                                  ↓
                               FAILED → RETRY → QUEUED (loop back)
                                  ↓
                              DEAD_LETTER (terminal failure after max retries)
```
- Optimistic locking via version column
- Every transition logged to PostLog table
- Stuck-post recovery: PUBLISHING > 5 min → reset to QUEUED
- Max retries: 3, exponential backoff: 30s, 120s, 480s

## Data Model (Core Tables)
### Campaign
- id (UUID PK), name, slug, description, status (DRAFT/ACTIVE/PAUSED/COMPLETED/ARCHIVED)
- created_at, updated_at, activated_at, completed_at
- metadata (JSON) — arbitrary campaign-level data

### Post
- id (UUID PK), campaign_id (FK), platform (TWITTER/REDDIT/LINKEDIN)
- title (Reddit), body (text content), media_assets (relationship)
- state (PostState enum), scheduled_at, published_at
- platform_post_id, platform_post_url (set after publish)
- idempotency_key (unique), retry_count, max_retries (default 3)
- version (optimistic lock), error_detail (JSON)
- Indexes: (campaign_id, scheduled_at, state), (idempotency_key UNIQUE)

### MediaAsset
- id (UUID PK), post_id (FK), file_path, original_path
- sha256_hash, mime_type, size_bytes
- platform_constraints (JSON) — validated per platform

### PlatformCredential
- id (UUID PK), platform, encrypted_credentials (AES-256)
- is_active, last_used_at, token_expires_at

### PostLog (Audit)
- id (UUID PK), post_id (FK), from_state, to_state
- timestamp, error_detail, metadata (JSON)

## Platform-Specific Rules
### Twitter/X
- OAuth2 user-context auth
- Free tier: 300 posts / 3 hours
- Image ≤ 5MB, video ≤ 512MB, max 2:1 aspect ratio
- Thread support (multiple posts linked)

### Reddit
- OAuth2 script app (username/password flow)
- ~1 post/minute rate limit
- Image ≤ 20MB (subreddit-dependent)
- Text, link, or image post types
- Note: If Reddit deprecates password auth post-2026, adapter will switch to refresh-token flow

### LinkedIn
- OAuth2 3-legged flow
- ~100 posts/day
- Image ≤ 10MB
- 200-char preview limit

## Configuration
- `.env` — secrets (API keys, master encryption key)
- `config.toml` — non-secret settings (scheduler, rate limits, paths)
- Environment variables override TOML values
- Pydantic Settings for validation

## Dedup & Safety
- Idempotency key: SHA-256(campaign_id + post_slug + platform + scheduled_at)
- Publish-once guard: check idempotency_key + platform_post_id before publish
- Row-level locking: SQLite BEGIN IMMEDIATE for publish transactions
- Duplicate content detection: warn if same text to same platform within 24h

## Rate Limiting
- In-memory token bucket synced to DB
- Persist remaining tokens + reset time (survives restart)
- Backpressure: delay jobs instead of failing when tokens exhausted

## Import Formats
### JSON Import (primary)
Full campaign JSON with posts, media references, platform targets, schedule

### Quick-Start Markdown
Markdown with YAML frontmatter → parsed to JSON → imported via same pipeline

## Dashboard
- Single-page status dashboard (active campaigns, post pipeline by state)
- Campaign timeline view
- One-click "Export campaign as JSON" for cloning
- Structured JSON logging with configurable level

## Docker Deployment
- Multi-stage Dockerfile, non-root user (UID 1000)
- docker-compose with volumes for ./campaigns and ./sqlite
- Health check endpoint
- Startup validation (DB writable, creds decryptable, dirs exist)
