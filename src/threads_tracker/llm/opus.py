"""Anthropic Opus 4.7 — 事件演進敘事."""

from __future__ import annotations

from ..config import get_settings
from ..logging import get_logger
from .base import (
    SYSTEM_PROMPT,
    EvolutionSummary,
    build_evolution_prompt,
    parse_evolution_payload,
)
from .client import build_async_client

logger = get_logger(__name__)


class OpusSummarizer:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = build_async_client()
        self._model = self._settings.anthropic_opus_model

    async def summarize_evolution(
        self,
        original_post: str,
        followups: list[str],
        top_replies: list[str],
    ) -> EvolutionSummary:
        prompt = build_evolution_prompt(original_post, followups, top_replies)
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text")
        return parse_evolution_payload(text)


# 保留舊匯入路徑（services/summarization.py 已改用 llm.base）
__all__ = ["EvolutionSummary", "OpusSummarizer"]
