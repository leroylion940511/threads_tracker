"""共用的 Anthropic 客戶端工廠 + 提示快取支援."""

from __future__ import annotations

from anthropic import AsyncAnthropic

from ..config import get_settings


def build_async_client() -> AsyncAnthropic:
    s = get_settings()
    if not s.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    return AsyncAnthropic(api_key=s.anthropic_api_key)
