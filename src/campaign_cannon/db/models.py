"""SQLAlchemy 2.0 declarative models for Campaign Cannon.

Defines the five core tables: Campaign, Post, MediaAsset,
PlatformCredential, and PostLog, plus the PostState, Platform,
and CampaignStatus enums.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


# ── Enums ──────────────────────────────────────────────────────────────


class PostState(str, enum.Enum):
    """Lifecycle states for a Post."""

    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    QUEUED = "QUEUED"
    PUBLISHING = "PUBLISHING"
    POSTED = "POSTED"
    FAILED = "FAILED"
    RETRY = "RETRY"
    DEAD_LETTER = "DEAD_LETTER"


class Platform(str, enum.Enum):
    """Supported social-media platforms."""

    TWITTER = "TWITTER"
    REDDIT = "REDDIT"
    LINKEDIN = "LINKEDIN"


class CampaignStatus(str, enum.Enum):
    """High-level campaign statuses."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


# ── Base ───────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """Shared declarative base for all models."""

    pass


# ── Helpers ────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ── Campaign ───────────────────────────────────────────────────────────


class Campaign(Base):
    """A campaign groups related posts for multi-platform publishing."""

    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=_new_uuid
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus), nullable=False, default=CampaignStatus.DRAFT
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    activated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata", JSON, nullable=True
    )

    # Relationships
    posts: Mapped[list["Post"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Campaign {self.slug!r} status={self.status.value}>"


# ── Post ───────────────────────────────────────────────────────────────


class Post(Base):
    """An individual social-media post within a campaign."""

    __tablename__ = "posts"
    __table_args__ = (
        Index("ix_posts_campaign_schedule", "campaign_id", "scheduled_at", "state"),
        UniqueConstraint("idempotency_key", name="uq_posts_idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=_new_uuid
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        String(36), ForeignKey("campaigns.id"), nullable=False, index=True
    )
    platform: Mapped[Platform] = mapped_column(
        Enum(Platform), nullable=False
    )
    title: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[PostState] = mapped_column(
        Enum(PostState), nullable=False, default=PostState.DRAFT
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    platform_post_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    platform_post_url: Mapped[Optional[str]] = mapped_column(
        String(2048), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error_detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # Relationships
    campaign: Mapped["Campaign"] = relationship(back_populates="posts")
    media_assets: Mapped[list["MediaAsset"]] = relationship(
        back_populates="post", cascade="all, delete-orphan", lazy="selectin"
    )
    logs: Mapped[list["PostLog"]] = relationship(
        back_populates="post", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Post {self.id} platform={self.platform.value} state={self.state.value}>"


# ── MediaAsset ─────────────────────────────────────────────────────────


class MediaAsset(Base):
    """A media file (image/video) attached to a post."""

    __tablename__ = "media_assets"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=_new_uuid
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        String(36), ForeignKey("posts.id"), nullable=False, index=True
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # Relationships
    post: Mapped["Post"] = relationship(back_populates="media_assets")

    def __repr__(self) -> str:
        return f"<MediaAsset {self.file_path!r} ({self.mime_type})>"


# ── PlatformCredential ─────────────────────────────────────────────────


class PlatformCredential(Base):
    """Encrypted credential blob for a social-media platform."""

    __tablename__ = "platform_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=_new_uuid
    )
    platform: Mapped[Platform] = mapped_column(
        Enum(Platform), nullable=False
    )
    encrypted_credentials: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:
        return f"<PlatformCredential {self.platform.value} active={self.is_active}>"


# ── PostLog ────────────────────────────────────────────────────────────


class PostLog(Base):
    """Immutable audit-trail entry for every post state transition."""

    __tablename__ = "post_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=_new_uuid
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        String(36), ForeignKey("posts.id"), nullable=False, index=True
    )
    from_state: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    to_state: Mapped[str] = mapped_column(String(20), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    error_detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata", JSON, nullable=True
    )

    # Relationships
    post: Mapped["Post"] = relationship(back_populates="logs")

    def __repr__(self) -> str:
        return f"<PostLog {self.from_state}→{self.to_state} @ {self.timestamp}>"
