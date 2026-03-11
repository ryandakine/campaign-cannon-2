"""Markdown + YAML frontmatter campaign import for Campaign Cannon.

Parses a markdown file with YAML frontmatter into a CampaignImportRequest,
then delegates to the JSON import pipeline for validation and persistence.

Expected format:
    ---
    name: My Campaign
    slug: my-campaign
    platforms: [twitter, reddit, linkedin]
    ---

    ## Post 1: Launch Announcement
    scheduled: 2026-03-15T09:00:00-07:00
    media: ./images/launch.png

    We're excited to announce...

    ## Post 2: Follow-up
    scheduled: 2026-03-16T14:00:00-07:00

    Here's what happened...
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

import structlog

from campaign_cannon.api.schemas import CampaignImportRequest, PostImport
from campaign_cannon.db.models import Platform

logger = structlog.get_logger("campaign_cannon.import.markdown")

# ── Frontmatter Parsing ────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_POST_HEADER_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


class MarkdownParseError(Exception):
    """Raised when markdown parsing fails."""

    def __init__(self, message: str, line: int | None = None) -> None:
        self.line = line
        prefix = f"Line {line}: " if line else ""
        super().__init__(f"{prefix}{message}")


def parse_markdown_campaign(
    content: str,
    file_path: str | None = None,
) -> CampaignImportRequest:
    """Parse a markdown campaign file into a CampaignImportRequest.

    Args:
        content: Raw markdown string with YAML frontmatter.
        file_path: Path to the markdown file (for resolving relative media paths).

    Returns:
        CampaignImportRequest ready for import pipeline.

    Raises:
        MarkdownParseError: If the markdown is malformed.
    """
    # Parse YAML frontmatter
    frontmatter, body = _split_frontmatter(content)
    meta = _parse_yaml_frontmatter(frontmatter)

    # Extract campaign-level fields
    name = meta.get("name")
    if not name:
        raise MarkdownParseError("Frontmatter missing required field: name")

    slug = meta.get("slug")
    if not slug:
        raise MarkdownParseError("Frontmatter missing required field: slug")

    platforms_raw = meta.get("platforms", [])
    if isinstance(platforms_raw, str):
        platforms_raw = [platforms_raw]
    platforms = _parse_platforms(platforms_raw)
    if not platforms:
        raise MarkdownParseError(
            "Frontmatter must specify at least one platform "
            "(e.g., platforms: [twitter, reddit])"
        )

    description = meta.get("description")
    media_base_path = meta.get("media_base_path")
    campaign_metadata = {k: v for k, v in meta.items()
                         if k not in ("name", "slug", "platforms", "description", "media_base_path")}

    # If no explicit media_base_path, use the markdown file's directory
    if not media_base_path and file_path:
        media_base_path = str(Path(file_path).parent)

    # Parse posts from markdown body
    raw_posts = _split_posts(body)
    if not raw_posts:
        raise MarkdownParseError("No posts found. Posts should start with ## headers.")

    posts: list[PostImport] = []
    for i, (title, post_body) in enumerate(raw_posts):
        post_meta, post_content = _parse_post_metadata(post_body)

        scheduled_str = post_meta.get("scheduled")
        if not scheduled_str:
            raise MarkdownParseError(
                f"Post {i + 1} ({title!r}) missing 'scheduled:' field",
            )

        scheduled_at = _parse_datetime(scheduled_str, title)
        media_paths = _parse_media_paths(post_meta.get("media"))
        subreddit = post_meta.get("subreddit")

        # Generate slug from title
        post_slug = _slugify(title) if title else f"post-{i + 1}"

        # Create a post for each target platform
        for platform in platforms:
            posts.append(
                PostImport(
                    slug=f"{post_slug}-{platform.value}",
                    platform=platform,
                    title=title if platform == Platform.REDDIT else None,
                    body=post_content.strip(),
                    scheduled_at=scheduled_at,
                    media_paths=media_paths,
                    subreddit=subreddit,
                )
            )

    return CampaignImportRequest(
        name=name,
        slug=slug,
        description=description,
        posts=posts,
        media_base_path=media_base_path,
        metadata=campaign_metadata or None,
    )


def import_markdown_campaign(
    session,
    content: str,
    file_path: str | None = None,
    dry_run: bool = False,
):
    """Parse markdown and import via the JSON import pipeline.

    Args:
        session: SQLAlchemy session.
        content: Raw markdown string.
        file_path: Path to the markdown file.
        dry_run: If True, validate only.

    Returns:
        Import result from json_import.import_campaign.
    """
    from campaign_cannon.import_.json_import import import_campaign

    payload = parse_markdown_campaign(content, file_path)
    return import_campaign(session, payload, dry_run=dry_run)


# ── Internal Helpers ────────────────────────────────────────────────────────


def _split_frontmatter(content: str) -> tuple[str, str]:
    """Split YAML frontmatter from markdown body."""
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise MarkdownParseError(
            "Missing YAML frontmatter. File must start with ---\\n...\\n---"
        )
    frontmatter = match.group(1)
    body = content[match.end():]
    return frontmatter, body


def _parse_yaml_frontmatter(raw: str) -> dict:
    """Parse YAML frontmatter into a dict.

    Uses a simple key-value parser to avoid requiring PyYAML as a dependency.
    Supports scalar values and simple lists in [a, b, c] format.
    """
    result: dict = {}
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        # Parse list syntax: [a, b, c]
        if value.startswith("[") and value.endswith("]"):
            items = [item.strip().strip("'\"") for item in value[1:-1].split(",")]
            result[key] = [item for item in items if item]
        elif value.lower() in ("true", "yes"):
            result[key] = True
        elif value.lower() in ("false", "no"):
            result[key] = False
        elif value.startswith(("'", '"')) and value.endswith(("'", '"')):
            result[key] = value[1:-1]
        else:
            result[key] = value

    return result


def _parse_platforms(raw: list[str]) -> list[Platform]:
    """Convert string platform names to Platform enum values."""
    platforms = []
    valid_names = {p.value.lower(): p for p in Platform}
    for name in raw:
        normalized = name.strip().lower()
        if normalized in valid_names:
            platforms.append(valid_names[normalized])
        else:
            raise MarkdownParseError(
                f"Unknown platform {name!r}. Valid: {', '.join(valid_names.keys())}"
            )
    return platforms


def _split_posts(body: str) -> list[tuple[str, str]]:
    """Split markdown body into (title, content) tuples by ## headers."""
    matches = list(_POST_HEADER_RE.finditer(body))
    if not matches:
        return []

    posts: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        title = match.group(1).strip()
        # Remove leading "Post N:" prefix if present
        title = re.sub(r"^Post\s+\d+:\s*", "", title, flags=re.IGNORECASE)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[start:end].strip()
        posts.append((title, content))

    return posts


