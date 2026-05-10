"""候選 → 追蹤的核心服務（v3 流程）.

v3 的入口是「探索層先寫 candidate_posts，使用者 ❤️ 後升格為 tracked_posts」。
v1 的「使用者貼 url 直接追蹤」流程已移除；測試與 polling 透過
``add_candidate`` + ``promote_candidate`` 模擬同一條路徑。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..logging import get_logger
from ..models import (
    CandidatePost,
    PollingTier,
    PostSnapshot,
    PostStatus,
    TrackedPost,
)
from ..scrapers.base import PostFetcher, PostPayload

logger = get_logger(__name__)


class TrackingService:
    def __init__(self, session: AsyncSession, fetcher: PostFetcher) -> None:
        self._session = session
        self._fetcher = fetcher

    # --- 候選層 ----------------------------------------------------------

    async def add_candidate(
        self,
        payload: PostPayload,
        *,
        discovery_source: str | None = None,
        author_follower_count: int | None = None,
    ) -> CandidatePost:
        """寫入一筆 candidate；同 ``threads_post_id`` 已存在則回傳既有紀錄."""
        existing = await self._get_candidate_by_threads_id(payload.threads_post_id)
        if existing is not None:
            return existing

        candidate = CandidatePost(
            threads_post_id=payload.threads_post_id,
            author_username=payload.author_username or None,
            author_follower_count=author_follower_count,
            post_url=payload.post_url or None,
            content=payload.content or None,
            posted_at=payload.posted_at,
            discovery_source=discovery_source,
            initial_likes=payload.like_count,
            initial_replies=payload.reply_count,
            initial_reposts=payload.repost_count,
            metadata_=payload.raw or None,
        )
        self._session.add(candidate)
        await self._session.flush()
        logger.info(
            "candidate.added",
            candidate_id=candidate.id,
            post_id=candidate.threads_post_id,
            source=discovery_source,
        )
        return candidate

    # --- 追蹤層 ----------------------------------------------------------

    async def promote_candidate(
        self,
        candidate_post_id: int,
        *,
        user_id: int | None = None,
    ) -> TrackedPost:
        """使用者按 ❤️ → 從 candidate_posts 升格為 tracked_posts；冪等."""
        existing = await self._get_tracked_by_candidate(candidate_post_id)
        if existing is not None:
            return existing

        candidate = await self._session.get(CandidatePost, candidate_post_id)
        if candidate is None:
            raise ValueError(f"Candidate #{candidate_post_id} not found")

        tracked = TrackedPost(
            candidate_post_id=candidate.id,
            user_id=user_id,
            polling_tier=PollingTier.HOT.value,
            status=PostStatus.ACTIVE.value,
        )
        self._session.add(tracked)
        await self._session.flush()

        # 升格瞬間先抓一次 snapshot，之後分級輪詢負責持續抓
        snapshot_payload = PostPayload(
            threads_post_id=candidate.threads_post_id,
            author_username=candidate.author_username or "",
            post_url=candidate.post_url or "",
            content=candidate.content or "",
            posted_at=candidate.posted_at,
            like_count=candidate.initial_likes or 0,
            reply_count=candidate.initial_replies or 0,
            repost_count=candidate.initial_reposts or 0,
        )
        await self._record_snapshot(tracked, snapshot_payload)
        await self._session.commit()

        logger.info(
            "track.promoted",
            tracked_id=tracked.id,
            candidate_id=candidate.id,
            user_id=user_id,
        )
        return tracked

    async def poll_once(self, tracked: TrackedPost) -> PostSnapshot:
        """重新抓取一次貼文並寫入 snapshot；不變更 polling_tier."""
        candidate = await self._ensure_candidate(tracked)
        if not candidate.post_url:
            raise RuntimeError(
                f"TrackedPost #{tracked.id} candidate has no post_url"
            )
        payload = await self._fetcher.fetch_post(candidate.post_url)
        snapshot = await self._record_snapshot(tracked, payload)
        tracked.last_polled_at = datetime.now(timezone.utc)
        await self._session.commit()
        return snapshot

    # --- internals -------------------------------------------------------

    async def _get_candidate_by_threads_id(
        self, threads_post_id: str
    ) -> CandidatePost | None:
        stmt = select(CandidatePost).where(
            CandidatePost.threads_post_id == threads_post_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _get_tracked_by_candidate(
        self, candidate_post_id: int
    ) -> TrackedPost | None:
        stmt = (
            select(TrackedPost)
            .where(TrackedPost.candidate_post_id == candidate_post_id)
            .options(selectinload(TrackedPost.candidate))
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _ensure_candidate(self, tracked: TrackedPost) -> CandidatePost:
        candidate = await self._session.get(CandidatePost, tracked.candidate_post_id)
        if candidate is None:
            raise RuntimeError(
                f"TrackedPost #{tracked.id} references missing candidate "
                f"#{tracked.candidate_post_id}"
            )
        return candidate

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
