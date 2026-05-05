"""APScheduler 排程器 — 驅動分級輪詢與每日彙整."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import get_settings
from .db import session_scope
from .logging import get_logger
from .scrapers.factory import get_fetcher
from .services.polling import run_polling_cycle

logger = get_logger(__name__)


async def _polling_job() -> None:
    fetcher = get_fetcher()
    async with session_scope() as session:
        await run_polling_cycle(session, fetcher)


async def _daily_digest_job() -> None:
    # TODO Week 5: 撰寫每日 21:00 彙整推播 (proposal §4.5)
    logger.info("scheduler.daily_digest.placeholder")


def build_scheduler() -> AsyncIOScheduler:
    s = get_settings()
    scheduler = AsyncIOScheduler(timezone="Asia/Taipei")

    scheduler.add_job(
        _polling_job,
        trigger=IntervalTrigger(minutes=max(1, s.poll_hot_minutes // 3)),
        id="polling_cycle",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        _daily_digest_job,
        trigger=CronTrigger(hour=21, minute=0),
        id="daily_digest",
        replace_existing=True,
    )
    return scheduler
