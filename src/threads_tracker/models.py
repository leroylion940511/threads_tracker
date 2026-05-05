"""ORM models matching the schema in the proposal §五."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator

from .db import Base

# SQLite only supports AUTOINCREMENT on INTEGER PKs; use Integer for SQLite
# variant so dev/test stays self-contained, BIGINT for Postgres.
BigPK = BigInteger().with_variant(Integer(), "sqlite")
BigFK = BigInteger().with_variant(Integer(), "sqlite")


class JSONField(TypeDecorator):
    """JSONB on Postgres, JSON elsewhere (e.g. SQLite for local dev/tests)."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[override]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class DetectionSource(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


class PostStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    REMOVED = "removed"


class PollingTier(StrEnum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class RelationType(StrEnum):
    AUTHOR_FOLLOWUP = "author_followup"
    QUOTE = "quote"
    DISCUSSION = "discussion"


class SummaryType(StrEnum):
    EVOLUTION = "evolution"
    SENTIMENT = "sentiment"
    MILESTONE = "milestone"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class TrackedPost(Base, TimestampMixin):
    __tablename__ = "tracked_posts"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    threads_post_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    author_username: Mapped[str] = mapped_column(String(64), nullable=False)
    post_url: Mapped[str] = mapped_column(Text, nullable=False)
    original_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    detection_source: Mapped[str] = mapped_column(
        String(16), default=DetectionSource.MANUAL.value, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), default=PostStatus.ACTIVE.value, nullable=False
    )
    polling_tier: Mapped[str] = mapped_column(
        String(16), default=PollingTier.HOT.value, nullable=False
    )
    last_polled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONField, nullable=True
    )

    snapshots: Mapped[list["PostSnapshot"]] = relationship(
        back_populates="tracked_post", cascade="all, delete-orphan"
    )
    related_posts: Mapped[list["RelatedPost"]] = relationship(
        back_populates="tracked_post", cascade="all, delete-orphan"
    )
    summaries: Mapped[list["LLMSummary"]] = relationship(
        back_populates="tracked_post", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="tracked_post", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "idx_tracked_polling",
            "polling_tier",
            "last_polled_at",
        ),
    )


class PostSnapshot(Base):
    __tablename__ = "post_snapshots"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    tracked_post_id: Mapped[int] = mapped_column(
        BigFK,
        ForeignKey("tracked_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    like_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reply_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repost_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_replies: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONField, nullable=True
    )

    tracked_post: Mapped[TrackedPost] = relationship(back_populates="snapshots")

    __table_args__ = (
        Index("idx_snapshots_post_time", "tracked_post_id", "captured_at"),
    )


class RelatedPost(Base):
    __tablename__ = "related_posts"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    tracked_post_id: Mapped[int] = mapped_column(
        BigFK,
        ForeignKey("tracked_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    threads_post_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    relation_type: Mapped[str] = mapped_column(String(16), nullable=False)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tracked_post: Mapped[TrackedPost] = relationship(back_populates="related_posts")

    __table_args__ = (
        Index("idx_related_post", "tracked_post_id", "posted_at"),
    )


class LLMSummary(Base):
    __tablename__ = "llm_summaries"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    tracked_post_id: Mapped[int] = mapped_column(
        BigFK,
        ForeignKey("tracked_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    summary_type: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    tracked_post: Mapped[TrackedPost] = relationship(back_populates="summaries")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONField, nullable=False, default=dict
    )

    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    user_id: Mapped[int] = mapped_column(
        BigFK, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tracked_post_id: Mapped[int] = mapped_column(
        BigFK,
        ForeignKey("tracked_posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    subscribed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    notification_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONField, nullable=False, default=dict
    )

    user: Mapped[User] = relationship(back_populates="subscriptions")
    tracked_post: Mapped[TrackedPost] = relationship(back_populates="subscriptions")

    __table_args__ = (
        UniqueConstraint("user_id", "tracked_post_id", name="uq_user_post"),
    )


__all__ = [
    "Base",
    "DetectionSource",
    "LLMSummary",
    "PollingTier",
    "PostSnapshot",
    "PostStatus",
    "RelatedPost",
    "RelationType",
    "Subscription",
    "SummaryType",
    "TrackedPost",
    "User",
]
