"""FastAPI application + minimal HTTP API.

Telegram bot is the primary user surface; this HTTP layer exists for ops
visibility (health, current tracked / candidate posts) and for the Apify
webhook callback that some actor configurations need.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .logging import configure_logging, get_logger
from .models import CandidatePost, PostSnapshot, TrackedPost
from .schemas import CandidatePostOut, SnapshotOut, TrackedPostOut
from .scheduler import build_scheduler

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


app = FastAPI(title="Threads Tracker", version="0.2.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/candidates", response_model=list[CandidatePostOut])
async def list_candidates(
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
) -> list[CandidatePostOut]:
    stmt = (
        select(CandidatePost)
        .order_by(CandidatePost.discovered_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [CandidatePostOut.model_validate(r) for r in rows]


@app.get("/api/tracked-posts", response_model=list[TrackedPostOut])
async def list_tracked(
    session: AsyncSession = Depends(get_session),
) -> list[TrackedPostOut]:
    stmt = select(TrackedPost).order_by(TrackedPost.promoted_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [TrackedPostOut.model_validate(r) for r in rows]


@app.get(
    "/api/tracked-posts/{tracked_id}/snapshots", response_model=list[SnapshotOut]
)
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