def _parse_post_metadata(post_body: str) -> tuple[dict[str, str], str]:
    """Extract key: value metadata lines from the start of a post body.

    Metadata lines are at the top before the first blank line or content paragraph.
    """
    meta: dict[str, str] = {}
    content_lines: list[str] = []
    in_metadata = True

    for line in post_body.splitlines():
        stripped = line.strip()
        if in_metadata and ":" in stripped and not stripped.startswith("#"):
            key, _, value = stripped.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if key in ("scheduled", "media", "subreddit", "title"):
                meta[key] = value
                continue
        if in_metadata and stripped == "":
            in_metadata = False
            continue
        if in_metadata and ":" not in stripped:
            in_metadata = False
        content_lines.append(line)

    return meta, "\n".join(content_lines)


def _parse_datetime(value: str, context: str) -> datetime:
    """Parse an ISO 8601 datetime string."""
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise MarkdownParseError(
            f"Invalid date format for post {context!r}: {value!r}. "
            "Expected ISO 8601 format (e.g., 2026-03-15T09:00:00-07:00)"
        ) from exc


def _parse_media_paths(value: str | None) -> list[str]:
    """Parse comma-separated media paths."""
    if not value:
        return []
    return [path.strip() for path in value.split(",") if path.strip()]


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")[:80]
