"""LLM factory + MiniMax client 行為測試（不打外部 API）."""

from __future__ import annotations

import json

import httpx
import pytest

from threads_tracker.config import get_settings
from threads_tracker.llm.factory import get_summarizer
from threads_tracker.llm.minimax import MiniMaxSummarizer
from threads_tracker.llm.opus import OpusSummarizer


@pytest.fixture(autouse=True)
def _reset_settings_cache(monkeypatch):
    """`get_settings` 是 lru_cache 過的；每個測試用 monkeypatch 後清掉重新讀."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_factory_picks_minimax(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.setenv("MINIMAX_API_KEY", "fake-key")
    summarizer = get_summarizer()
    assert isinstance(summarizer, MiniMaxSummarizer)


def test_factory_picks_anthropic(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    summarizer = get_summarizer()
    assert isinstance(summarizer, OpusSummarizer)


def test_factory_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bogus")
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        get_summarizer()


def test_minimax_missing_key_raises(monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MINIMAX_API_KEY"):
        MiniMaxSummarizer()


async def test_minimax_summarize_evolution_uses_openai_shape(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        body = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "narrative": "事件持續發酵",
                                "milestones": ["A", "B"],
                                "suggests_push": True,
                            }
                        ),
                    }
                }
            ]
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        s = MiniMaxSummarizer(
            api_key="test-key",
            model="abab6.5s-chat",
            base_url="https://example.test/v1",
            chat_path="/text/chatcompletion_v2",
            client=client,
        )
        result = await s.summarize_evolution(
            original_post="原文",
            followups=["作者後續 1"],
            top_replies=["@a: 留言一"],
        )

    assert result.narrative == "事件持續發酵"
    assert result.milestones == ["A", "B"]
    assert result.suggests_push is True

    assert captured["url"] == "https://example.test/v1/text/chatcompletion_v2"
    assert captured["headers"]["authorization"] == "Bearer test-key"
    body = captured["body"]
    assert body["model"] == "abab6.5s-chat"
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"
    assert "原文" in body["messages"][1]["content"]


async def test_minimax_surfaces_provider_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [],
                "base_resp": {"status_code": 1004, "status_msg": "rate limited"},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        s = MiniMaxSummarizer(
            api_key="test-key",
            base_url="https://example.test/v1",
            client=client,
        )
        with pytest.raises(RuntimeError, match="rate limited"):
            await s.summarize_evolution("原文", [], [])


async def test_minimax_handles_markdown_fenced_json():
    def handler(request: httpx.Request) -> httpx.Response:
        fenced = (
            "```json\n"
            + json.dumps(
                {"narrative": "x", "milestones": [], "suggests_push": False}
            )
            + "\n```"
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": fenced}}]},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        s = MiniMaxSummarizer(
            api_key="test-key",
            base_url="https://example.test/v1",
            client=client,
        )
        result = await s.summarize_evolution("原文", [], [])
    assert result.narrative == "x"
