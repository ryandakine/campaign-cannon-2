"""Campaign Cannon Dashboard — simple HTML status page mounted on /dashboard."""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# ── CSS ───────────────────────────────────────────────────────────────────

_CSS = """
:root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --border: #2a2d3a;
    --text: #e1e4ed;
    --muted: #8b8fa3;
    --accent: #6366f1;
    --success: #22c55e;
    --warning: #f59e0b;
    --danger: #ef4444;
    --info: #3b82f6;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', monospace;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
    max-width: 1200px;
    margin: 0 auto;
}
h1 { font-size: 1.5rem; margin-bottom: 1.5rem; color: var(--accent); }
h2 { font-size: 1.1rem; margin: 1.5rem 0 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
.card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem 1.25rem;
}
.card .label { font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.card .value { font-size: 1.75rem; font-weight: bold; margin-top: 0.25rem; }
table { width: 100%; border-collapse: collapse; margin-bottom: 1.5rem; }
th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); font-size: 0.85rem; }
th { color: var(--muted); font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; font-size: 0.75rem; }
.badge {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
}
.badge-active, .badge-posted { background: rgba(34,197,94,0.15); color: var(--success); }
.badge-paused, .badge-queued { background: rgba(245,158,11,0.15); color: var(--warning); }
.badge-draft, .badge-scheduled { background: rgba(59,130,246,0.15); color: var(--info); }
.badge-failed, .badge-dead_letter { background: rgba(239,68,68,0.15); color: var(--danger); }
.badge-publishing, .badge-retry { background: rgba(99,102,241,0.15); color: var(--accent); }
.badge-completed, .badge-archived { background: rgba(139,143,163,0.15); color: var(--muted); }
.btn {
    display: inline-block;
    padding: 0.3rem 0.75rem;
    background: var(--accent);
    color: white;
    border: none;
    border-radius: 4px;
    font-size: 0.75rem;
    cursor: pointer;
    text-decoration: none;
}
.btn:hover { opacity: 0.85; }
.refresh-bar { font-size: 0.75rem; color: var(--muted); margin-bottom: 1rem; }
"""

# ── HTML Template ─────────────────────────────────────────────────────────

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Campaign Cannon — Dashboard</title>
    <style>{css}</style>
    <script>
        setTimeout(function() {{ window.location.reload(); }}, {refresh_ms});
    </script>
</head>
<body>
    <h1>Campaign Cannon Dashboard</h1>
    <div class="refresh-bar">Auto-refresh every {refresh_sec}s &middot; Last updated: {updated_at}</div>

    <h2>Post Pipeline</h2>
    <div class="grid">
        {pipeline_cards}
    </div>

    <h2>Active Campaigns</h2>
    {campaigns_table}

    <h2>Next 5 Upcoming Posts</h2>
    {upcoming_table}

    <h2>Last 10 Completed Posts</h2>
    {completed_table}

    <h2>Campaign Timeline</h2>
    {timeline_table}
</body>
</html>"""


# ── Data access (with graceful fallbacks) ─────────────────────────────────

def _safe_query(session_factory, query_fn, default=None):
    """Run a query with fallback if models aren't available."""
    if default is None:
        default = []
    try:
        from campaign_cannon.db.connection import get_session
        with get_session() as session:
            return query_fn(session)
    except Exception:
        return default


def _get_pipeline_counts() -> dict[str, int]:
    """Count posts per state."""
    def _query(session):
        from campaign_cannon.db.models import Post
        from sqlalchemy import func
        rows = session.query(Post.state, func.count()).group_by(Post.state).all()
        return {str(state): count for state, count in rows}

    return _safe_query(None, _query, default={})


def _get_campaigns() -> list[dict]:
    """Get active campaigns."""
    def _query(session):
        from campaign_cannon.db.models import Campaign
        campaigns = session.query(Campaign).order_by(Campaign.updated_at.desc()).limit(20).all()
        return [
            {
                "id": str(c.id),
                "name": c.name,
                "slug": c.slug,
                "status": str(c.status),
                "created_at": str(c.created_at) if c.created_at else "",
            }
            for c in campaigns
        ]

    return _safe_query(None, _query, default=[])


def _get_upcoming_posts() -> list[dict]:
    """Next 5 upcoming posts."""
    def _query(session):
        from campaign_cannon.db.models import Post
        posts = (
            session.query(Post)
            .filter(Post.state.in_(["scheduled", "queued"]))
            .order_by(Post.scheduled_at.asc())
            .limit(5)
            .all()
        )
        return [
            {
                "id": str(p.id),
                "platform": str(p.platform),
                "body": (p.body[:60] + "...") if p.body and len(p.body) > 60 else (p.body or ""),
                "scheduled_at": str(p.scheduled_at) if p.scheduled_at else "",
                "state": str(p.state),
            }
            for p in posts
        ]

    return _safe_query(None, _query, default=[])


