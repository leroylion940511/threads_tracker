"""把 KEYWORD_SEEDS 寫進資料庫的 keyword_seeds 表（冪等）.

跑法：
    uv run python -m threads_tracker.seeds.loader

也可以從程式碼呼叫 ``load_seeds(session)`` 在 setup script / 測試裡用。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import session_scope
from ..logging import get_logger
from ..models import KeywordSeed
from .keyword_seeds import KEYWORD_SEEDS

logger = get_logger(__name__)


@dataclass(slots=True)
class LoadResult:
    inserted: int
    existing: int


async def load_seeds(session: AsyncSession) -> LoadResult:
    """把 KEYWORD_SEEDS 全部 upsert 進 DB；同 keyword 已存在就略過."""
    existing_rows = (
        await session.execute(select(KeywordSeed.keyword))
    ).scalars().all()
    existing = set(existing_rows)

    inserted = 0
    for seed in KEYWORD_SEEDS:
        if seed.keyword in existing:
            continue
        session.add(
            KeywordSeed(
                keyword=seed.keyword,
                category=seed.category,
                note=seed.note or None,
                enabled=True,
            )
        )
        inserted += 1

    await session.commit()
    logger.info(
        "seeds.loaded",
        total_in_module=len(KEYWORD_SEEDS),
        inserted=inserted,
        already_existing=len(existing),
    )
    return LoadResult(inserted=inserted, existing=len(existing))


async def _main() -> None:
    async with session_scope() as session:
        result = await load_seeds(session)
    print(f"seed loader: inserted={result.inserted}, existing={result.existing}")


if __name__ == "__main__":
    asyncio.run(_main())
