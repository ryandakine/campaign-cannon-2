"""Campaign Cannon 2 — SQLAlchemy 2.0 models.

All datetimes are stored as UTC. Enums use Python enums for type safety.
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
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# ── Enums ──────────────────────────────────────────────────────────────────


class CampaignStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"


class PostStatus(str, enum.Enum):
    draft = "draft"
    pending = "pending"
    locked = "locked"
    posting = "posting"
    posted = "posted"
    retry_scheduled = "retry_scheduled"
    failed = "failed"
    cancelled = "cancelled"
    missed = "missed"


class AssetStatus(str, enum.Enum):
    pending = "pending"
    validating = "validating"
    ready = "ready"
    error = "error"
    placeholder = "placeholder"


class Platform(str, enum.Enum):
    twitter = "twitter"
    reddit = "reddit"


class DeliveryOutcome(str, enum.Enum):
    success = "success"
    retryable_failure = "retryable_failure"
    permanent_failure = "permanent_failure"


# ── Valid state transitions ────────────────────────────────────────────────

CAMPAIGN_TRANSITIONS: dict[CampaignStatus, set[CampaignStatus]] = {
    CampaignStatus.draft: {CampaignStatus.active, CampaignStatus.cancelled},
    CampaignStatus.active: {CampaignStatus.paused, CampaignStatus.completed, CampaignStatus.cancelled},
    CampaignStatus.paused: {CampaignStatus.active, CampaignStatus.cancelled},
    CampaignStatus.completed: set(),
    CampaignStatus.cancelled: set(),
}

POST_TRANSITIONS: dict[PostStatus, set[PostStatus]] = {
    PostStatus.draft: {PostStatus.pending, PostStatus.cancelled},
    PostStatus.pending: {PostStatus.locked, PostStatus.cancelled, PostStatus.missed},
    PostStatus.locked: {PostStatus.posting, PostStatus.pending, PostStatus.cancelled},
    PostStatus.posting: {PostStatus.posted, PostStatus.retry_scheduled, PostStatus.failed},
    PostStatus.posted: set(),
    PostStatus.retry_scheduled: {PostStatus.pending, PostStatus.cancelled, PostStatus.failed},
    PostStatus.failed: set(),
    PostStatus.cancelled: set(),
    PostStatus.missed: set(),
}


# ── Models ─────────────────────────────────────────────────────────────────


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("campaign_profiles.id"), nullable=True
    )
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus), nullable=False, default=CampaignStatus.draft
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    catch_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    profile: Mapped[Optional[CampaignProfile]] = relationship(back_populates="campaigns")
    posts: Mapped[list[Post]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    assets: Mapped[list[MediaAsset]] = relationship(back_populates="campaign", cascade="all, delete-orphan")

    def can_transition_to(self, target: CampaignStatus) -> bool:
        return target in CAMPAIGN_TRANSITIONS.get(self.status, set())


class CampaignProfile(Base):
    __tablename__ = "campaign_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    platforms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    default_subreddits: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    default_hashtags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    cadence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    posting_windows: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    campaigns: Mapped[list[Campaign]] = relationship(back_populates="profile")


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    campaign_id: Mapped[str] = mapped_column(String(36), ForeignKey("campaigns.id"), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[AssetStatus] = mapped_column(
        Enum(AssetStatus), nullable=False, default=AssetStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    campaign: Mapped[Campaign] = relationship(back_populates="assets")
    posts: Mapped[list[Post]] = relationship(back_populates="asset")

    __table_args__ = (
        UniqueConstraint("campaign_id", "sha256", name="uq_asset_campaign_sha256"),
    )


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    campaign_id: Mapped[str] = mapped_column(String(36), ForeignKey("campaigns.id"), nullable=False)
    asset_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("media_assets.id"), nullable=True
    )
    platform: Mapped[Platform] = mapped_column(Enum(Platform), nullable=False)
    target_account: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    copy: Mapped[str] = mapped_column(Text, nullable=False)
    subreddit: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    hashtags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[PostStatus] = mapped_column(
        Enum(PostStatus), nullable=False, default=PostStatus.draft
    )
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    platform_post_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    lock_token: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    campaign: Mapped[Campaign] = relationship(back_populates="posts")
    asset: Mapped[Optional[MediaAsset]] = relationship(back_populates="posts")
    delivery_attempts: Mapped[list[DeliveryAttempt]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_posts_status_scheduled", "status", "scheduled_at"),
        Index("ix_posts_campaign_status", "campaign_id", "status"),
    )

    def can_transition_to(self, target: PostStatus) -> bool:
        return target in POST_TRANSITIONS.get(self.status, set())


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    post_id: Mapped[str] = mapped_column(String(36), ForeignKey("posts.id"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[Optional[DeliveryOutcome]] = mapped_column(Enum(DeliveryOutcome), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    post: Mapped[Post] = relationship(back_populates="delivery_attempts")


class RateLimitLog(Base):
    __tablename__ = "rate_limit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_duration_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    calls_made: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    calls_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_rate_limit_platform_window", "platform", "window_start"),
    )
