# Threads Tracker v3 — 任務級里程碑

> 與 `threads_tracker_proposal_v3.md` §七 對應，展開到可勾選任務粒度。
> 每個里程碑「完成判準」全部達標後才進下一個。沒有週數，只看任務。

---

## M1 — Apify 可行性驗證（阻塞所有後續）

**前置**：無
**選定 actor**：`watcher.data/search-threads-by-keywords`（$8/1000 results、keywords 陣列、自動跨 keyword 去重；2026-05-10 比對 5+ Threads scrapers 後選定）
**完成判準**：能用關鍵字穩定取得貼文流，知道每月成本上限

- [x] 1.1 註冊 Apify、申請 token、寫進 `.env` 的 `APIFY_TOKEN`
- [x] 1.2 比對 Apify Store 上 Threads 相關 actor，選定 `watcher.data/search-threads-by-keywords`
- [x] 1.3 寫 `scrapers/watcher.py::WatcherDataSearchScraper`：餵 keywords 陣列、回 list[PostPayload]
- [x] 1.4 草擬 30 個 keyword seeds（5 類 × 6），存進 `seeds/keyword_seeds.py`
- [x] 1.5 跑 `scripts/m1_apify_smoke.py` 預設 3 個 keyword × max=5：32 筆，連線 OK
- [x] 1.6 欄位比對：21/22 expected fields 全 100% 命中，`lang` 缺（不影響）；多出 `raw_data` 欄位（已透過 `raw=item` 全保留）
- [x] 1.7 全 30 seed × max=3：**258 筆**（actor 不嚴格遵守 max，平均 8.6/kw），單次成本 ~$2.06
- [x] 1.8 月成本估算：每 4h × 30 seed × max=3 ≈ $370/月；max=10 估 ~$860/月。**Starter 方案 ($49/月) 配合 max=3、每 6h 一次** 是合理區間（~$246/月，預算內）
- [ ] 1.9 寫 M1 結論段（PROGRESS.md「下一步」改寫成 M2），標 GO / NO-GO

---

## M2 — 探索層 + DB 重構

**前置**：M1 GO
**完成判準**：自動跑 discovery，寫入 `candidate_posts` 並更新 `keyword_seeds` 統計
**頻率決策**：依 M1 成本估算採每 12h × max=2 ≈ $84/月（config 可調）

- [x] 2.1 ER 圖（mermaid）→ `docs/v3_schema.md`
- [x] 2.2 改寫 `models.py`：新增 8 張表（含 `llm_records`），改 `tracked_posts` FK
- [x] 2.3 刪舊 migration、`rm data/threads_tracker.sqlite3`、重生 v3 migration
- [x] 2.4 `alembic upgrade head` 驗證；27 passed（v3 smoke + summarization + discovery）
- [x] 2.5 `seeds/keyword_seeds.py` 30 詞 + `seeds/loader.py` 冪等寫入 DB
- [x] 2.6 `services/discovery.py`：批次餵 keywords → 寫 `candidate_posts`（threads_post_id UNIQUE 去重）
- [x] 2.7 `scheduler.py`：新增 `discovery_job`（IntervalTrigger，預設 12h），更新 seed `last_polled_at` + `total_candidates_yielded`
- [x] 2.8 `tests/test_discovery.py`：6 個 unit test 涵蓋 seed loading、dedup、disabled seed、stat update

---

## M3 — 評分層

**前置**：M2 `candidate_posts` 有真實資料累積（至少 200 筆）
**完成判準**：每 30 分鐘自動評分新 candidate，產 final_score 並寫 `scoring_records`

