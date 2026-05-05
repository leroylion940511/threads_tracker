"""Pydantic schemas for the HTTP API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class TrackRequest(BaseModel):
    post_url: HttpUrl = Field(..., description="Threads 貼文連結")


class TrackedPostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    threads_post_id: str
    author_username: str
    post_url: str
    original_content: str | None
    detected_at: datetime
    detection_source: str
    status: str
    polling_tier: str
    last_polled_at: datetime | None


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    captured_at: datetime
    like_count: int | None
    reply_count: int | None
    repost_count: int | None
