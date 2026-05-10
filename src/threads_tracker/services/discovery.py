"""探索層 — 用 keyword_seeds 餵 watcher.data，把結果寫進 candidate_posts.

設計選擇：一次 actor run 把所有 enabled keywords 一起餵下去，省去
per-run 的啟動開銷。代價是無法精準歸功「這篇貼文是哪個 keyword 抓到」，
所以 ``KeywordSeed.total_candidates_yielded`` 採用「本輪新增 candidate
數量 / 本輪 keyword 數」均分計入（M3 / M7 評估時若要看單一 keyword
表現再切回 per-keyword 模式）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..logging import get_logger
from ..models import CandidatePost, KeywordSeed
from ..scrapers.watcher import WatcherDataSearchScraper
from .tracking import TrackingService

logger = get_logger(__name__)


@dataclass(slots=True)
class DiscoveryResult:
    keywords_used: int
    candidates_returned: int
    candidates_new: int
    candidates_dedup: int


class DiscoveryService:
    def __init__(
        self,
        session: AsyncSession,
        scraper: WatcherDataSearchScraper,
    ) -> None:
        self._session = session
        self._scraper = scraper

    async def run_once(
        self,
        *,
        max_per_keyword: int = 2,
        sort_by_recent: bool = True,
    ) -> DiscoveryResult:
        keywords = await self._enabled_keywords()
        if not keywords:
            logger.warning("discovery.no_seeds")
            return DiscoveryResult(0, 0, 0, 0)

        kw_strings = [k.keyword for k in keywords]
        logger.info(
            "discovery.run_start",
            keyword_count=len(kw_strings),
            max_per_keyword=max_per_keyword,
        )

        payloads = await self._scraper.search_keywords(
            keywords=kw_strings,
            max_per_keyword=max_per_keyword,
            sort_by_recent=sort_by_recent,
        )

        tracking = TrackingService(self._session)
        new_count = 0
        dedup_count = 0
        seen_existing_ids: set[int] = set()

        for payload in payloads:
            if not payload.threads_post_id:
                continue
            existing_id = await self._existing_candidate_id(payload.threads_post_id)
            if existing_id is not None:
                seen_existing_ids.add(existing_id)
                dedup_count += 1
                continue
            await tracking.add_candidate(
                payload,
                discovery_source=f"keyword_batch:{len(kw_strings)}",
                author_follower_count=_extract_follower(payload.raw),
            )
            new_count += 1

        await self._session.flush()
        await self._update_seed_stats(keywords, new_for_seed=new_count)
        await self._session.commit()

        logger.info(
            "discovery.run_done",
            returned=len(payloads),
            new=new_count,
            dedup=dedup_count,
        )
        return DiscoveryResult(
            keywords_used=len(kw_strings),
            candidates_returned=len(payloads),
            candidates_new=new_count,
            candidates_dedup=dedup_count,
        )

    async def _enabled_keywords(self) -> list[KeywordSeed]:
        stmt = (
            select(KeywordSeed)
            .where(KeywordSeed.enabled.is_(True))
            .order_by(KeywordSeed.id.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def _existing_candidate_id(self, threads_post_id: str) -> int | None:
        stmt = select(CandidatePost.id).where(
            CandidatePost.threads_post_id == threads_post_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _update_seed_stats(
        self, keywords: list[KeywordSeed], *, new_for_seed: int
    ) -> None:
        """均分 yielded 給每個 keyword（無法精準歸功；見模組 docstring）."""
        if not keywords:
            return
        share = new_for_seed // len(keywords) if new_for_seed else 0
        leftover = new_for_seed - share * len(keywords) if new_for_seed else 0
        now = datetime.now(timezone.utc)
        ids = [k.id for k in keywords]
        await self._session.execute(
            update(KeywordSeed)
            .where(KeywordSeed.id.in_(ids))
            .values(
                last_polled_at=now,
                total_candidates_yielded=KeywordSeed.total_candidates_yielded + share,
            )
        )
        if leftover and ids:
            await self._session.execute(
                update(KeywordSeed)
                .where(KeywordSeed.id == ids[0])
                .values(
                    total_candidates_yielded=KeywordSeed.total_candidates_yielded
                    + leftover
                )
            )


def _extract_follower(raw: dict | None) -> int | None:
    if not raw:
        return None
    val = raw.get("follower_count")
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
