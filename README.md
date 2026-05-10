# threads_tracker

Threads 熱點貼文後續追蹤系統。v3 架構：關鍵字探索 → 多階段評分 →
每日 Top 5 推送 → 使用者 ❤️ 升格追蹤 → 後續事件偵測 → Opus 問答。

完整企劃見 [`threads_tracker_proposal_v3.md`](./threads_tracker_proposal_v3.md)、
任務級進度見 [`SCHEDULE.md`](./SCHEDULE.md)、跨 session 狀態真相見 [`PROGRESS.md`](./PROGRESS.md)。

## 進度

| 里程碑 | 狀態 |
|--------|------|
| M1 — Apify 可行性驗證（actor 選定 `watcher.data/search-threads-by-keywords`） | ✅ |
| M2 — v3 schema + 探索層 + scheduler | ✅ |
| M3 — 評分層 | ⏳ |
| M4–M8 — 推送 / 追蹤 / 問答 / 評估 / 報告 | ❌ |

## 專案結構

```
src/threads_tracker/
├── api.py            # FastAPI: /health + /api/candidates + /api/tracked-posts
├── bot/              # Telegram bot（v3 過渡期 stub，M4 重寫）
├── cli.py            # `threads-tracker api|bot`
├── config.py         # pydantic-settings (.env)
├── db.py             # async SQLAlchemy engine / session
├── llm/              # Haiku（評分）+ Opus（摘要 / 問答）
├── models.py         # v3 schema：10 張表，見 docs/v3_schema.md
├── scheduler.py      # APScheduler：discovery / polling / daily_push
├── schemas.py        # Pydantic API schemas
├── scrapers/
│   ├── watcher.py    # watcher.data keyword search（v3 探索層）
│   ├── apify.py      # v1 single-post / author-timeline（M5 會替換）
│   └── fake.py       # 本地 dev / 測試
├── seeds/
│   ├── keyword_seeds.py  # 30 個觸發詞（5 類）
│   └── loader.py         # 把 keyword 寫進 DB
└── services/
    ├── discovery.py  # M2：批次跑 keywords → candidate_posts
    ├── tracking.py   # candidate → tracked promote 流程
    ├── polling.py    # 分級輪詢（M5 才有資料）
    ├── detection.py  # 爆紅 / milestone 偵測
    └── summarization.py  # Opus 敘事摘要 + 純資料時間軸
alembic/              # v3 schema migration
docs/v3_schema.md     # mermaid ER 圖
tests/                # 27 passed
```

## 開始開發

```bash
uv sync
cp .env.example .env                  # 填 APIFY_TOKEN、ANTHROPIC_API_KEY
mkdir -p data
uv run alembic upgrade head
uv run pytest                         # 27 passed
```

## 灌入 30 個 keyword seeds

```bash
uv run python -m threads_tracker.seeds.loader
```

## 跑一次 discovery（手動觸發、不等 scheduler）

```bash
# M1 驗證 actor 是否能跑：
uv run python scripts/m1_apify_smoke.py                       # 預設 3 keyword × max=5
uv run python scripts/m1_apify_smoke.py --all --max-per-keyword 3   # 全 30 個
```

之後 scheduler 會自動跑 discovery（預設每 12h × max=2，依 `.env` 的
`DISCOVERY_INTERVAL_HOURS` / `DISCOVERY_MAX_PER_KEYWORD` 調整）。

## 啟動服務

```bash
uv run threads-tracker api            # FastAPI + scheduler（discovery/polling/daily_push）
uv run threads-tracker bot            # Telegram bot（v3 過渡期 stub）
```

## 切換 LLM provider

`.env` 設 `LLM_PROVIDER=anthropic` 或 `minimax`：

| Provider  | 必填                  | 備註                                          |
|-----------|----------------------|-----------------------------------------------|
| anthropic | `ANTHROPIC_API_KEY`  | 預設，模型 `claude-opus-4-7` / `claude-haiku-4-5` |
| minimax   | `MINIMAX_API_KEY`    | OpenAI 相容 chat completion；可改 base_url / path |

接 DeepSeek / Qwen / 自架 vLLM 走 `minimax` 路徑改 `MINIMAX_BASE_URL` + `MINIMAX_CHAT_PATH` + `MINIMAX_MODEL`。

## 抓取器策略

| 路徑 | 用途 | 開關 |
|------|------|------|
| `WatcherDataSearchScraper` | M2 探索層（keywords array） | 自動，需 `APIFY_TOKEN` |
| `ApifyThreadsScraper` | v1 single-post / author-timeline（M5 替換） | 自動，需 `APIFY_TOKEN` |
| `FakeThreadsScraper` | 測試 / 本地 dev | 沒 token 時 fallback |

## 資料庫 migration

```bash
uv run alembic revision --autogenerate -m "<message>"
uv run alembic upgrade head
```

`alembic/script.py.mako` 已 import `threads_tracker.models`，新 migration 裡的
`JSONField` 等自訂型別可直接使用。

## 成本估算（v3 production）

| 項目 | 配置 | 月成本 |
|------|------|--------|
| Apify discovery | 30 seed × 每 12h × max=2 | ~$84 |
| Haiku 評分 | 200 篇/日 | ~$6 |
| Opus 摘要 + 問答 | ~10 次/日 | ~$45 |
| **總計** | | **~$135/月** |

降規 / hybrid 替代方案：見 `research/self-scraper` 分支的 `SELF_SCRAPER_FEASIBILITY.md`。
