# Threads Tracker — 專案進度（v3 重置）

> 跨 session 的單一狀態真相。每次有實質進展就更新。
> 完整企劃見 `threads_tracker_proposal_v3.md`、任務級里程碑見 `SCHEDULE.md`（v2 已過時，保留作為歷史對照）。
> 進度以里程碑（M1–M8）追蹤，不再用週數。

**Last updated:** 2026-05-07（v3 reset day）

---

## v3 里程碑完成度

| 里程碑 | 主題 | 狀態 | 備註 |
|--------|------|------|------|
| M1 | Apify 可行性驗證 | ⏳ 阻塞中 | 沒 token，今天先寫完企劃書 |
| M2 | 探索層 + DB 重構 | ❌ | 新 schema 待設計 migration |
| M3 | 評分層 | ❌ | Haiku 評分 prompt 待寫 |
| M4 | 候選排程 + 推送層 | ❌ | inline button 流程待寫 |
| M5 | 收藏追蹤層 | ❌ | 四類後續事件偵測待寫 |
| M6 | 問答層 | ❌ | `/ask` 對話模式待寫 |
| M7 | 評估與調優 | ❌ | 收藏率 / 後續命中率指標 |
| M8 | 報告與 demo | ❌ | 案例分析 + 問答自評 |

---

## 從 v1 baseline 繼承的資產（評估後續處置）

v1 已完成的東西，按 v3 架構重新審視：

| 既有檔 | 處置 | 備註 |
|--------|------|------|
| `config.py` / `db.py` / `cli.py` / `logging.py` | ✅ 留 | 基礎設施可直接沿用 |
| `models.py` | 🔧 **大改** | 新增 `candidate_posts` / `scoring_records` / `daily_pushes` / `feedback` / `qa_sessions` / `qa_messages` / `keyword_seeds`；現有 `tracked_posts` 改為 `candidate_post_id` FK |
| `alembic/versions/a1efa9e7d751_*.py` | 🔧 重生 | schema 大改後重建 migration |
| `scrapers/apify.py` `fake.py` `factory.py` | ✅ 留 | 仍是主資料來源，欄位 mapping 等 M1 驗證 |
| `services/tracking.py` | 🔧 改 | `add_tracked_post` 入口從「使用者貼 url」改為「使用者按 ❤️ 升格 candidate_post」 |
| `services/polling.py` | ✅ 留 | tier_for_age + select_due_posts 邏輯沿用 |
| `services/detection.py` | 🔧 改 | `evaluate_hot_signal` 改為「重大進展偵測」用，給追蹤層 |
| `services/summarization.py` | ✅ 留 | `EvolutionSummary` + 24h cache 沿用，問答層也會用到 |
| `llm/base.py` `factory.py` `opus.py` `minimax.py` | ✅ 留 | provider 抽象沿用 |
| `llm/haiku.py` | 🔧 **接上去** | 之前寫好沒人呼叫，v3 由評分層 + 重大進展偵測 + 留言相關性過濾使用 |
| `bot/handlers.py` | 🔧 大改 | 砍掉 `/track <url>`（不再需要使用者貼連結）；新增 inline button callback、`/saved` `/ask` `/exit` `/feed` |
| `scheduler.py` | 🔧 改 | 新增「每日 09:00 推送」「每 60 分鐘探索」「即時破例推送檢查」job |
| `api.py` | ✅ 留 | `/health` + 內部 webhook 沿用 |
| `tests/test_smoke.py` `test_summarization.py` `test_llm.py` | ⚠️ 部分要改 | 砍掉測 `/track <url>` 的 case；新增評分層 + 推送層測試 |

**v3 新增模組（待開）**：
- `services/discovery.py`（探索層：關鍵字輪詢）
- `services/scoring.py`（評分層：硬規則 + Haiku + 加權）
- `services/feed.py`（候選排程層：每日 Top 5 + 即時破例）
- `services/qa.py`（問答 session 管理 + context 組裝）

---

## 下一步（單一優先）

**M1：Apify 可行性驗證**。沒 token 之前無法前進。具體：

1. 註冊 Apify、拿到 `APIFY_TOKEN` 寫進 `.env`
2. 用 `automation-lab/threads-scraper` 跑一次「關鍵字 search 模式」（不是抓單一 url），確認能不能用「後來」「求後續」這類觸發詞流式取得貼文
3. 校正 `_normalize_post`：欄位名（threads_post_id / username / like_count / reply_count / repost_count / replies）對哪幾個、要改哪些
4. 估免費 / 付費額度：每跑 100 次 search 用掉多少 quota，決定是否能撐每 60 分鐘 × 30 種子的探索頻率

如果 M1 結束 token 仍拿不到，**進入備案**：用 fake scraper 把整條流水線跑通，案例分析章節改用「模擬資料」並在報告中誠實說明。

---

## 關鍵決策 / 踩過的坑（沿用 v1）

- SQLite BigInt PK 不會 auto-increment → `BigInteger().with_variant(Integer(), "sqlite")`
- alembic 自訂 type (`JSONField`) 找不到 → `alembic/script.py.mako` 加 `import threads_tracker.models`
- scraper factory 沒設 token 自動 fallback fake
- 預設 SQLite，切 Postgres 改 `DATABASE_URL`
- APScheduler 排程頻率取 `poll_hot_minutes // 3`
- `LLMSummary.content` 存 JSON 字串（不開新欄位），`parse_evolution()` 還原
- summarization 24h cache 用「最新 evolution row 的 generated_at」判斷
- LLM provider 抽到 `llm/factory.py`，`LLM_PROVIDER=anthropic|minimax` 切
- LLM 回傳的 JSON 容忍 ` ```json ` fence

---

## v3 新引入的設計決策（待驗證）

- **每日推送 5 篇 = 3 已爆 + 2 早期**：固定配比，可由 config 調整
- **即時破例條件**：發文 1h 內互動速度 Top 1% + Haiku verdict=track + semantic_score > 0.85，每日上限 2 則
- **問答預設重量 context**：原貼文 + 摘要 + 全部留言 + 作者近 30 篇 + 後續事件，預估每次 8k–35k input tokens
- **個位數使用者共用同一份每日推送**：先不做個人化，feedback 純粹當資料蒐集

---

## 已知未驗證 / 風險

- Apify Threads Scraper 的 search 模式實際吞吐量與配額（M1 要驗）
- Apify 欄位名（`_normalize_post` 是猜的）
- 重量 context 問答 token 成本實測（預估 $0.1/次 但沒驗）
- Threads 搜尋 cookie 認證限制是否影響 Actor 可用性
- 沒有推播 retry / rate limit 處理

---

## 環境檢查

```bash
uv sync && uv run pytest                             # baseline 應該 19 passed
uv run alembic current                               # 目前 a1efa9e7d751，v3 會重生
uv run threads-tracker --help                        # 列 api / bot

# v3 schema 重置（M2 開工前）
rm data/threads_tracker.sqlite3
uv run alembic upgrade head
```
