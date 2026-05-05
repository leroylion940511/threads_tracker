# Threads Tracker — 專案進度

> 跨 session 的單一狀態真相。每次有實質進展就更新這份；不是 changelog，是「現在站在哪」的快照。
> 完整原始企劃見 `threads_tracker_proposal.md`。

**Last updated:** 2026-05-05（第二次）

---

## 企劃書週次完成度

| 週 | 主題 | 狀態 | 備註 |
|----|------|------|------|
| W1 | Apify 可行性驗證 | ⏳ 未驗證 | 客戶端寫好了但沒有 token，欄位 mapping 待對 |
| W2 | 資料層 + 排程 | ✅ 完成 | SQLAlchemy + Alembic + APScheduler 都跑通 |
| W3 | Telegram bot 基礎 | ✅ 完成 | `/track /list /untrack` 可實際運作 |
| W4 | LLM 摘要整合 | ✅ 多 provider | `SummarizationService` + `/digest` + `/timeline` 完成；Anthropic / MiniMax 可切換；Haiku 仍待用 |
| W5 | 爆紅偵測 + 推播 | 🚧 偵測規則寫好；推播沒做 | `evaluate_hot_signal` 可呼叫；scheduler 的 daily_digest_job 是空殼 |
| W6 | 整合測試 + 報告 | ❌ | smoke tests 5/5 過，但端到端真實場景未測 |

---

## 模組狀態

| 模組 | 路徑 | 狀態 | 備註 |
|------|------|------|------|
| 設定 | `src/threads_tracker/config.py` | ✅ | pydantic-settings 讀 .env |
| ORM | `src/threads_tracker/models.py` | ✅ | 對應企劃 §五；BigInt PK 用 dialect variant |
| DB session | `src/threads_tracker/db.py` | ✅ | async SQLAlchemy |
| Migration | `alembic/versions/a1efa9e7d751_*.py` | ✅ | initial schema 已 apply |
| Apify scraper | `scrapers/apify.py` | 🚧 | 未驗證欄位名 |
| Fake scraper | `scrapers/fake.py` | ✅ | 自動 fallback |
| TrackingService | `services/tracking.py` | ✅ | add + poll_once + 寫 snapshot |
| 爆紅偵測 | `services/detection.py` | ✅ | `evaluate_hot_signal()` 可用，未被任何排程呼叫 |
| 分級輪詢 | `services/polling.py` | ✅ | tier_for_age + select_due_posts + reconcile_tiers |
| Scheduler | `scheduler.py` | 🚧 | polling_job 已接；daily_digest_job 是 stub |
| FastAPI | `api.py` | ✅ | `/health`、`POST/GET /api/tracked-posts`、`/snapshots` |
| Telegram bot | `bot/handlers.py` | 🚧 | `/track /list /untrack /poll /digest /timeline` 完成；`/settings /explore` 是 stub |
| 摘要服務 | `services/summarization.py` | ✅ | `get_or_create_evolution` 24h cache + `build_timeline` 純資料 |
| LLM base | `llm/base.py` | ✅ | `EvolutionSummary` + 共用 prompt builder + JSON 解析（容忍 markdown fence） |
| LLM factory | `llm/factory.py` | ✅ | 由 `LLM_PROVIDER` 環境變數選 Anthropic / MiniMax |
| LLM Haiku | `llm/haiku.py` | 🚧 | 寫好但無人呼叫 |
| LLM Opus | `llm/opus.py` | ✅ | provider=anthropic 走這條 |
| LLM MiniMax | `llm/minimax.py` | ✅ | OpenAI 相容 chat completion；base_url / chat_path / model 都可改 |
| CLI | `cli.py` | ✅ | `uv run threads-tracker api\|bot` |
| Tests | `tests/` | ✅ | 19/19 過（smoke 5 + summarization 7 + llm 7） |

---

## Demo 跑法（fake scraper，不需 Apify token）

```bash
# .env 至少填這幾個：
#   TELEGRAM_BOT_TOKEN=...（@BotFather 拿）
#   LLM_PROVIDER=minimax     （或 anthropic）
#   MINIMAX_API_KEY=...      （或 ANTHROPIC_API_KEY）

uv run alembic upgrade head
uv run threads-tracker bot
```

在 Telegram 對 bot：

