"""抓取器抽象介面與共用資料結構."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ReplyPayload:
    threads_post_id: str
    author_username: str
    content: str
    like_count: int = 0
    posted_at: datetime | None = None
    is_author_reply: bool = False


@dataclass(slots=True)
class PostPayload:
    """抓取到的單則貼文（原貼文或續發貼文）."""

    threads_post_id: str
    author_username: str
    post_url: str
    content: str
    posted_at: datetime | None = None
    like_count: int = 0
    reply_count: int = 0
    repost_count: int = 0
    replies: list[ReplyPayload] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


_THREADS_URL_RE = re.compile(
    r"^https?://(?:www\.)?threads\.(?:net|com)/@(?P<user>[\w.]+)/post/(?P<code>[\w-]+)/?",
    re.IGNORECASE,
)


def parse_threads_url(url: str) -> tuple[str, str]:
    """Return (username, post_code) for a Threads post URL.

    Raises ValueError if the URL does not look like a Threads post.
    """
    m = _THREADS_URL_RE.match(url.strip())
    if not m:
        raise ValueError(f"Not a recognised Threads post URL: {url!r}")
    return m.group("user"), m.group("code")


class PostFetcher(ABC):
    """所有抓取器（Apify、自寫 GraphQL、測試 fake）共用的介面."""

    @abstractmethod
    async def fetch_post(self, post_url: str) -> PostPayload:
        """抓取單一貼文的當前狀態（含留言）."""

    @abstractmethod
    async def fetch_author_timeline(
        self, username: str, since: datetime | None = None
    ) -> list[PostPayload]:
        """抓取作者 timeline 中 since 之後的新貼文."""

    @abstractmethod
    async def search_related(self, query: str, limit: int = 20) -> list[PostPayload]:
        """以關鍵字或原貼文連結查找相關討論."""
