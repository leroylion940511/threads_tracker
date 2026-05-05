"""Pick the right PostFetcher based on settings."""

from __future__ import annotations

from ..config import get_settings
from .apify import ApifyThreadsScraper
from .base import PostFetcher
from .fake import FakeThreadsScraper


def get_fetcher() -> PostFetcher:
    """Return Apify if configured; fall back to the fake scraper for dev."""
    s = get_settings()
    if s.apify_token:
        return ApifyThreadsScraper()
    return FakeThreadsScraper()
