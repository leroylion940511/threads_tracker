"""Application settings loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"

    database_url: str = "sqlite+aiosqlite:///./data/threads_tracker.sqlite3"

    apify_token: str | None = None
    apify_actor_id: str = "apify/threads-scraper"

    # LLM provider 切換：anthropic（預設）/ minimax；驗證在 llm.factory
    llm_provider: str = "anthropic"

    anthropic_api_key: str | None = None
    anthropic_haiku_model: str = "claude-haiku-4-5-20251001"
    anthropic_opus_model: str = "claude-opus-4-7"

    # MiniMax — OpenAI 相容 chat completion endpoint
    # 國際站可改成 https://api.minimaxi.chat/v1
    minimax_api_key: str | None = None
    minimax_base_url: str = "https://api.minimax.chat/v1"
    minimax_chat_path: str = "/text/chatcompletion_v2"
    minimax_model: str = "abab6.5s-chat"

    telegram_bot_token: str | None = None
    telegram_webhook_url: str | None = None
    telegram_webhook_secret: str | None = None

    poll_hot_minutes: int = Field(15, ge=1)
    poll_warm_minutes: int = Field(60, ge=1)
    poll_cold_minutes: int = Field(360, ge=1)
    archive_after_days: int = Field(30, ge=1)

    hot_like_threshold: int = 1000
    hot_reply_threshold: int = 200
    hot_growth_ratio: float = 0.5

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
