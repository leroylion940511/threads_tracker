"""SummarizationService 行為測試（不打外部 API）."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from threads_tracker.db import Base
from threads_tracker.llm.opus import EvolutionSummary
from threads_tracker.models import (
    LLMSummary,
    RelatedPost,
    RelationType,
    SummaryType,
)
from threads_tracker.scrapers.fake import FakeThreadsScraper
from threads_tracker.services.summarization import (
    SummarizationService,
    parse_evolution,
)
from threads_tracker.services.tracking import TrackingService


@dataclass
class FakeSummarizer:
    calls: int = 0
    seen: list[dict] = field(default_factory=list)

    async def summarize_evolution(
        self,
        original_post: str,
        followups: list[str],
        top_replies: list[str],
    ) -> EvolutionSummary:
        self.calls += 1
        self.seen.append(
            {
                "original": original_post,
                "followups": list(followups),
                "top_replies": list(top_replies),
            }
        )
        return EvolutionSummary(
            narrative=f"敘事 #{self.calls}",
            milestones=["第一節點", "第二節點"],
            suggests_push=False,
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


async def _seed_post(session, *, polls: int = 2):
    service = TrackingService(session, FakeThreadsScraper())
    tracked = await service.add_tracked_post(
        "https://www.threads.net/@alice/post/EVOLVE1"
    )
    for _ in range(polls):
        await service.poll_once(tracked)
    return tracked


async def test_get_or_create_evolution_persists_and_caches(session):
    tracked = await _seed_post(session, polls=2)
    summarizer = FakeSummarizer()
    service = SummarizationService(session, summarizer)

    record = await service.get_or_create_evolution(tracked.id)
    assert record is not None
    assert summarizer.calls == 1
    assert record.summary_type == SummaryType.EVOLUTION.value
    parsed = parse_evolution(record)
    assert parsed.narrative == "敘事 #1"
    assert parsed.milestones == ["第一節點", "第二節點"]

    # cache hit — same summary returned, no extra LLM call
    again = await service.get_or_create_evolution(tracked.id)
    assert again is not None
    assert again.id == record.id
    assert summarizer.calls == 1

    # force=True bypasses cache
    forced = await service.get_or_create_evolution(tracked.id, force=True)
    assert forced is not None
    assert forced.id != record.id
    assert summarizer.calls == 2


async def test_evolution_cache_expires_after_window(session):
    tracked = await _seed_post(session)
    summarizer = FakeSummarizer()
    service = SummarizationService(session, summarizer, cache_hours=24)

    stale = LLMSummary(
        tracked_post_id=tracked.id,
        summary_type=SummaryType.EVOLUTION.value,
        model="opus",
        content=json.dumps(
            {"narrative": "舊", "milestones": [], "suggests_push": False}
        ),
        generated_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    session.add(stale)
    await session.commit()

    record = await service.get_or_create_evolution(tracked.id)
    assert record is not None
    assert summarizer.calls == 1
    assert parse_evolution(record).narrative == "敘事 #1"


async def test_get_or_create_evolution_unknown_post_returns_none(session):
    service = SummarizationService(session, FakeSummarizer())
    assert await service.get_or_create_evolution(99999) is None


async def test_get_or_create_evolution_requires_summarizer(session):
    tracked = await _seed_post(session)
    service = SummarizationService(session, summarizer=None)
    with pytest.raises(RuntimeError):
        await service.get_or_create_evolution(tracked.id)


async def test_top_replies_dedupe_by_id_and_pick_highest_likes(session):
    tracked = await _seed_post(session, polls=3)
    summarizer = FakeSummarizer()
    service = SummarizationService(session, summarizer)
    await service.get_or_create_evolution(tracked.id)

    seen = summarizer.seen[0]["top_replies"]
    # FakeThreadsScraper produces 3 reply ids per round; merged uniques == 3.
    assert len(seen) == 3
    # Reply id _r3 has like_count=3 and should rank first.
    assert seen[0].startswith("@user3:")


async def test_build_timeline_orders_events_chronologically(session):
    tracked = await _seed_post(session, polls=2)
    base = datetime.now(timezone.utc)
    session.add_all(
        [
            RelatedPost(
                tracked_post_id=tracked.id,
                threads_post_id="FOLLOW1",
                relation_type=RelationType.AUTHOR_FOLLOWUP.value,
                content="作者說明後續",
                posted_at=base + timedelta(hours=1),
            ),
            RelatedPost(
                tracked_post_id=tracked.id,
                threads_post_id="QUOTE1",
                relation_type=RelationType.QUOTE.value,
                content="他人引用討論",
                posted_at=base + timedelta(hours=2),
            ),
        ]
    )
    await session.commit()

    service = SummarizationService(session)
    items = await service.build_timeline(tracked.id)

    kinds = [it.kind for it in items]
    assert kinds[0] == "original"
    # all subsequent items must be sorted ascending
    times = [it.occurred_at for it in items]
    assert times == sorted(times)
    assert RelationType.AUTHOR_FOLLOWUP.value in kinds
    assert RelationType.QUOTE.value in kinds
    assert "metrics" in kinds


async def test_build_timeline_unknown_post_returns_empty(session):
    service = SummarizationService(session)
    assert await service.build_timeline(99999) == []
