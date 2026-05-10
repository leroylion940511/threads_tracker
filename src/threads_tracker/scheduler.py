"""APScheduler 排程器 — v3 三條 job：探索 / 追蹤輪詢 / 每日推送（M4）."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import get_settings
from .db import session_scope
from .logging import get_logger
from .scrapers.factory import get_fetcher
from .scrapers.watcher import WatcherDataSearchScraper
from .services.discovery import DiscoveryService
from .services.polling import run_polling_cycle

logger = get_logger(__name__)


async def _discovery_job() -> None:
    s = get_settings()
    if not s.apify_token:
        logger.warning("scheduler.discovery.skipped_no_token")
        return
    scraper = WatcherDataSearchScraper()
    try:
        async with session_scope() as session:
            service = DiscoveryService(session, scraper)
            result = await service.run_once(
                max_per_keyword=s.discovery_max_per_keyword,
                sort_by_recent=s.discovery_sort_by_recent,
            )
        logger.info(
            "scheduler.discovery.done",
            new=result.candidates_new,
            dedup=result.candidates_dedup,
            keywords=result.keywords_used,
        )
    finally:
        await scraper.aclose()


async def _polling_job() -> None:
    """追蹤層輪詢 — M5 接上 candidate-promote 流程後才會有資料."""
    fetcher = get_fetcher()
    async with session_scope() as session:
        await run_polling_cycle(session, fetcher)


async def _daily_push_job() -> None:
    """M4 將實作每日 09:00 Top 5 推送。"""
    logger.info("scheduler.daily_push.placeholder")


def build_scheduler() -> AsyncIOScheduler:
    s = get_settings()
    scheduler = AsyncIOScheduler(timezone="Asia/Taipei")

    scheduler.add_job(
        _discovery_job,
        trigger=IntervalTrigger(hours=s.discovery_interval_hours),
        id="discovery_cycle",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        _polling_job,
        trigger=IntervalTrigger(minutes=max(1, s.poll_hot_minutes // 3)),
        id="polling_cycle",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        _daily_push_job,
        trigger=CronTrigger(hour=9, minute=0),
        id="daily_push",
        replace_existing=True,
    )
    return scheduler
