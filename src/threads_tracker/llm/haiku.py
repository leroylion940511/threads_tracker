"""Haiku 4.5：高頻、低成本的留言情緒分類與相關性判定."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from ..config import get_settings
from ..logging import get_logger
from .client import build_async_client

logger = get_logger(__name__)

Sentiment = Literal["support", "oppose", "neutral", "question"]


@dataclass(slots=True)
class SentimentResult:
    label: Sentiment
    confidence: float


@dataclass(slots=True)
class RelevanceResult:
    score: float  # 0..1
    reason: str


class HaikuClassifier:
    """非同步 Haiku 客戶端，回傳結構化結果."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = build_async_client()
        self._model = self._settings.anthropic_haiku_model

    async def classify_sentiment(self, comment: str) -> SentimentResult:
        prompt = (
            "以下是一則 Threads 留言，請判斷它的立場。"
            "只能輸出 JSON：{\"label\": <support|oppose|neutral|question>, \"confidence\": <0..1>}\n\n"
            f"留言：{comment}"
        )
        data = await self._json_call(prompt, max_tokens=128)
        return SentimentResult(label=data["label"], confidence=float(data["confidence"]))

    async def judge_relevance(self, original: str, candidate: str) -> RelevanceResult:
        prompt = (
            "判斷『候選貼文』是否在延續『原貼文』的事件。輸出 JSON：\n"
            "{\"score\": <0..1>, \"reason\": <一句話>}\n\n"
            f"原貼文：\n{original}\n\n候選貼文：\n{candidate}"
        )
        data = await self._json_call(prompt, max_tokens=192)
        return RelevanceResult(score=float(data["score"]), reason=data["reason"])

    async def _json_call(self, prompt: str, *, max_tokens: int) -> dict:
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("haiku.invalid_json", text=text[:200])
            raise
