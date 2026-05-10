"""Pydantic schemas for the HTTP API（v3）."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CandidatePostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    threads_post_id: str
    author_username: str | None
    post_url: str | None
    content: str | None
    posted_at: datetime | None
    discovered_at: datetime
    discovery_source: str | None
    initial_likes: int | None
    initial_replies: int | None
    initial_reposts: int | None


class TrackedPostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_post_id: int
    user_id: int | None
    promoted_at: datetime
    polling_tier: str
    status: str
    last_polled_at: datetime | None


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    captured_at: datetime
    like_count: int | None
    reply_count: int | None
    repost_count: int | None
