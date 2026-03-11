"""Initial schema — all five core tables.

Revision ID: 001
Revises: None
Create Date: 2026-03-11
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── campaigns ──────────────────────────────────────────────────────
    op.create_table(
        "campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "status",
            sa.Enum("DRAFT", "ACTIVE", "PAUSED", "COMPLETED", "ARCHIVED", name="campaignstatus"),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON, nullable=True),
    )

    # ── posts ──────────────────────────────────────────────────────────
    op.create_table(
        "posts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column(
            "platform",
            sa.Enum("TWITTER", "REDDIT", "LINKEDIN", name="platform"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=True),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "DRAFT", "SCHEDULED", "QUEUED", "PUBLISHING",
                "POSTED", "FAILED", "RETRY", "DEAD_LETTER",
                name="poststate",
            ),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("platform_post_id", sa.String(255), nullable=True),
        sa.Column("platform_post_url", sa.String(2048), nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer, nullable=False, server_default="3"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("error_detail", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_posts_campaign_id", "posts", ["campaign_id"])
    op.create_index("ix_posts_campaign_schedule", "posts", ["campaign_id", "scheduled_at", "state"])
    op.create_unique_constraint("uq_posts_idempotency_key", "posts", ["idempotency_key"])

    # ── media_assets ───────────────────────────────────────────────────
    op.create_table(
        "media_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("post_id", sa.String(36), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("original_path", sa.String(1024), nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_media_assets_post_id", "media_assets", ["post_id"])

    # ── platform_credentials ───────────────────────────────────────────
    op.create_table(
        "platform_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "platform",
            sa.Enum("TWITTER", "REDDIT", "LINKEDIN", name="platform"),
            nullable=False,
        ),
        sa.Column("encrypted_credentials", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── post_logs ──────────────────────────────────────────────────────
    op.create_table(
        "post_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("post_id", sa.String(36), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("from_state", sa.String(20), nullable=True),
        sa.Column("to_state", sa.String(20), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_detail", sa.JSON, nullable=True),
        sa.Column("metadata", sa.JSON, nullable=True),
    )
    op.create_index("ix_post_logs_post_id", "post_logs", ["post_id"])


def downgrade() -> None:
    op.drop_table("post_logs")
    op.drop_table("platform_credentials")
    op.drop_table("media_assets")
    op.drop_table("posts")
    op.drop_table("campaigns")
