"""爆紅偵測（提案 §4.1）— 雙訊號規則：絕對門檻 + 1 小時相對成長率."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import PostSnapshot


@dataclass(slots=True)
class HotSignal:
    is_hot: bool
    reason: str
    like_count: int
    reply_count: int
    growth_ratio: float | None


async def evaluate_hot_signal(
    session: AsyncSession, tracked_post_id: int
) -> HotSignal:
    """判定一則被追蹤貼文是否處於爆紅狀態."""
    s = get_settings()
    snapshots = await _recent_snapshots(session, tracked_post_id, hours=2)
    if not snapshots:
        return HotSignal(False, "no snapshots yet", 0, 0, None)

    latest = snapshots[0]
    likes = latest.like_count or 0
    replies = latest.reply_count or 0

    absolute_ok = (
        likes >= s.hot_like_threshold or replies >= s.hot_reply_threshold
    )

    growth_ratio = _growth_ratio(snapshots)
    relative_ok = growth_ratio is not None and growth_ratio >= s.hot_growth_ratio

    if absolute_ok and relative_ok:
        return HotSignal(True, "absolute+relative match", likes, replies, growth_ratio)
    if absolute_ok:
        return HotSignal(False, "absolute only — no growth signal", likes, replies, growth_ratio)
    if relative_ok:
        return HotSignal(False, "growth only — under absolute threshold", likes, replies, growth_ratio)
    return HotSignal(False, "neither signal", likes, replies, growth_ratio)


def _growth_ratio(snapshots: Sequence[PostSnapshot]) -> float | None:
    """以最近 ~1 小時前的快照為基準，計算互動數成長率."""
    if len(snapshots) < 2:
        return None

    latest = snapshots[0]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    baseline = next(
        (s for s in snapshots if s.captured_at and s.captured_at <= cutoff),
        snapshots[-1],
    )

    base_total = (baseline.like_count or 0) + (baseline.reply_count or 0)
    latest_total = (latest.like_count or 0) + (latest.reply_count or 0)
    if base_total == 0:
        return None
    return (latest_total - base_total) / base_total


async def _recent_snapshots(
    session: AsyncSession, tracked_post_id: int, hours: int
) -> list[PostSnapshot]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    stmt = (
        select(PostSnapshot)
        .where(
            PostSnapshot.tracked_post_id == tracked_post_id,
            PostSnapshot.captured_at >= cutoff,
        )
        .order_by(PostSnapshot.captured_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())
