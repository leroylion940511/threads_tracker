"""watcher.data/search-threads-by-keywords client (v3 探索層用).

與 v1 ApifyThreadsScraper 的差異：
- 單一模式：keywords 陣列搜尋；不支援單一 url / author timeline
- 一次 actor run 可餵多個關鍵字，自動跨 keyword 去重
- Output schema 是平的 snake_case（author / created_at / like_count），
  與 v1 actor 的 user{}.username / publishedOn / likeCount 不同
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx

from ..config import get_settings
from ..logging import get_logger
from .base import PostPayload

logger = get_logger(__name__)

APIFY_BASE = "https://api.apify.com/v2"


class ApifyError(RuntimeError):
    pass


class WatcherDataSearchScraper:
    """單一職責：餵 keywords 陣列、回 list[PostPayload]。"""

    def __init__(
        self,
        token: str | None = None,
        actor_id: str | None = None,
        client: httpx.AsyncClient | None = None,
        poll_interval: float = 2.0,
        timeout: float = 180.0,
    ) -> None:
        s = get_settings()
        self._token = token or s.apify_token
        self._actor_id = (actor_id or s.apify_search_actor_id).replace("/", "~")
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._poll_interval = poll_interval
        self._timeout = timeout

        if not self._token:
            logger.warning("watcher.missing_token")

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search_keywords(
        self,
        keywords: list[str],
        max_per_keyword: int = 20,
        sort_by_recent: bool = True,
    ) -> list[PostPayload]:
        if not keywords:
            return []
        run_input: dict[str, Any] = {
            "keywords": keywords,
            "maxItemsPerKeyword": max_per_keyword,
            "sortByRecent": sort_by_recent,
            "outputFormat": "json",
        }
        items = await self._run_actor(run_input)
        return [self._normalize_post(it) for it in items]

    async def search_keywords_raw(
        self,
        keywords: list[str],
        max_per_keyword: int = 20,
        sort_by_recent: bool = True,
    ) -> list[dict[str, Any]]:
        """跑一次然後回 raw items。M1 驗證欄位名稱用。"""
        run_input: dict[str, Any] = {
            "keywords": keywords,
            "maxItemsPerKeyword": max_per_keyword,
            "sortByRecent": sort_by_recent,
            "outputFormat": "json",
        }
        return await self._run_actor(run_input)

    async def _run_actor(self, run_input: dict[str, Any]) -> list[dict[str, Any]]:
        if not self._token:
            raise ApifyError("APIFY_TOKEN is not configured")

        url = f"{APIFY_BASE}/acts/{self._actor_id}/runs"
        params = {"token": self._token}

        logger.info("watcher.run_start", actor=self._actor_id, kw_count=len(run_input.get("keywords") or []))
        resp = await self._client.post(url, params=params, json=run_input)
        resp.raise_for_status()
        run = resp.json()["data"]
        run_id = run["id"]
        dataset_id = run["defaultDatasetId"]

        await self._wait_for_run(run_id)

        items_url = f"{APIFY_BASE}/datasets/{dataset_id}/items"
        items_resp = await self._client.get(items_url, params={"token": self._token})
        items_resp.raise_for_status()
        return items_resp.json()

    async def _wait_for_run(self, run_id: str) -> None:
        deadline = asyncio.get_event_loop().time() + self._timeout
        url = f"{APIFY_BASE}/actor-runs/{run_id}"
        params = {"token": self._token}

        while True:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            status = resp.json()["data"]["status"]
            if status == "SUCCEEDED":
                return
            if status in {"FAILED", "ABORTED", "TIMED-OUT"}:
                raise ApifyError(f"Apify run {run_id} ended with status={status}")
            if asyncio.get_event_loop().time() > deadline:
                raise ApifyError(f"Apify run {run_id} did not complete in {self._timeout}s")
            await asyncio.sleep(self._poll_interval)

    @staticmethod
    def _normalize_post(item: dict[str, Any]) -> PostPayload:
        return PostPayload(
            threads_post_id=str(item.get("id") or ""),
            author_username=str(item.get("author") or ""),
            post_url=str(item.get("url") or ""),
            content=str(item.get("text") or ""),
            posted_at=_parse_dt(item.get("created_at")),
            like_count=int(item.get("like_count") or 0),
            reply_count=int(item.get("reply_count") or 0),
            repost_count=int(item.get("repost_count") or 0),
            replies=[],
            raw=item,
        )


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return datetime.fromtimestamp(float(s))
    except (ValueError, OSError):
        return None
