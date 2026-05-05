"""FastAPI application + minimal HTTP API.

Telegram bot is the primary user surface; this HTTP layer exists for ops
visibility (health, current tracked posts, manual triggers) and for the
Apify webhook callback that some actor configurations need.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .logging import configure_logging, get_logger
from .models import DetectionSource, PostSnapshot, TrackedPost
from .schemas import SnapshotOut, TrackedPostOut, TrackRequest
from .scheduler import build_scheduler
from .scrapers.factory import get_fetcher
from .services.tracking import TrackingService

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    scheduler = build_scheduler()
    scheduler.start()
    logger.info("api.startup", scheduler_jobs=[j.id for j in scheduler.get_jobs()])
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        logger.info("api.shutdown")


app = FastAPI(title="Threads Tracker", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/tracked-posts", response_model=TrackedPostOut)
async def track_post(
    body: TrackRequest,
    session: AsyncSession = Depends(get_session),
) -> TrackedPostOut:
    fetcher = get_fetcher()
    service = TrackingService(session, fetcher)
    try:
        tracked = await service.add_tracked_post(
            str(body.post_url), source=DetectionSource.MANUAL
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return TrackedPostOut.model_validate(tracked)


@app.get("/api/tracked-posts", response_model=list[TrackedPostOut])
async def list_tracked(
    session: AsyncSession = Depends(get_session),
) -> list[TrackedPostOut]:
    stmt = select(TrackedPost).order_by(TrackedPost.detected_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [TrackedPostOut.model_validate(r) for r in rows]


@app.get("/api/tracked-posts/{tracked_id}/snapshots", response_model=list[SnapshotOut])
async def list_snapshots(
    tracked_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[SnapshotOut]:
    stmt = (
        select(PostSnapshot)
        .where(PostSnapshot.tracked_post_id == tracked_id)
        .order_by(PostSnapshot.captured_at.desc())
        .limit(100)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [SnapshotOut.model_validate(r) for r in rows]
