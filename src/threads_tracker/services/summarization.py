"""Opus 摘要 + 純資料時間軸（v3 用 LLMRecord、candidate-based 內容）.

兩個職責：
- ``get_or_create_evolution``：把 original_post + 作者後續 + 熱門留言餵 Opus，
  寫進 ``llm_records`` (purpose=evolution)；24h 內同一貼文不重算（cache）。
- ``build_timeline``：純資料拼貼（snapshots + related_posts），不打 LLM。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..llm.base import EvolutionSummary
from ..logging import get_logger
from ..models import (
    LLMPurpose,
    LLMRecord,
    PostSnapshot,
    RelatedPost,
    RelationType,
    TrackedPost,
)

logger = get_logger(__name__)

DEFAULT_CACHE_HOURS = 24
TOP_REPLIES_K = 5
TIMELINE_DETAIL_CHARS = 200


class EvolutionSummarizer(Protocol):
    async def summarize_evolution(
        self,
        original_post: str,
        followups: list[str],
        top_replies: list[str],
    ) -> EvolutionSummary: ...


@dataclass(slots=True)
class TimelineItem:
    occurred_at: datetime
    kind: str  # "original" | "metrics" | author_followup | quote | author_reply | hot_reply
    title: str
    detail: str | None = None


class SummarizationService:
    def __init__(
        self,
        session: AsyncSession,
        summarizer: EvolutionSummarizer | None = None,
        *,
        cache_hours: int = DEFAULT_CACHE_HOURS,
    ) -> None:
        self._session = session
        self._summarizer = summarizer
        self._cache = timedelta(hours=cache_hours)

    async def get_or_create_evolution(
        self, tracked_post_id: int, *, force: bool = False
    ) -> LLMRecord | None:
        tracked = await self._load_tracked(tracked_post_id)
        if tracked is None:
            return None

        if not force:
            cached = await self._latest_evolution(tracked_post_id)
            if cached is not None and self._is_fresh(cached.generated_at):
                logger.info(
                    "summary.cache_hit",
                    tracked_post_id=tracked_post_id,
                    summary_id=cached.id,
                )
                return cached

        if self._summarizer is None:
            raise RuntimeError("summarizer is required to generate a new summary")

        followups = await self._fetch_followups(tracked_post_id)
        top_replies = await self._fetch_top_replies(tracked_post_id)
        original = (tracked.candidate.content if tracked.candidate else None) or ""

        result = await self._summarizer.summarize_evolution(
            original_post=original,
            followups=[f.content or "" for f in followups if f.content],
            top_replies=top_replies,
        )

        record = LLMRecord(
            purpose=LLMPurpose.EVOLUTION.value,
            related_id=tracked_post_id,
            model="opus",
            content=json.dumps(asdict(result), ensure_ascii=False),
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        logger.info(
            "summary.generated",
            tracked_post_id=tracked_post_id,
            summary_id=record.id,
            milestones=len(result.milestones),
        )
        return record

    async def build_timeline(self, tracked_post_id: int) -> list[TimelineItem]:
        tracked = await self._load_tracked(tracked_post_id)
        if tracked is None:
            return []
        candidate = tracked.candidate

        items: list[TimelineItem] = [
            TimelineItem(
                occurred_at=_aware(tracked.promoted_at),
                kind="original",
                title=f"@{candidate.author_username if candidate else '?'} 原貼文",
                detail=_clip(candidate.content if candidate else None),
            )
        ]

        snapshots = await self._fetch_snapshots(tracked_post_id)
        prev: PostSnapshot | None = None
        for cur in snapshots:
            if prev is None:
                title = (
                    f"首次抓取：{cur.like_count or 0} 讚 / "
                    f"{cur.reply_count or 0} 留言"
                )
            else:
                d_likes = (cur.like_count or 0) - (prev.like_count or 0)
                d_replies = (cur.reply_count or 0) - (prev.reply_count or 0)
                if d_likes == 0 and d_replies == 0:
                    prev = cur
                    continue
                title = f"+{d_likes} 讚 / +{d_replies} 留言"
            items.append(
                TimelineItem(
                    occurred_at=_aware(cur.captured_at),
                    kind="metrics",
                    title=title,
                )
            )
            prev = cur

        related = await self._fetch_related(tracked_post_id)
        for r in related:
            label = _RELATION_LABELS.get(r.relation_type, r.relation_type)
            items.append(
                TimelineItem(
                    occurred_at=_aware(r.posted_at or r.discovered_at),
                    kind=r.relation_type,
                    title=label,
                    detail=_clip(r.content),
                )
            )

        items.sort(key=lambda x: x.occurred_at)
        return items

    # --- internals --------------------------------------------------------

    async def _load_tracked(self, tracked_post_id: int) -> TrackedPost | None:
        stmt = (
            select(TrackedPost)
            .where(TrackedPost.id == tracked_post_id)
            .options(selectinload(TrackedPost.candidate))
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _latest_evolution(self, tracked_post_id: int) -> LLMRecord | None:
        stmt = (
            select(LLMRecord)
            .where(
                LLMRecord.purpose == LLMPurpose.EVOLUTION.value,
                LLMRecord.related_id == tracked_post_id,
            )
            .order_by(LLMRecord.generated_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    def _is_fresh(self, generated_at: datetime | None) -> bool:
        if generated_at is None:
            return False
        return datetime.now(timezone.utc) - _aware(generated_at) < self._cache

    async def _fetch_followups(self, tracked_post_id: int) -> list[RelatedPost]:
        stmt = (
            select(RelatedPost)
            .where(
                RelatedPost.tracked_post_id == tracked_post_id,
                RelatedPost.relation_type == RelationType.AUTHOR_FOLLOWUP.value,
            )
            .order_by(RelatedPost.posted_at.asc().nulls_last())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def _fetch_related(self, tracked_post_id: int) -> list[RelatedPost]:
        stmt = (
            select(RelatedPost)
            .where(RelatedPost.tracked_post_id == tracked_post_id)
            .order_by(RelatedPost.posted_at.asc().nulls_last())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def _fetch_snapshots(self, tracked_post_id: int) -> list[PostSnapshot]:
        stmt = (
            select(PostSnapshot)
            .where(PostSnapshot.tracked_post_id == tracked_post_id)
            .order_by(PostSnapshot.captured_at.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def _fetch_top_replies(self, tracked_post_id: int) -> list[str]:
        snapshots = await self._fetch_snapshots(tracked_post_id)
        merged: dict[str, dict[str, Any]] = {}
        for s in snapshots:
            for r in s.new_replies or []:
                rid = r.get("id") or r.get("threads_post_id")
                if rid is None:
                    continue
                existing = merged.get(rid)
                if existing is None or (r.get("like_count") or 0) > (
                    existing.get("like_count") or 0
                ):
                    merged[rid] = r
        ranked = sorted(
            merged.values(),
            key=lambda r: (r.get("like_count") or 0),
            reverse=True,
        )
        out: list[str] = []
        for r in ranked:
            content = (r.get("content") or "").strip()
            if not content:
                continue
            author = r.get("author") or "?"
            out.append(f"@{author}: {content}")
            if len(out) >= TOP_REPLIES_K:
                break
        return out


_RELATION_LABELS = {
    RelationType.AUTHOR_FOLLOWUP.value: "作者後續",
    RelationType.AUTHOR_REPLY.value: "作者回留言",
    RelationType.HOT_REPLY.value: "熱門留言",
    RelationType.QUOTE.value: "他人引用",
}


def parse_evolution(record: LLMRecord) -> EvolutionSummary:
    """把 LLMRecord.content 還原成 EvolutionSummary（給 bot 顯示用）."""
    data = json.loads(record.content or "{}")
    return EvolutionSummary(
        narrative=data.get("narrative", ""),
        milestones=list(data.get("milestones", [])),
        suggests_push=bool(data.get("suggests_push", False)),
    )


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _clip(text: str | None) -> str | None:
    if not text:
        return None
    text = text.strip()
    if len(text) <= TIMELINE_DETAIL_CHARS:
        return text
    return text[: TIMELINE_DETAIL_CHARS - 1] + "…"


__all__ = [
    "EvolutionSummarizer",
    "SummarizationService",
    "TimelineItem",
    "parse_evolution",
]
