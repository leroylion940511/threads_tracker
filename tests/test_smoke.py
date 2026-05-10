"""Smoke tests — boot the system end-to-end with the fake scraper (v3 schema)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from threads_tracker.api import app
from threads_tracker.db import Base
from threads_tracker.models import PostSnapshot, TrackedPost
from threads_tracker.scrapers.base import PostPayload, parse_threads_url
from threads_tracker.scrapers.fake import FakeThreadsScraper
from threads_tracker.services.detection import evaluate_hot_signal
from threads_tracker.services.polling import tier_for_age
from threads_tracker.services.tracking import TrackingService


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def _seed_tracked(
    session,
    fetcher: FakeThreadsScraper,
    url: str = "https://www.threads.net/@alice/post/ABC123",
) -> TrackedPost:
    """v3 流程：fake fetch → add_candidate → promote → tracked."""
    parse_threads_url(url)  # validate
    payload = await fetcher.fetch_post(url)
    service = TrackingService(session, fetcher)
    candidate = await service.add_candidate(payload, discovery_source="test")
    return await service.promote_candidate(candidate.id)


async def test_promote_candidate_creates_tracked_with_snapshot(session):
    fetcher = FakeThreadsScraper()
    tracked = await _seed_tracked(session, fetcher)

    assert tracked.id is not None
    assert tracked.candidate_post_id is not None
    assert tracked.polling_tier == "hot"

    refreshed = await session.get(TrackedPost, tracked.id)
    assert refreshed is not None
    snaps = (
        await session.execute(
            PostSnapshot.__table__.select().where(
                PostSnapshot.tracked_post_id == tracked.id
            )
        )
    ).all()
    assert len(snaps) == 1


async def test_poll_once_appends_snapshot_with_growing_counts(session):
    fetcher = FakeThreadsScraper()
    tracked = await _seed_tracked(
        session, fetcher, "https://www.threads.net/@bob/post/XYZ789"
    )
    service = TrackingService(session, fetcher)
    await service.poll_once(tracked)
    await service.poll_once(tracked)

    snaps = (
        await session.execute(
            PostSnapshot.__table__.select()
            .where(PostSnapshot.tracked_post_id == tracked.id)
            .order_by(PostSnapshot.captured_at.asc())
        )
    ).all()
    likes = [r.like_count for r in snaps]
    assert likes == sorted(likes), "fake fetcher should return monotonically growing counts"


def test_tier_for_age_boundaries():
    now = datetime.now(timezone.utc)
    assert tier_for_age(now - timedelta(hours=1), now=now).value == "hot"
    assert tier_for_age(now - timedelta(days=2), now=now).value == "warm"
    assert tier_for_age(now - timedelta(days=10), now=now).value == "cold"
    assert tier_for_age(now - timedelta(days=40), now=now) is None


async def test_detection_neither_signal_when_no_data(session):
    fetcher = FakeThreadsScraper()
    tracked = await _seed_tracked(
        session, fetcher, "https://www.threads.net/@carol/post/HOT001"
    )
    signal = await evaluate_hot_signal(session, tracked.id)
    # Promotion writes 1 baseline snapshot; growth ratio needs ≥2 snapshots.
    assert signal.is_hot is False


async def test_candidate_dedup_by_threads_post_id(session):
    fetcher = FakeThreadsScraper()
    payload = await fetcher.fetch_post("https://www.threads.net/@dan/post/DUP001")
    service = TrackingService(session, fetcher)

    a = await service.add_candidate(payload, discovery_source="kw:test1")
    b = await service.add_candidate(payload, discovery_source="kw:test2")
    assert a.id == b.id, "same threads_post_id must collapse to one candidate row"


async def test_promote_is_idempotent(session):
    fetcher = FakeThreadsScraper()
    payload = await fetcher.fetch_post("https://www.threads.net/@eve/post/IDEM1")
    service = TrackingService(session, fetcher)
    candidate = await service.add_candidate(payload)

    t1 = await service.promote_candidate(candidate.id, user_id=42)
    t2 = await service.promote_candidate(candidate.id, user_id=42)
    assert t1.id == t2.id


async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# Construct a non-fetcher PostPayload directly to keep this test independent.
def _make_payload() -> PostPayload:
    return PostPayload(
        threads_post_id="STATIC1",
        author_username="static",
        post_url="https://www.threads.net/@static/post/STATIC1",
        content="hello",
    )
