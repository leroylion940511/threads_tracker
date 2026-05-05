"""核心追蹤服務 — 處理 /track、輪詢更新、寫入 snapshot."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..logging import get_logger
from ..models import (
    DetectionSource,
    PollingTier,
    PostSnapshot,
    PostStatus,
    TrackedPost,
)
from ..scrapers.base import PostFetcher, PostPayload, parse_threads_url

logger = get_logger(__name__)


class TrackingService:
    def __init__(self, session: AsyncSession, fetcher: PostFetcher) -> None:
        self._session = session
        self._fetcher = fetcher

    async def add_tracked_post(
        self,
        post_url: str,
        *,
        source: DetectionSource = DetectionSource.MANUAL,
    ) -> TrackedPost:
        """加入新貼文到追蹤清單；若已存在則回傳既有紀錄."""
        parse_threads_url(post_url)  # validate

        payload = await self._fetcher.fetch_post(post_url)
        existing = await self._get_by_threads_id(payload.threads_post_id)
        if existing:
            logger.info("track.already_exists", post_id=payload.threads_post_id)
            return existing

        tracked = TrackedPost(
            threads_post_id=payload.threads_post_id,
            author_username=payload.author_username,
            post_url=payload.post_url or post_url,
            original_content=payload.content,
            detection_source=source.value,
            status=PostStatus.ACTIVE.value,
            polling_tier=PollingTier.HOT.value,
        )
        self._session.add(tracked)
        await self._session.flush()

        await self._record_snapshot(tracked, payload)
        await self._session.commit()
        logger.info(
            "track.added",
            tracked_id=tracked.id,
            post_id=tracked.threads_post_id,
            author=tracked.author_username,
        )
        return tracked

    async def poll_once(self, tracked: TrackedPost) -> PostSnapshot:
        """重新抓取一次貼文並寫入 snapshot；不變更 polling_tier（由排程器決定）."""
        payload = await self._fetcher.fetch_post(tracked.post_url)
        snapshot = await self._record_snapshot(tracked, payload)
        tracked.last_polled_at = datetime.now(timezone.utc)
        await self._session.commit()
        return snapshot

    # --- internals ---------------------------------------------------------

    async def _get_by_threads_id(self, threads_post_id: str) -> TrackedPost | None:
        stmt = select(TrackedPost).where(
            TrackedPost.threads_post_id == threads_post_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _record_snapshot(
        self, tracked: TrackedPost, payload: PostPayload
    ) -> PostSnapshot:
        snapshot = PostSnapshot(
            tracked_post_id=tracked.id,
            like_count=payload.like_count,
            reply_count=payload.reply_count,
            repost_count=payload.repost_count,
            new_replies=[
                {
                    "id": r.threads_post_id,
                    "author": r.author_username,
                    "content": r.content,
                    "like_count": r.like_count,
                    "is_author_reply": r.is_author_reply,
                    "posted_at": r.posted_at.isoformat() if r.posted_at else None,
                }
                for r in payload.replies
            ],
        )
        self._session.add(snapshot)
        return snapshot
