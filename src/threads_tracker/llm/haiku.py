"""Haiku 4.5：高頻、低成本的判斷層.

用途：
    - score_candidate    候選貼文五軸評分（評分層 §4.2 第二段）
    - classify_sentiment 留言情緒分類（追蹤層用）
    - judge_relevance    候選貼文是否延續原事件（追蹤層用）
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from ..config import get_settings
from ..logging import get_logger
from .client import build_async_client

logger = get_logger(__name__)

Sentiment = Literal["support", "oppose", "neutral", "question"]
Verdict = Literal["track", "skip"]

# Anthropic Haiku 4.5 公定定價（USD / MTok）— 用來估 cost_usd 寫入 audit log
HAIKU_INPUT_PRICE_PER_MTOK: float = 1.00
HAIKU_OUTPUT_PRICE_PER_MTOK: float = 5.00

# 容忍 LLM 回傳 ```json ... ``` 包覆
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass(slots=True)
class SentimentResult:
    label: Sentiment
    confidence: float


@dataclass(slots=True)
class RelevanceResult:
    score: float  # 0..1
    reason: str


@dataclass(slots=True)
class CandidateScore:
    """候選貼文五軸評分 + verdict + reason（評分層 §4.2 第二段輸出）.

    五軸全部 0..1，意義：
        story_potential  — 貼文是否暗示「後續會發展」（追蹤價值的核心訊號）
        emotional_pull   — 是否引發情緒共鳴、能催出留言
        grassroots       — 看起來像「真實素人」而非 KOL / 帳號經營者
        novelty          — 題材新鮮度、與近期常見話題的差異
        authenticity     — 真實感（非業配 / 非機器人 / 非搬運）
    """

    story_potential: float
    emotional_pull: float
    grassroots: float
    novelty: float
    authenticity: float
    verdict: Verdict
    reason: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw_response: str | None = None

    def overall(self) -> float:
        """五軸平均，給 scoring_records.haiku.score 一個方便的代表值."""
        return round(
            (
                self.story_potential
                + self.emotional_pull
                + self.grassroots
                + self.novelty
                + self.authenticity
            )
            / 5,
            4,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "story_potential": self.story_potential,
            "emotional_pull": self.emotional_pull,
            "grassroots": self.grassroots,
            "novelty": self.novelty,
            "authenticity": self.authenticity,
            "verdict": self.verdict,
            "reason": self.reason,
        }


_SCORING_SYSTEM_PROMPT = (
    "你是 Threads 素人爆文偵測器。給定一則貼文，從 5 個面向打分（0–1，"
    "0.5 為中性），並判斷是否值得列入追蹤清單。\n"
    "目標：找『真實素人、暗示有後續、能引共鳴』的繁中貼文；"
    "排除『業配、搬運、爭流量八卦、純情緒宣洩無敘事』。\n"
    "只回 JSON，禁用解釋文字、禁用 markdown fence。"
)

_SCORING_USER_TEMPLATE = (
    "貼文作者：@{author}（粉絲 {followers}）\n"
    "貼文內文：\n{content}\n\n"
    "輸出 JSON schema：\n"
    "{{\n"
    '  "story_potential": <0..1>,   // 暗示「後續會發展」的程度\n'
    '  "emotional_pull": <0..1>,    // 情緒共鳴 / 留言驅動力\n'
    '  "grassroots": <0..1>,        // 素人感（vs KOL / 媒體 / 行銷號）\n'
    '  "novelty": <0..1>,           // 題材新鮮度\n'
    '  "authenticity": <0..1>,      // 真實感（非業配 / 非搬運）\n'
    '  "verdict": "track" | "skip",\n'
    '  "reason": "<不超過 30 字的中文判斷依據>"\n'
    "}}"
)


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
        data, _ = await self._json_call(prompt, max_tokens=128)
        return SentimentResult(
            label=data["label"], confidence=float(data["confidence"])
        )

    async def judge_relevance(self, original: str, candidate: str) -> RelevanceResult:
        prompt = (
            "判斷『候選貼文』是否在延續『原貼文』的事件。輸出 JSON：\n"
            "{\"score\": <0..1>, \"reason\": <一句話>}\n\n"
            f"原貼文：\n{original}\n\n候選貼文：\n{candidate}"
        )
        data, _ = await self._json_call(prompt, max_tokens=192)
        return RelevanceResult(score=float(data["score"]), reason=data["reason"])

    async def score_candidate(
        self,
        *,
        content: str,
        author_username: str | None = None,
        follower_count: int | None = None,
    ) -> CandidateScore:
        user_prompt = _SCORING_USER_TEMPLATE.format(
            author=author_username or "unknown",
            followers=follower_count if follower_count is not None else "未知",
            content=content,
        )
        data, meta = await self._json_call(
            user_prompt,
            max_tokens=320,
            system=_SCORING_SYSTEM_PROMPT,
        )
        return _parse_candidate_score(data, model=self._model, meta=meta)

    async def _json_call(
        self,
        prompt: str,
        *,
        max_tokens: int,
        system: str | None = None,
    ) -> tuple[dict, dict]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system is not None:
            kwargs["system"] = system
        msg = await self._client.messages.create(**kwargs)
        text = "".join(b.text for b in msg.content if b.type == "text")
        usage = getattr(msg, "usage", None)
        meta = {
            "raw": text,
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        }
        try:
            return _extract_json_object(text), meta
        except (json.JSONDecodeError, ValueError):
            logger.warning("haiku.invalid_json", text=text[:200])
            raise


def _extract_json_object(text: str) -> dict:
    """容忍 ```json fence``` 包覆 / 前後雜訊空白."""
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty response")
    fenced = _FENCE_RE.search(stripped)
    if fenced:
        return json.loads(fenced.group(1))
    return json.loads(stripped)


def _parse_candidate_score(
    data: dict, *, model: str, meta: dict
) -> CandidateScore:
    def _clamp(x: Any) -> float:
        try:
            v = float(x)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, v))

    verdict = data.get("verdict", "skip")
    if verdict not in ("track", "skip"):
        verdict = "skip"
    input_tokens = int(meta.get("input_tokens", 0))
    output_tokens = int(meta.get("output_tokens", 0))
    cost = (
        input_tokens * HAIKU_INPUT_PRICE_PER_MTOK
        + output_tokens * HAIKU_OUTPUT_PRICE_PER_MTOK
    ) / 1_000_000
    return CandidateScore(
        story_potential=_clamp(data.get("story_potential")),
        emotional_pull=_clamp(data.get("emotional_pull")),
        grassroots=_clamp(data.get("grassroots")),
        novelty=_clamp(data.get("novelty")),
        authenticity=_clamp(data.get("authenticity")),
        verdict=verdict,  # type: ignore[arg-type]
        reason=str(data.get("reason", "")),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 6),
        raw_response=meta.get("raw"),
    )
