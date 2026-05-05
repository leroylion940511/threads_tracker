"""Threads 抓取層 — 對外提供統一的 PostFetcher 介面."""

from .base import (
    PostFetcher,
    PostPayload,
    ReplyPayload,
    parse_threads_url,
)

__all__ = [
    "PostFetcher",
    "PostPayload",
    "ReplyPayload",
    "parse_threads_url",
]
