"""In-memory fake scraper for local dev / tests.

Lets the rest of the system (DB, scheduler, bot) run end-to-end without an
Apify token. Replace with `ApifyThreadsScraper` once Week 1 verification passes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .base import PostFetcher, PostPayload, ReplyPayload, parse_threads_url


class FakeThreadsScraper(PostFetcher):
    """Returns deterministic dummy data with monotonically growing counts."""

    def __init__(self) -> None:
        self._calls: dict[str, int] = {}

    async def fetch_post(self, post_url: str) -> PostPayload:
        user, code = parse_threads_url(post_url)
        n = self._calls.get(code, 0) + 1
        self._calls[code] = n

        return PostPayload(
            threads_post_id=code,
            author_username=user,
            post_url=post_url,
            content=f"[fake] {user} 的爆紅貼文（第 {n} 次抓取）",
            posted_at=datetime.now(timezone.utc),
            like_count=100 * n,
            reply_count=20 * n,
            repost_count=5 * n,
            replies=[
                ReplyPayload(
                    threads_post_id=f"{code}_r{i}",
                    author_username=f"user{i}",
                    content=f"留言 {i} (round {n})",
                    like_count=i,
                    posted_at=datetime.now(timezone.utc),
                    is_author_reply=(i == 1 and n > 2),
                )
                for i in range(1, 4)
            ],
        )

    async def fetch_author_timeline(
        self, username: str, since: datetime | None = None
    ) -> list[PostPayload]:
        return []

    async def search_related(self, query: str, limit: int = 20) -> list[PostPayload]:
        return []
