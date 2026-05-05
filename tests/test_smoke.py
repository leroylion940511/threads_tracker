"""Smoke tests — boot the system end-to-end with the fake scraper."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from threads_tracker.api import app
from threads_tracker.db import Base
from threads_tracker.models import PostSnapshot, TrackedPost
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


async def test_add_tracked_post_creates_snapshot(session):
    service = TrackingService(session, FakeThreadsScraper())
    tracked = await service.add_tracked_post(
        "https://www.threads.net/@alice/post/ABC123"
    )

    assert tracked.id is not None
    assert tracked.author_username == "alice"
    assert tracked.threads_post_id == "ABC123"
    assert tracked.polling_tier == "hot"

    refreshed = await session.get(TrackedPost, tracked.id)
    assert refreshed is not None
    snaps = (await session.execute(
        PostSnapshot.__table__.select().where(
            PostSnapshot.tracked_post_id == tracked.id
        )
    )).all()
    assert len(snaps) == 1


async def test_poll_once_appends_snapshot_with_growing_counts(session):
    fetcher = FakeThreadsScraper()
    service = TrackingService(session, fetcher)
    tracked = await service.add_tracked_post(
        "https://www.threads.net/@bob/post/XYZ789"
    )
    await service.poll_once(tracked)
    await service.poll_once(tracked)

    snaps = (await session.execute(
        PostSnapshot.__table__.select()
        .where(PostSnapshot.tracked_post_id == tracked.id)
        .order_by(PostSnapshot.captured_at.asc())
    )).all()
    likes = [r.like_count for r in snaps]
    assert likes == sorted(likes), "fake fetcher should return monotonically growing counts"


def test_tier_for_age_boundaries():
    now = datetime.now(timezone.utc)
    assert tier_for_age(now - timedelta(hours=1), now=now).value == "hot"
    assert tier_for_age(now - timedelta(days=2), now=now).value == "warm"
    assert tier_for_age(now - timedelta(days=10), now=now).value == "cold"
    assert tier_for_age(now - timedelta(days=40), now=now) is None


async def test_detection_neither_signal_when_no_data(session):
    service = TrackingService(session, FakeThreadsScraper())
    tracked = await service.add_tracked_post(
        "https://www.threads.net/@carol/post/HOT001"
    )
    signal = await evaluate_hot_signal(session, tracked.id)
    assert signal.is_hot is False


async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
