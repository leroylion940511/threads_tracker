"""LLM provider 共用型別與提示."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(slots=True)
class EvolutionSummary:
    narrative: str
    milestones: list[str]
    suggests_push: bool


SYSTEM_PROMPT = (
    "你是一個事件追蹤助理，善於把零散的貼文與留言整理成"
    "『這件事現在發展到哪了』的敘事。輸出簡潔、不重複、不臆測。"
    "全部輸出 JSON。"
)


def build_evolution_prompt(
    original_post: str, followups: list[str], top_replies: list[str]
) -> str:
    followup_block = "\n".join(f"- {f}" for f in followups) or "（暫無）"
    reply_block = "\n".join(f"- {r}" for r in top_replies) or "（暫無）"
    return (
        '請輸出 JSON：{"narrative": <300 字內敘事>,'
        ' "milestones": [<關鍵節點...>],'
        ' "suggests_push": <是否值得立刻推播>}\n\n'
        f"【原貼文】\n{original_post}\n\n"
        f"【作者後續貼文】\n{followup_block}\n\n"
        f"【熱門留言】\n{reply_block}\n"
    )


def parse_evolution_payload(text: str) -> EvolutionSummary:
    """把 LLM 回傳的 JSON 字串解成 EvolutionSummary（容忍包在 markdown code fence 裡）."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        # 去掉開頭可能的 "json\n"
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].lstrip("\n")
    data = json.loads(cleaned)
    return EvolutionSummary(
        narrative=str(data.get("narrative", "")),
        milestones=[str(m) for m in data.get("milestones", [])],
        suggests_push=bool(data.get("suggests_push", False)),
    )


__all__ = [
    "SYSTEM_PROMPT",
    "EvolutionSummary",
    "build_evolution_prompt",
    "parse_evolution_payload",
]