def _get_completed_posts() -> list[dict]:
    """Last 10 completed (posted/failed) posts."""
    def _query(session):
        from campaign_cannon.db.models import Post
        posts = (
            session.query(Post)
            .filter(Post.state.in_(["posted", "failed", "dead_letter"]))
            .order_by(Post.updated_at.desc())
            .limit(10)
            .all()
        )
        return [
            {
                "id": str(p.id),
                "platform": str(p.platform),
                "body": (p.body[:60] + "...") if p.body and len(p.body) > 60 else (p.body or ""),
                "state": str(p.state),
                "published_at": str(p.published_at) if p.published_at else str(p.updated_at),
            }
            for p in posts
        ]

    return _safe_query(None, _query, default=[])


# ── HTML builders ─────────────────────────────────────────────────────────

def _badge(status: str) -> str:
    s = html.escape(str(status).lower())
    return f'<span class="badge badge-{s}">{s}</span>'


def _pipeline_cards(counts: dict[str, int]) -> str:
    states = ["draft", "scheduled", "queued", "publishing", "posted", "failed", "retry", "dead_letter"]
    cards = []
    for state in states:
        count = counts.get(state, 0)
        cards.append(
            f'<div class="card"><div class="label">{_badge(state)}</div>'
            f'<div class="value">{count}</div></div>'
        )
    return "\n".join(cards)


def _campaigns_table(campaigns: list[dict]) -> str:
    if not campaigns:
        return '<p style="color:var(--muted)">No campaigns yet.</p>'

    rows = []
    for c in campaigns:
        export_btn = (
            f'<a class="btn" href="/api/v1/campaigns/{html.escape(c["id"])}/export"'
            f' target="_blank">Export JSON</a>'
        )
        rows.append(
            f'<tr><td>{html.escape(c["name"])}</td>'
            f'<td><code>{html.escape(c["slug"])}</code></td>'
            f'<td>{_badge(c["status"])}</td>'
            f'<td>{html.escape(c["created_at"])}</td>'
            f'<td>{export_btn}</td></tr>'
        )

    return (
        '<table><thead><tr><th>Name</th><th>Slug</th><th>Status</th>'
        '<th>Created</th><th>Actions</th></tr></thead><tbody>'
        + "\n".join(rows)
        + '</tbody></table>'
    )


def _posts_table(posts: list[dict], columns: list[str]) -> str:
    if not posts:
        return '<p style="color:var(--muted)">No posts.</p>'

    headers = "".join(f"<th>{html.escape(c.replace('_', ' ').title())}</th>" for c in columns)
    rows = []
    for p in posts:
        cells = []
        for col in columns:
            val = p.get(col, "")
            if col == "state":
                cells.append(f"<td>{_badge(val)}</td>")
            else:
                cells.append(f"<td>{html.escape(str(val))}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")

    return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _timeline_table(campaigns: list[dict]) -> str:
    """Simple timeline: campaign name + dates."""
    if not campaigns:
        return '<p style="color:var(--muted)">No campaigns.</p>'

    rows = []
    for c in campaigns:
        rows.append(
            f'<tr><td>{html.escape(c["name"])}</td>'
            f'<td>{_badge(c["status"])}</td>'
            f'<td>{html.escape(c["created_at"])}</td></tr>'
        )
    return (
        '<table><thead><tr><th>Campaign</th><th>Status</th><th>Created</th></tr></thead>'
        '<tbody>' + "\n".join(rows) + '</tbody></table>'
    )


# ── Route ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard_home():
    """Render the dashboard HTML page."""
    refresh_sec = 5
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    pipeline = _get_pipeline_counts()
    campaigns = _get_campaigns()
    upcoming = _get_upcoming_posts()
    completed = _get_completed_posts()

    page = _TEMPLATE.format(
        css=_CSS,
        refresh_ms=refresh_sec * 1000,
        refresh_sec=refresh_sec,
        updated_at=now,
        pipeline_cards=_pipeline_cards(pipeline),
        campaigns_table=_campaigns_table(campaigns),
        upcoming_table=_posts_table(upcoming, ["platform", "body", "scheduled_at", "state"]),
        completed_table=_posts_table(completed, ["platform", "body", "state", "published_at"]),
        timeline_table=_timeline_table(campaigns),
    )
    return HTMLResponse(content=page)


def mount_dashboard(app):
    """Mount the dashboard router on the main FastAPI app."""
    app.include_router(router)
