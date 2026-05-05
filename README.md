# threads_tracker

Threads 熱點貼文後續追蹤系統 — 自動偵測爆紅貼文，持續追蹤後續演進，
並透過 Telegram 推播 LLM 摘要。完整企劃見 [`threads_tracker_proposal.md`](./threads_tracker_proposal.md)。

目前可 demo：fake scraper + Telegram bot 串通，`/track /list /poll /digest /timeline`
都能跑；LLM 摘要支援 **Anthropic Claude** 與 **MiniMax** 兩個 provider，環境變數切換。
爆紅推播、自動偵測、Apify 真實抓取尚未啟用。

## 專案結構

```
src/threads_tracker/
├── api.py            # FastAPI app + /api/tracked-posts
├── bot/              # Telegram bot (python-telegram-bot)
├── cli.py            # `threads-tracker api|bot`
├── config.py         # pydantic-settings (.env)
├── db.py             # async SQLAlchemy engine / session
├── llm/              # Haiku 分類 + Opus 摘要（需 ANTHROPIC_API_KEY）
├── logging.py        # structlog
├── models.py         # ORM (對應企劃書 §五 資料表)
├── scheduler.py      # APScheduler 分級輪詢
├── schemas.py        # Pydantic API schemas
├── scrapers/         # PostFetcher 介面 + Apify + Fake
└── services/
    ├── detection.py  # 爆紅偵測 (§4.1)
    ├── polling.py    # 分級輪詢 (§4.4)
    └── tracking.py   # 主要 ingestion 流程
alembic/              # 資料庫 migration
tests/                # smoke tests
```

## 開始開發

```bash
# 1. 安裝依賴
uv sync

# 2. 建立 .env
cp .env.example .env
# 預設使用 SQLite，可立即跑；要切到 Postgres 改 DATABASE_URL

# 3. 建表
mkdir -p data
uv run alembic upgrade head

# 4. 跑測試
uv run pytest
```

## Demo 流程（不需要 Apify token）

最少要填的 `.env`：

```bash
TELEGRAM_BOT_TOKEN=...                # 從 @BotFather 拿
LLM_PROVIDER=minimax                  # 或 anthropic
MINIMAX_API_KEY=...                   # 對應 provider 的 key
```

啟動 bot（fake scraper 會自動接手，無需 Apify）：

```bash
uv run threads-tracker bot
```

在 Telegram 對 bot：

```
/track https://www.threads.net/@demo/post/HELLO
/list
/poll 1                # 重抓一次（demo 用，產生第二筆 snapshot）
/poll 1                # 再抓一次，互動數會持續成長
/digest 1              # 呼叫 LLM 產生敘事 + 關鍵節點，24h 內 cache
/timeline 1            # 純資料時間軸（不打 LLM）
```

要兩個 process 同時跑（API + scheduler 一邊、bot 一邊）：

```bash
uv run threads-tracker api --reload   # http://127.0.0.1:8000/docs
uv run threads-tracker bot
```

## 切換 LLM provider

`.env` 設 `LLM_PROVIDER=anthropic` 或 `minimax`：

| Provider  | 必填                                         | 備註                                            |
|-----------|---------------------------------------------|-------------------------------------------------|
| anthropic | `ANTHROPIC_API_KEY`                         | 走 Anthropic SDK，預設模型 `claude-opus-4-7`     |
| minimax   | `MINIMAX_API_KEY`                           | OpenAI 相容 chat completion；可改 base_url / path |

要接其它 OpenAI 相容服務（DeepSeek、Qwen、自架 vLLM…），暫時用 MiniMax 那條路、改 `MINIMAX_BASE_URL` + `MINIMAX_CHAT_PATH` + `MINIMAX_MODEL` 即可（之後會把它改名成更通用的 `openai_compat`）。

## 抓取器策略

`scrapers.factory.get_fetcher()` 根據環境變數選用：

- 有設 `APIFY_TOKEN` → `ApifyThreadsScraper`
- 沒設 → `FakeThreadsScraper`（產生遞增的假資料，方便沒有 API key 也能跑通流程）

第一週可行性驗證：
1. 註冊 Apify、拿 token、把 `APIFY_TOKEN` 填進 `.env`
2. 跑 `uv run threads-tracker bot`，在 Telegram 對 bot 送 `/track <連結>`
3. 觀察 logs / DB 是否拿到正確的貼文與留言。
4. 若欄位對不上，調整 `scrapers/apify.py` 的 `_normalize_post` / `_normalize_reply`。

## 資料庫 migration

```bash
# 改了 ORM 後重新產生
uv run alembic revision --autogenerate -m "<message>"
uv run alembic upgrade head
```

`alembic/script.py.mako` 已自動 import `threads_tracker.models`，新 migration
裡的自訂 `JSONField` 等型別可直接使用。

## 接下來（對應企劃書週次）

- **第四週**：✅ `services/summarization.py` + `/digest` `/timeline` 已串通。
- **第五週**：實作自動偵測（種子來源 → `services/detection.py`）、`/explore` 候選清單，
  以及每日 21:00 彙整推播（補完 `scheduler._daily_digest_job`）。
- **第六週**：端到端整合測試、效能調校、撰寫專題報告。
