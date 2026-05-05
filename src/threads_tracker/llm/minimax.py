"""MiniMax — OpenAI 相容的 chat completion 摘要實作.

設計上盡量「拿其它 OpenAI 相容 provider 也能用」：
- 端點（base_url + chat_path）、API key、模型名都從 settings 帶
- request 與 response 解析走 OpenAI v1 chat completions 規格
- 失敗時保留原 response 在 exception 訊息中，方便 debug 不同 provider 的格式差異
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import get_settings
from ..logging import get_logger
from .base import (
    SYSTEM_PROMPT,
    EvolutionSummary,
    build_evolution_prompt,
    parse_evolution_payload,
)

logger = get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.3


class MiniMaxSummarizer:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        chat_path: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        s = get_settings()
        self._api_key = api_key or s.minimax_api_key
        if not self._api_key:
            raise RuntimeError("MINIMAX_API_KEY is not configured")
        self._model = model or s.minimax_model
        self._base_url = (base_url or s.minimax_base_url).rstrip("/")
        self._chat_path = chat_path or s.minimax_chat_path
        self._timeout = timeout
        self._client = client  # injectable for tests

    async def summarize_evolution(
        self,
        original_post: str,
        followups: list[str],
        top_replies: list[str],
    ) -> EvolutionSummary:
        prompt = build_evolution_prompt(original_post, followups, top_replies)
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": DEFAULT_MAX_TOKENS,
            "temperature": DEFAULT_TEMPERATURE,
            "response_format": {"type": "json_object"},
        }
        url = f"{self._base_url}{self._chat_path}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        data = await self._post(url, payload, headers)
        text = _extract_message_content(data)
        try:
            return parse_evolution_payload(text)
        except Exception as exc:  # noqa: BLE001
            logger.error("minimax.parse_failed", text=text[:500])
            raise RuntimeError(f"failed to parse MiniMax response: {exc}") from exc

    async def _post(
        self, url: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        if self._client is not None:
            resp = await self._client.post(url, json=payload, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            logger.error(
                "minimax.http_error",
                status=resp.status_code,
                body=resp.text[:500],
            )
        resp.raise_for_status()
        return resp.json()


def _extract_message_content(data: dict[str, Any]) -> str:
    """OpenAI 相容回應：``choices[0].message.content``."""
    choices = data.get("choices") or []
    if not choices:
        # MiniMax 失敗時會回 base_resp.status_msg，把它帶出來方便除錯
        base = data.get("base_resp") or {}
        msg = base.get("status_msg") or "no choices in response"
        raise RuntimeError(f"MiniMax error: {msg} | raw: {data}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        raise RuntimeError(f"MiniMax returned empty content: {data}")
    return content


__all__ = ["MiniMaxSummarizer"]
