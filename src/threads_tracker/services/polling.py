"""分級輪詢策略（提案 §4.4）."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..logging import get_logger
from ..models import PollingTier, PostStatus, TrackedPost
from ..scrapers.base import PostFetcher
from .tracking import TrackingService

logger = get_logger(__name__)


def tier_for_age(detected_at: datetime, *, now: datetime | None = None) -> PollingTier | None:
    """0–24h: HOT, 1–7d: WARM, 7–30d: COLD, >30d: archive."""
    now = now or datetime.now(timezone.utc)
    age = now - detected_at
    if age < timedelta(days=1):
        return PollingTier.HOT
    if age < timedelta(days=7):
        return PollingTier.WARM
    if age < timedelta(days=30):
        return PollingTier.COLD
    return None  # archive


def poll_interval_minutes(tier: PollingTier) -> int:
    s = get_settings()
    return {
        PollingTier.HOT: s.poll_hot_minutes,
        PollingTier.WARM: s.poll_warm_minutes,
        PollingTier.COLD: s.poll_cold_minutes,
    }[tier]


async def select_due_posts(
    session: AsyncSession, *, now: datetime | None = None, limit: int = 50
) -> list[TrackedPost]:
    """挑出本次排程要重新輪詢的貼文."""
    now = now or datetime.now(timezone.utc)
    stmt = (
        select(TrackedPost)
        .where(TrackedPost.status == PostStatus.ACTIVE.value)
        .order_by(TrackedPost.last_polled_at.asc().nulls_first())
        .limit(limit * 4)  # over-fetch then filter in Python by tier interval
    )
    candidates = list((await session.execute(stmt)).scalars().all())

    due: list[TrackedPost] = []
    for p in candidates:
        tier = PollingTier(p.polling_tier)
        interval = timedelta(minutes=poll_interval_minutes(tier))
        if p.last_polled_at is None or now - p.last_polled_at >= interval:
            due.append(p)
        if len(due) >= limit:
            break
    return due


async def reconcile_tiers(session: AsyncSession, *, now: datetime | None = None) -> int:
    """根據 promoted_at 把每個 active post 的 polling_tier 重新對齊；超過 30 天歸檔."""
    now = now or datetime.now(timezone.utc)
    stmt = select(TrackedPost).where(TrackedPost.status == PostStatus.ACTIVE.value)
    posts = list((await session.execute(stmt)).scalars().all())

    changed = 0
    for p in posts:
        new_tier = tier_for_age(p.promoted_at, now=now)
        if new_tier is None:
            if p.status != PostStatus.ARCHIVED.value:
                p.status = PostStatus.ARCHIVED.value
                changed += 1
            continue
        if p.polling_tier != new_tier.value:
            logger.info(
                "polling.tier_changed",
                tracked_id=p.id,
                old=p.polling_tier,
                new=new_tier.value,
            )
            p.polling_tier = new_tier.value
            changed += 1
    if changed:
        await session.commit()
    return changed


async def run_polling_cycle(session: AsyncSession, fetcher: PostFetcher) -> int:
    """單次排程觸發：對齊 tier → 抓出 due 的貼文 → 逐一重新抓取."""
    await reconcile_tiers(session)
    due = await select_due_posts(session)
    service = TrackingService(session, fetcher)
    n = 0
    for tracked in due:
        try:
            await service.poll_once(tracked)
            n += 1
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "polling.fetch_failed",
                tracked_id=tracked.id,
                error=str(exc),
            )
    logger.info("polling.cycle_done", polled=n, due=len(due))
    return n
