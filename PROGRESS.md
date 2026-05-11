# Threads Tracker — 專案進度（v3 重置）

> 跨 session 的單一狀態真相。每次有實質進展就更新。
> 完整企劃見 `threads_tracker_proposal_v3.md`、任務級里程碑見 `SCHEDULE.md`（v2 已過時，保留作為歷史對照）。
> 進度以里程碑（M1–M8）追蹤，不再用週數。

**Last updated:** 2026-05-11（M3 主幹完成 — scoring 三段、Haiku 五軸 prompt、scoring_job、46 passed；尚缺真實資料驗證 + 人工標記）

---

## v3 里程碑完成度

| 里程碑 | 主題 | 狀態 | 備註 |
|--------|------|------|------|
| M1 | Apify 可行性驗證 | ✅ **GO** | watcher.data，欄位 21/22 對齊，採每 12h × max=2 ≈ $84/月（降規後） |
| M2 | 探索層 + DB 重構 | ✅ | v3 schema (10 表 + ER 圖)、discovery service、seed loader、scheduler；27 passed |
| M3 | 評分層 | 🟡 | 主幹完成（規則 / Haiku 五軸 / 加權 / 三段寫入 / scoring_job）；缺真實資料 + 30 篇人工標記驗證 |
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

**M3 收尾**：主幹（步驟 2–7）已完成，剩兩件需真實資料才能做的事：

1. 啟動 scheduler 跑 1–3 天蒐集真實 candidate（或手動觸發 discovery）— 至少 200 筆才能盲測 prompt
2. ~~寫 `services/scoring.py` 第一層硬規則~~ ✅ `services/scoring.py::apply_hard_rules` — 互動速度 / 粉絲 / 長度 / 繁中 / 業配黑名單
3. ~~寫 Haiku 評分 prompt~~ ✅ 五軸（story_potential / emotional_pull / grassroots / novelty / authenticity）+ verdict + reason
4. ~~接 `llm/haiku.py` 新增 `score_candidate`~~ ✅ `HaikuClassifier.score_candidate` 回傳 `CandidateScore`（含 token / cost）
5. ~~加權合併~~ ✅ `combine_final(rules, haiku)`；s = (story+emo)/2、g、n
6. ~~`scoring_records` 三段式寫入~~ ✅ `ScoringService.score_candidate`（rules → haiku → final），失敗策略寫進模組 docstring
7. ~~`scoring_job` 每 30 分鐘~~ ✅ `scheduler.py::_scoring_job`，config `scoring_interval_minutes` / `scoring_batch_limit`
8. **【待】** 從 M2 資料隨機抽 30 篇人工標記，跟 Haiku verdict 對比準確率（需先有真實資料）

### 觸發評分（手動）
```bash
# 1) 建 DB + 載 seed
uv run alembic upgrade head
uv run python -m threads_tracker.seeds.loader

# 2) 跑一次 discovery（需 APIFY_TOKEN）
uv run python -c "import asyncio; from threads_tracker.scheduler import _discovery_job; asyncio.run(_discovery_job())"

# 3) 評分（需 ANTHROPIC_API_KEY；沒 key 只跑規則層）
uv run python -c "import asyncio; from threads_tracker.scheduler import _scoring_job; asyncio.run(_scoring_job())"
```

## M1 結論（2026-05-10）

- **actor**：`watcher.data/search-threads-by-keywords`（5+ 支比對後選定，理由：keywords 陣列、跨 keyword 自動 dedup、活躍維護、$8/1000 results 略貴但 ops 簡）
- **欄位 mapping**：21/22 expected 全 100% 命中；缺 `lang`（不影響）；多出 `raw_data` 已透過 `raw=item` 整包保留
- **吞吐**：30 keyword × max=3 → 258 筆（actor 對 max 不嚴格，每 keyword 平均 8.6 筆）
- **成本決策**：採「每 12h × max=2 ≈ $84/月」為 production 預設（M2 scheduler config）；研究自寫 scraper 的 ROI 過低（見 `research/self-scraper` 分支報告）

## M2 完成項（2026-05-10）

- 10 張 v3 表（含 `llm_records` 統一 audit）；ER 圖：[`docs/v3_schema.md`](docs/v3_schema.md)
- alembic v3 migration（`3cc2f42838db`）取代 v1 single revision
- `services/discovery.py`：批次餵 keywords，threads_post_id UNIQUE 去重，更新 seed 統計
- `seeds/loader.py`：30 keyword 冪等寫入 DB（`uv run python -m threads_tracker.seeds.loader`）
- `scheduler.py`：`discovery_job`（IntervalTrigger，預設 12h）、`polling_job`（M5 才有資料）、`daily_push_job`（M4 placeholder）
- v1 user-flow（/track/list/untrack + Subscription）拔掉，bot 暫時 stub；M4 重寫

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
