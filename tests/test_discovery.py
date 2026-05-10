"""DiscoveryService + seed loader 測試（不打 Apify）."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from threads_tracker.db import Base
from threads_tracker.models import CandidatePost, KeywordSeed
from threads_tracker.scrapers.base import PostPayload
from threads_tracker.seeds.keyword_seeds import KEYWORD_SEEDS
from threads_tracker.seeds.loader import load_seeds
from threads_tracker.services.discovery import DiscoveryService


@dataclass
class FakeWatcher:
    payloads: list[PostPayload]
    last_call: dict = field(default_factory=dict)

    async def search_keywords(
        self,
        keywords: list[str],
        max_per_keyword: int = 20,
        sort_by_recent: bool = True,
    ) -> list[PostPayload]:
        self.last_call = {
            "keywords": keywords,
            "max_per_keyword": max_per_keyword,
            "sort_by_recent": sort_by_recent,
        }
        return list(self.payloads)


def _payload(pid: str, author: str = "u", likes: int = 1) -> PostPayload:
    return PostPayload(
        threads_post_id=pid,
        author_username=author,
        post_url=f"https://www.threads.net/@{author}/post/{pid}",
        content=f"content {pid}",
        posted_at=datetime.now(timezone.utc),
        like_count=likes,
        reply_count=0,
        repost_count=0,
        raw={"follower_count": 100},
    )


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


# --- seed loader ---------------------------------------------------------


async def test_seed_loader_inserts_all_seeds(session):
    result = await load_seeds(session)
    assert result.inserted == len(KEYWORD_SEEDS)
    assert result.existing == 0

    rows = (await session.execute(select(KeywordSeed))).scalars().all()
    assert len(rows) == len(KEYWORD_SEEDS)

    categories = {r.category for r in rows}
    assert categories == {"follow_up", "help_empathy", "event", "narrative", "emotion"}


async def test_seed_loader_is_idempotent(session):
    await load_seeds(session)
    result = await load_seeds(session)
    assert result.inserted == 0
    assert result.existing == len(KEYWORD_SEEDS)


# --- discovery -----------------------------------------------------------


async def test_discovery_writes_candidates_and_updates_stats(session):
    await load_seeds(session)
    watcher = FakeWatcher(
        payloads=[_payload("P1"), _payload("P2"), _payload("P3")]
    )
    service = DiscoveryService(session, watcher)  # type: ignore[arg-type]

    result = await service.run_once(max_per_keyword=2)

    assert result.candidates_returned == 3
    assert result.candidates_new == 3
    assert result.candidates_dedup == 0
    assert result.keywords_used == len(KEYWORD_SEEDS)

    # call routed correct keywords + max
    assert watcher.last_call["max_per_keyword"] == 2
    assert len(watcher.last_call["keywords"]) == len(KEYWORD_SEEDS)

    # candidates landed
    candidates = (await session.execute(select(CandidatePost))).scalars().all()
    assert {c.threads_post_id for c in candidates} == {"P1", "P2", "P3"}
    # follower count extracted from raw
    assert candidates[0].author_follower_count == 100

    # seeds got bumped
    seeds = (await session.execute(select(KeywordSeed))).scalars().all()
    assert all(s.last_polled_at is not None for s in seeds)
    assert sum(s.total_candidates_yielded for s in seeds) == 3


async def test_discovery_dedup_existing_post(session):
    await load_seeds(session)
    watcher = FakeWatcher(payloads=[_payload("P1"), _payload("P2")])
    service = DiscoveryService(session, watcher)  # type: ignore[arg-type]

    first = await service.run_once(max_per_keyword=2)
    assert first.candidates_new == 2

    # Same payloads on second run → all dedup'd
    second = await service.run_once(max_per_keyword=2)
    assert second.candidates_new == 0
    assert second.candidates_dedup == 2

    rows = (await session.execute(select(CandidatePost))).scalars().all()
    assert len(rows) == 2


async def test_discovery_no_enabled_seeds(session):
    # Don't load seeds; table is empty
    watcher = FakeWatcher(payloads=[])
    service = DiscoveryService(session, watcher)  # type: ignore[arg-type]
    result = await service.run_once()
    assert result.keywords_used == 0
    assert result.candidates_returned == 0
    assert watcher.last_call == {}


async def test_discovery_skips_disabled_seed(session):
    await load_seeds(session)
    # Disable the first seed
    seed = (
        await session.execute(select(KeywordSeed).order_by(KeywordSeed.id).limit(1))
    ).scalar_one()
    seed.enabled = False
    await session.commit()

    watcher = FakeWatcher(payloads=[])
    service = DiscoveryService(session, watcher)  # type: ignore[arg-type]
    result = await service.run_once()

    assert result.keywords_used == len(KEYWORD_SEEDS) - 1
    assert seed.keyword not in watcher.last_call["keywords"]