- [ ] 3.1 寫 `services/scoring.py` 第一層硬規則：互動速度 / 粉絲數 / 文字長度 / 繁中檢測 / 業配黑名單
- [ ] 3.2 寫 Haiku 評分 prompt（五項 0–1 + verdict + reason，JSON 輸出）
- [ ] 3.3 接 `llm/haiku.py`，新增 `score_candidate(post) -> SemanticScore`
- [ ] 3.4 寫加權合併：`final_score = 0.4·v + 0.3·s + 0.2·g + 0.1·n`
- [ ] 3.5 寫 `scoring_records` 三段式寫入（rules → haiku → final），每段記 `cost_usd`
- [ ] 3.6 接 `scheduler.py`：新增 `scoring_job` 每 30 分鐘批次評分尚未評分的 candidate
- [ ] 3.7 從 M2 資料隨機抽 30 篇人工標記（track / skip），跟 Haiku verdict 對比，記準確率
- [ ] 3.8 unit test：硬規則 + 加權邏輯（mock Haiku）

---

## M4 — 候選排程層 + 推送層

**前置**：M3 `final_score` 可算
**完成判準**：每日 09:00 推 5 篇到 Telegram，破例觸發即時推送，按鈕回寫 `feedback`

- [ ] 4.1 寫 `services/feed.py::pick_daily_top5`：從過去 24h 候選池選 3 已爆 + 2 早期
- [ ] 4.2 寫 `services/feed.py::check_breaking`：找符合即時破例條件的候選（每日上限 2）
- [ ] 4.3 `daily_pushes` 寫入流程，避免重複推同一篇
- [ ] 4.4 改 `bot/handlers.py`：每日推送訊息格式（標題 / metadata / Opus 摘要 / 三按鈕）
- [ ] 4.5 inline button callback handler：❤️ → `feedback.action='collect'`、👎 → `'dislike'`、🔕 → `'mute_event'`
- [ ] 4.6 `bot/handlers.py` 砍掉 `/track <url>`，新增 `/feed`、`/digest`
- [ ] 4.7 接 `scheduler.py`：`daily_push_job` 每日 09:00、`breaking_check_job` 每 10 分鐘
- [ ] 4.8 端到端測：fake scraper → discovery → scoring → daily push 訊息真的出現在 Telegram

---

## M5 — 收藏追蹤層

**前置**：M4 ❤️ 按鈕能寫 `feedback`
**完成判準**：收藏一篇後，系統自動偵測四類後續事件並推送

- [ ] 5.1 寫升格邏輯：`feedback.action='collect'` → 建 `tracked_posts` row，啟動分級輪詢
- [ ] 5.2 改 `services/polling.py`：以 `tracked_posts.polling_tier` 為驅動，沿用 tier_for_age
- [ ] 5.3 寫 `related_posts` 偵測 — `author_followup`：作者新貼文，Haiku 判斷與原事件相關性
- [ ] 5.4 寫 `related_posts` 偵測 — `author_reply`：原 PO 在自己貼文下的新留言
- [ ] 5.5 寫 `related_posts` 偵測 — `hot_reply`：他人留言按讚數 / 回覆數突破閾值
- [ ] 5.6 寫 `related_posts` 偵測 — `quote`：用 Threads search 找該貼文的引用 / quote
- [ ] 5.7 改 `services/detection.py::evaluate_milestone`：用 Haiku 判定 `is_milestone`
- [ ] 5.8 後續推送邏輯：日常更新加進每日彙整、`is_milestone=true` 即時推送
- [ ] 5.9 新增 bot 指令：`/saved` 列收藏、`/timeline <id>` 看時間軸
- [ ] 5.10 端到端測：fake 收藏 → 餵假後續資料 → 確認推送觸發

---

## M6 — 問答層

**前置**：M5 `tracked_posts` 與 `related_posts` 有資料
**完成判準**：`/ask <id>` 能進入問答模式、多輪對話、`/exit` 或超時離開、token 成本實測過

