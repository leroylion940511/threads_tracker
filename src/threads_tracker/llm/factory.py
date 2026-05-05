"""根據設定挑選 EvolutionSummarizer 實作（Anthropic / MiniMax / 其他）."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..config import get_settings

if TYPE_CHECKING:
    from ..services.summarization import EvolutionSummarizer


def get_summarizer() -> "EvolutionSummarizer":
    s = get_settings()
    provider = (s.llm_provider or "anthropic").lower()
    if provider == "anthropic":
        from .opus import OpusSummarizer

        return OpusSummarizer()
    if provider == "minimax":
        from .minimax import MiniMaxSummarizer

        return MiniMaxSummarizer()
    raise ValueError(
        f"Unknown LLM_PROVIDER: {provider!r}（支援：anthropic, minimax）"
    )


__all__ = ["get_summarizer"]
