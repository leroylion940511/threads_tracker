"""ORM models — v3 schema (proposal §五)."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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


# --- enums --------------------------------------------------------------


class PostStatus(StrEnum):
    ACTIVE = "active"
    MUTED = "muted"
    ARCHIVED = "archived"
    REMOVED = "removed"


class PollingTier(StrEnum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class RelationType(StrEnum):
    AUTHOR_FOLLOWUP = "author_followup"
    AUTHOR_REPLY = "author_reply"
    HOT_REPLY = "hot_reply"
    QUOTE = "quote"


class PushType(StrEnum):
    ALREADY_HOT = "already_hot"
    EARLY_BET = "early_bet"
    BREAKING = "breaking"


class FeedbackAction(StrEnum):
    COLLECT = "collect"
    DISLIKE = "dislike"
    MUTE_EVENT = "mute_event"


class ScoringStage(StrEnum):
    RULES = "rules"
    HAIKU = "haiku"
    FINAL = "final"


class LLMPurpose(StrEnum):
    SCORING = "scoring"
    INITIAL_SUMMARY = "initial_summary"
    EVOLUTION = "evolution"
    MILESTONE_CHECK = "milestone_check"
    QA = "qa"


class QAContextMode(StrEnum):
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"


class QAEndReason(StrEnum):
    EXIT = "exit"
    TIMEOUT = "timeout"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


# --- 探索層 -------------------------------------------------------------


class KeywordSeed(Base):
    """關鍵字種子池（M2 探索層的輸入）."""

    __tablename__ = "keyword_seeds"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    last_polled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_candidates_yielded: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    total_promoted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_collected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class CandidatePost(Base):
    """探索層產出 — 每筆 = 抓到的一篇候選貼文（去重 by threads_post_id）."""

    __tablename__ = "candidate_posts"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    threads_post_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    author_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    author_follower_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    post_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    discovery_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    initial_likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    initial_replies: Mapped[int | None] = mapped_column(Integer, nullable=True)
    initial_reposts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    initial_views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONField, nullable=True
    )

    scoring_records: Mapped[list["ScoringRecord"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )
    daily_pushes: Mapped[list["DailyPush"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )
    feedback_entries: Mapped[list["Feedback"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )
    tracked_post: Mapped["TrackedPost | None"] = relationship(
        back_populates="candidate", uselist=False
    )

    __table_args__ = (
        Index("idx_candidate_discovered", "discovered_at"),
        Index("idx_candidate_author", "author_username"),
    )


# --- 評分層 -------------------------------------------------------------


class ScoringRecord(Base):
    """三段式評分記錄：rules / haiku / final，每段 cost_usd 獨立記."""

    __tablename__ = "scoring_records"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    candidate_post_id: Mapped[int] = mapped_column(
        BigFK,
        ForeignKey("candidate_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONField, nullable=True)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)

    candidate: Mapped[CandidatePost] = relationship(back_populates="scoring_records")

    __table_args__ = (
        Index("idx_scoring_candidate_stage", "candidate_post_id", "stage"),
    )


# --- 推送層 -------------------------------------------------------------


class DailyPush(Base):
    """每日推送清單 — 一天一筆 push_date × candidate × push_type."""

    __tablename__ = "daily_pushes"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    push_date: Mapped[date] = mapped_column(Date, nullable=False)
    candidate_post_id: Mapped[int] = mapped_column(
        BigFK,
        ForeignKey("candidate_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    push_type: Mapped[str] = mapped_column(String(16), nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pushed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    candidate: Mapped[CandidatePost] = relationship(back_populates="daily_pushes")

    __table_args__ = (
        UniqueConstraint(
            "push_date", "candidate_post_id", name="uq_daily_push_date_candidate"
        ),
        Index("idx_daily_push_date", "push_date"),
    )


class Feedback(Base):
    """使用者按鈕回饋 — collect / dislike / mute_event."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigFK, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    candidate_post_id: Mapped[int] = mapped_column(
        BigFK,
        ForeignKey("candidate_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    acted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    candidate: Mapped[CandidatePost] = relationship(back_populates="feedback_entries")

    __table_args__ = (
        Index("idx_feedback_candidate", "candidate_post_id"),
        Index("idx_feedback_user_action", "user_id", "action"),
    )


# --- 收藏追蹤層 ---------------------------------------------------------


class TrackedPost(Base, TimestampMixin):
    """被使用者 ❤️ 升格為追蹤對象的 candidate（v3：candidate_posts 的子集）."""

    __tablename__ = "tracked_posts"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    candidate_post_id: Mapped[int] = mapped_column(
        BigFK,
        ForeignKey("candidate_posts.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    user_id: Mapped[int | None] = mapped_column(
        BigFK, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    promoted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    polling_tier: Mapped[str] = mapped_column(
        String(16), default=PollingTier.HOT.value, nullable=False
    )
    last_polled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default=PostStatus.ACTIVE.value, nullable=False
    )
    initial_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    candidate: Mapped[CandidatePost] = relationship(back_populates="tracked_post")
    snapshots: Mapped[list["PostSnapshot"]] = relationship(
        back_populates="tracked_post", cascade="all, delete-orphan"
    )
    related_posts: Mapped[list["RelatedPost"]] = relationship(
        back_populates="tracked_post", cascade="all, delete-orphan"
    )
    qa_sessions: Mapped[list["QASession"]] = relationship(
        back_populates="tracked_post", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_tracked_polling", "polling_tier", "last_polled_at"),
        Index("idx_tracked_user", "user_id"),
    )


class PostSnapshot(Base):
    """時序資料 — 每次 polling 寫一筆."""

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
    """後續事件（四類：author_followup / author_reply / hot_reply / quote）."""

    __tablename__ = "related_posts"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    tracked_post_id: Mapped[int] = mapped_column(
        BigFK,
        ForeignKey("tracked_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    threads_post_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(16), nullable=False)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_milestone: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tracked_post: Mapped[TrackedPost] = relationship(back_populates="related_posts")

    __table_args__ = (Index("idx_related_post", "tracked_post_id", "posted_at"),)


# --- LLM 紀錄（統一） ----------------------------------------------------


class LLMRecord(Base):
    """所有 LLM 呼叫的統一紀錄（評分、摘要、問答都寫這）."""

    __tablename__ = "llm_records"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    related_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("idx_llm_purpose_related", "purpose", "related_id"),)


# --- 問答層 -------------------------------------------------------------


class QASession(Base):
    """問答 session — 同一使用者同時只能一個 active."""

    __tablename__ = "qa_sessions"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigFK, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tracked_post_id: Mapped[int] = mapped_column(
        BigFK,
        ForeignKey("tracked_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    context_mode: Mapped[str] = mapped_column(
        String(16), default=QAContextMode.HEAVY.value, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)

    tracked_post: Mapped[TrackedPost] = relationship(back_populates="qa_sessions")
    messages: Mapped[list["QAMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_qa_user_active", "user_id", "ended_at"),)


class QAMessage(Base):
    __tablename__ = "qa_messages"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        BigFK, ForeignKey("qa_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[QASession] = relationship(back_populates="messages")

    __table_args__ = (Index("idx_qa_msg_session", "session_id", "sent_at"),)


# --- 使用者 -------------------------------------------------------------


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False
    )
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONField, nullable=False, default=dict
    )


__all__ = [
    "Base",
    "CandidatePost",
    "DailyPush",
    "Feedback",
    "FeedbackAction",
    "KeywordSeed",
    "LLMPurpose",
    "LLMRecord",
    "PollingTier",
    "PostSnapshot",
    "PostStatus",
    "PushType",
    "QAContextMode",
    "QAEndReason",
    "QAMessage",
    "QASession",
    "RelatedPost",
    "RelationType",
    "ScoringRecord",
    "ScoringStage",
    "TrackedPost",
    "User",
]