- [ ] 6.1 寫 `services/qa.py`：session 狀態管理（每使用者同時只能一個 active session，記憶體 dict 即可）
- [ ] 6.2 寫 context 組裝器：原貼文 + 最新 `EvolutionSummary` + 全留言 + 作者近 30 篇 + `related_posts`
- [ ] 6.3 `bot/handlers.py` 新增 `/ask <id>` handler：建 `qa_sessions` row、組 system prompt、回 prompt
- [ ] 6.4 改 message handler：active session 中所有非指令訊息走 Opus 多輪對話（system prompt 開 prompt cache）
- [ ] 6.5 寫 `/exit` handler 與 5 分鐘 idle timeout（背景 task 掃 `qa_sessions.started_at`）
- [ ] 6.6 `qa_messages` 寫入：每輪 user / assistant 各一筆，連同 `cost_usd` 記到 `llm_records`
- [ ] 6.7 token 實測：跑 5 個真實事件 × 3 輪問答，記錄 input / output / cache hit 比例與成本
- [ ] 6.8 unit test：session 狀態機（開 → 訊息 → exit / timeout）

---

## M7 — 評估與調優

**前置**：M6 完整流水線可跑、系統累積至少 7 天真實資料
**完成判準**：產出收藏率 / 後續命中率數字、30 組問答自評結果、有調過至少一輪 prompt / 閾值

- [ ] 7.1 寫評估腳本 `scripts/eval_collection_rate.py`：`SUM(feedback collect) / SUM(daily_pushes)`，依 push_type 分組
- [ ] 7.2 寫評估腳本 `scripts/eval_followup_hit.py`：30 天內 `related_posts ≥ 1` 的 `tracked_posts` 比例
- [ ] 7.3 系統連續 7 天無人工介入運行，蒐集真實資料
- [ ] 7.4 分析「被 👎 / 🔕 的 candidate」共同特徵，調 Haiku 評分 prompt
- [ ] 7.5 分析 `keyword_seeds.total_collected = 0` 的種子，標 `enabled=false`
- [ ] 7.6 抽 30 組 (問題, 回答) pair，研究者自評三項：事實正確性 / 引用精準度 / 幻覺有無
- [ ] 7.7 成本對帳：實際 `llm_records.cost_usd` 月總和 vs 企劃書 §八 預估，差異寫進報告

---

## M8 — 報告與 demo

**前置**：M7 評估數據完整
**完成判準**：報告交付、demo 影片產出、GitHub 整理乾淨

- [ ] 8.1 撰寫報告 Ch1–3（動機 / 目標 / 系統架構）— 直接從 v3 企劃書改寫
- [ ] 8.2 撰寫報告 Ch4–5（核心功能 / DB schema）
- [ ] 8.3 撰寫報告 Ch6（評估結果）— 灌 M7 數據
- [ ] 8.4 撰寫報告 Ch7 案例分析：挑 3–5 個從推送 → 收藏 → 完整生命週期事件，附時間軸圖
- [ ] 8.5 撰寫報告 Ch8 倫理章節（隱私 / 去識別化 / 資料刪除）
- [ ] 8.6 錄 5 分鐘 demo 影片：推送 → 收藏 → 後續觸發 → 問答
- [ ] 8.7 整理 GitHub README、清理 dev 殘留檔、確認 `.env.example` 完整
- [ ] 8.8 製作口頭簡報 slides（10–15 頁）

---

## 里程碑風險檢查點

| 時點 | 檢查 | 觸發條件 |
|------|------|---------|
| M1 完成 | Apify 是否可用、成本是否爆 | NO-GO → 改備案：fake 跑通流水線 + 模擬資料案例 |
| M3 完成 | Haiku 與人工標記準確率 | < 60% → 補一輪 prompt 調整再進 M4 |
| M4 完成 | Telegram bot 真的能推送 | 推不出 → 卡住一切後續，優先除錯 |
| M6 完成 | 問答 token 成本 | 單次 > $0.3 → 強制降中量 context 為預設 |
| M7 完成 | 收藏率 | < 15% → 報告誠實寫，但要分析原因（評分 vs 使用者口味）|
