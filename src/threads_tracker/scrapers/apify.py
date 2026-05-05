"""Apify Threads Scraper 客戶端 — 第一週可行性驗證階段使用.

API 細節以 actor 文件為準（https://apify.com/apify/threads-scraper），
此處先封裝呼叫流程，並用 Pydantic-friendly 的 PostPayload 統一輸出格式。
若第一週驗證後發現欄位對不上，再回頭微調 _normalize_*。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx

from ..config import get_settings
from ..logging import get_logger
from .base import PostFetcher, PostPayload, ReplyPayload, parse_threads_url

logger = get_logger(__name__)

APIFY_BASE = "https://api.apify.com/v2"


class ApifyError(RuntimeError):
    pass


class ApifyThreadsScraper(PostFetcher):
    def __init__(
        self,
        token: str | None = None,
        actor_id: str | None = None,
        client: httpx.AsyncClient | None = None,
        poll_interval: float = 2.0,
        timeout: float = 120.0,
    ) -> None:
        s = get_settings()
        self._token = token or s.apify_token
        self._actor_id = (actor_id or s.apify_actor_id).replace("/", "~")
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._poll_interval = poll_interval
        self._timeout = timeout

        if not self._token:
            logger.warning("apify.missing_token")

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- PostFetcher API ---------------------------------------------------

    async def fetch_post(self, post_url: str) -> PostPayload:
        parse_threads_url(post_url)  # validate early
        items = await self._run_actor({"postUrls": [post_url], "fetchReplies": True})
        if not items:
            raise ApifyError(f"Apify returned no items for {post_url}")
        return self._normalize_post(items[0])

    async def fetch_author_timeline(
        self, username: str, since: datetime | None = None
    ) -> list[PostPayload]:
        items = await self._run_actor(
            {"usernames": [username], "resultsLimit": 50, "fetchReplies": False}
        )
        posts = [self._normalize_post(it) for it in items]
        if since is not None:
            posts = [p for p in posts if p.posted_at and p.posted_at > since]
        return posts

    async def search_related(self, query: str, limit: int = 20) -> list[PostPayload]:
        items = await self._run_actor(
            {"searchTerms": [query], "resultsLimit": limit, "fetchReplies": False}
        )
        return [self._normalize_post(it) for it in items]

    # --- Apify HTTP plumbing ----------------------------------------------

    async def _run_actor(self, run_input: dict[str, Any]) -> list[dict[str, Any]]:
        if not self._token:
            raise ApifyError("APIFY_TOKEN is not configured")

        url = f"{APIFY_BASE}/acts/{self._actor_id}/runs"
        params = {"token": self._token}

        logger.info("apify.run_start", actor=self._actor_id, input=run_input)
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
            if status in {"SUCCEEDED"}:
                return
            if status in {"FAILED", "ABORTED", "TIMED-OUT"}:
                raise ApifyError(f"Apify run {run_id} ended with status={status}")
            if asyncio.get_event_loop().time() > deadline:
                raise ApifyError(f"Apify run {run_id} did not complete in {self._timeout}s")
            await asyncio.sleep(self._poll_interval)

    # --- Normalization -----------------------------------------------------

    @staticmethod
    def _normalize_post(item: dict[str, Any]) -> PostPayload:
        """Map an Apify item into our PostPayload.

        Field names below follow the actor's documented schema. They may need
        adjusting once we run a real fetch; centralising the mapping here
        keeps that change cheap.
        """
        replies = [
            ApifyThreadsScraper._normalize_reply(r) for r in item.get("replies") or []
        ]

        posted_at_raw = item.get("publishedOn") or item.get("publishedAt")
        posted_at = _parse_dt(posted_at_raw)

        return PostPayload(
            threads_post_id=str(item.get("id") or item.get("code") or ""),
            author_username=str(item.get("user", {}).get("username") or item.get("username") or ""),
            post_url=str(item.get("url") or ""),
            content=str(item.get("text") or item.get("caption") or ""),
            posted_at=posted_at,
            like_count=int(item.get("likeCount") or 0),
            reply_count=int(item.get("replyCount") or 0),
            repost_count=int(item.get("repostCount") or 0),
            replies=replies,
            raw=item,
        )

    @staticmethod
    def _normalize_reply(item: dict[str, Any]) -> ReplyPayload:
        return ReplyPayload(
            threads_post_id=str(item.get("id") or ""),
            author_username=str(
                item.get("user", {}).get("username") or item.get("username") or ""
            ),
            content=str(item.get("text") or ""),
            like_count=int(item.get("likeCount") or 0),
            posted_at=_parse_dt(item.get("publishedOn") or item.get("publishedAt")),
            is_author_reply=bool(item.get("isAuthorReply", False)),
        )


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