```
/track https://www.threads.net/@demo/post/HELLO
/list
/poll 1            # demo 用，手動再抓一次（產生新 snapshot）
/poll 1
/digest 1          # 呼叫 LLM；24h 內同一 id cache
/timeline 1        # 純資料，不打 LLM
```

`/poll` 是給 demo 用的「立刻重抓」捷徑；正式環境靠 `uv run threads-tracker api` 帶起來的 APScheduler 自動處理。

---

## 下一步（單一優先）

**Apify 可行性驗證** — 沒有真實資料前，後面所有功能都是空轉。具體：

1. 拿 `APIFY_TOKEN`，寫進 `.env`
2. 跑一次 `ApifyThreadsScraper().fetch_post("...")`，把回傳 raw 印出來
3. 對 `_normalize_post`：欄位名（threads_post_id / username / like_count / reply_count / repost_count / replies）有幾個猜對、要改哪些
4. 跑通後再 `add_tracked_post` 一次真實貼文，確認 snapshot 寫入

不靠 token 之前，可以用 fake scraper 把 `/digest`、`/timeline` 跑起來看格式是否堪用。

## 之後的優先順序

1. （上面）Apify 驗證
2. 自動偵測種子來源（標籤 / 關鍵字 / 白名單） + `/explore`
3. 主動推播（爆紅觸發 + 每日 21:00 digest_job 補完，呼叫 `SummarizationService` + Telegram send）
4. 抓「作者後續 timeline」「他人引用討論」並寫進 `related_posts`（讓 digest 真的有 followups 可吃）
5. Haiku 串接：留言情緒分類 + related_posts 相關性過濾

---

## 關鍵決策 / 踩過的坑

- **SQLite BigInt PK 不會 auto-increment** → models.py 用 `BigInteger().with_variant(Integer(), "sqlite")`，autogenerate 出來的 migration 也帶這個 variant。改 PK 型別時要重新生 migration。
- **alembic migration 找不到自訂 type (`JSONField`)** → 已在 `alembic/script.py.mako` 加 `import threads_tracker.models`，新生的 migration 都會帶這個 import。
- **scraper factory 自動 fallback**：沒設 `APIFY_TOKEN` 就回傳 `FakeThreadsScraper`，讓開發/測試完全不依賴外部服務。
- **預設 SQLite**（`data/threads_tracker.sqlite3`），切 Postgres 只要改 `DATABASE_URL`。
- **APScheduler 排程頻率取 `poll_hot_minutes // 3`**：確保 HOT 級貼文不會錯過時窗，但避免空轉太頻繁。
- **`LLMSummary.content` 存 JSON 字串**（不是新欄位）：`EvolutionSummary` 用 `dataclasses.asdict` 序列化進 `Text`，`parse_evolution()` 還原。換 schema 不必動 migration。
- **summarization 的 24h cache 用「最新 evolution row 的 generated_at」判斷**：強制重算用 `force=True`。SQLite 取出來的 datetime 有時無 tzinfo，`_aware()` 一律補 UTC。
- **LLM provider 抽到 `llm/factory.py`**：`LLM_PROVIDER=anthropic|minimax` 切。`config.llm_provider` 用普通 str 而非 Literal，新 provider 只動 factory 不用改 config schema。
- **MiniMax 走 OpenAI 相容 chat completion**：預設 base_url `https://api.minimax.chat/v1`、path `/text/chatcompletion_v2`、model `abab6.5s-chat`；要接其它 OpenAI 相容服務（DeepSeek/Qwen/vLLM）改這三個值即可。
- **LLM 回傳的 JSON 容忍 ```` ```json ```` fence**：在 `llm/base.parse_evolution_payload` 處理。

---

## 已知未驗證 / 風險

- Apify Threads Scraper 的實際欄位名（`_normalize_post` 是猜的，要等真實 response 校正）
- 沒有 Telegram 推播流程的 retry / rate limit 處理
- DB 沒做 connection pool 調校
- Anthropic API 沒做成本限制（每使用者每日上限尚未實作 — 見企劃書 §八 風險二）
- 沒有 metrics / 健康檢查除了 `/health`

---

## 環境檢查（給未來 session）

```bash
# 確認狀態
uv sync && uv run pytest                             # 應該 5 passed
uv run alembic current                               # 應該顯示 a1efa9e7d751
uv run threads-tracker --help                        # 應該列出 api / bot

# 重置 dev DB（如果 schema 大改）
rm data/threads_tracker.sqlite3
uv run alembic upgrade head
```
