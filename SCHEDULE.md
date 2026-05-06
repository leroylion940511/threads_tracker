# Threads Tracker v3 — 任務級時程表

> 與 `threads_tracker_proposal_v3.md` §七 對應，但展開到可勾選任務粒度。
> 每週開工前確認上週「完成判準」全部達標再進下週。

---

## W1 — Apify 可行性驗證（阻塞所有後續）

**前置**：無
**完成判準**：能用關鍵字穩定取得貼文流，知道每月成本上限

- [ ] 1.1 註冊 Apify、申請 token、寫進 `.env` 的 `APIFY_TOKEN`
- [ ] 1.2 用 `automation-lab/threads-scraper` 跑單一 url 抓取，印出 raw response 確認連線 OK
- [ ] 1.3 切換 search 模式，用一個關鍵字（例：「後來」）跑一次，印 raw response
- [ ] 1.4 比對 `scrapers/apify.py::_normalize_post` 欄位名，列出哪些對 / 哪些要改
- [ ] 1.5 修 `_normalize_post`，跑通到 `tracking.add_tracked_post` 能寫入一筆真實 candidate
- [ ] 1.6 跑 10 次 search、記錄 compute units 消耗，推算每 60 分鐘 × 30 種子的月成本
- [ ] 1.7 寫一頁 W1 結論（成本是否可接受、欄位 mapping 結果），決定 GO / NO-GO

---

## W2 — 探索層 + DB 重構

**前置**：W1 GO
**完成判準**：每 60 分鐘自動跑一次 discovery，寫入 `candidate_posts`

- [ ] 2.1 在 markdown 畫 v3 完整 ER 圖（10 張表、FK 關係）
- [ ] 2.2 改寫 `models.py`：新增 7 張表（`candidate_posts` / `scoring_records` / `daily_pushes` / `feedback` / `qa_sessions` / `qa_messages` / `keyword_seeds`），改 `tracked_posts` FK
- [ ] 2.3 刪舊 migration `a1efa9e7d751_*.py`、`rm data/threads_tracker.sqlite3`、`alembic revision --autogenerate -m "v3 schema"`
- [ ] 2.4 跑 `alembic upgrade head` 驗證、寫 schema smoke test
- [ ] 2.5 建 `keyword_seeds` 初始 fixture：30 個觸發詞分 5 類（後續暗示 / 求助共鳴 / 事件性 / 敘事開頭 / 情緒爆發）
- [ ] 2.6 寫 `services/discovery.py`：跑單一 keyword → 呼叫 scraper → 寫 `candidate_posts`（去重用 `threads_post_id` UNIQUE）
- [ ] 2.7 接 `scheduler.py`：新增 `discovery_job` 每 60 分鐘跑一次，更新 `keyword_seeds.last_polled_at` 與 `total_candidates_yielded`
- [ ] 2.8 寫 unit test：用 fake scraper 模擬 discovery，確認去重與 `keyword_seeds` 統計正確

---

## W3 — 評分層

**前置**：W2 `candidate_posts` 有真實資料累積（至少 200 筆）
**完成判準**：每 30 分鐘自動評分新 candidate，產 final_score 並寫 `scoring_records`

- [ ] 3.1 寫 `services/scoring.py` 第一層硬規則：互動速度 / 粉絲數 / 文字長度 / 繁中檢測 / 業配黑名單
- [ ] 3.2 寫 Haiku 評分 prompt（五項 0–1 + verdict + reason，JSON 輸出）
- [ ] 3.3 接 `llm/haiku.py`，新增 `score_candidate(post) -> SemanticScore`
- [ ] 3.4 寫加權合併：`final_score = 0.4·v + 0.3·s + 0.2·g + 0.1·n`
- [ ] 3.5 寫 `scoring_records` 三段式寫入（rules → haiku → final），每段記 `cost_usd`
- [ ] 3.6 接 `scheduler.py`：新增 `scoring_job` 每 30 分鐘批次評分尚未評分的 candidate
- [ ] 3.7 從 W2 資料隨機抽 30 篇人工標記（track / skip），跟 Haiku verdict 對比，記準確率
- [ ] 3.8 unit test：硬規則 + 加權邏輯（mock Haiku）

---

## W4 — 候選排程層 + 推送層

**前置**：W3 `final_score` 可算
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

## W5 — 收藏追蹤層

**前置**：W4 ❤️ 按鈕能寫 `feedback`
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

## W6 — 問答層

**前置**：W5 `tracked_posts` 與 `related_posts` 有資料
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

## W7 — 評估與調優

**前置**：W6 完整流水線可跑、系統至少跑了 7 天累積真實資料
**完成判準**：產出收藏率 / 後續命中率數字、30 組問答自評結果、有調過至少一輪 prompt / 閾值

- [ ] 7.1 寫評估腳本 `scripts/eval_collection_rate.py`：`SUM(feedback collect) / SUM(daily_pushes)`，依 push_type 分組
- [ ] 7.2 寫評估腳本 `scripts/eval_followup_hit.py`：30 天內 `related_posts ≥ 1` 的 `tracked_posts` 比例
- [ ] 7.3 系統 7 天無人工介入運行，蒐集真實資料
- [ ] 7.4 分析「被 👎 / 🔕 的 candidate」共同特徵，調 Haiku 評分 prompt
- [ ] 7.5 分析 `keyword_seeds.total_collected = 0` 的種子，標 `enabled=false`
- [ ] 7.6 抽 30 組 (問題, 回答) pair，研究者自評三項：事實正確性 / 引用精準度 / 幻覺有無
- [ ] 7.7 成本對帳：實際 `llm_records.cost_usd` 月總和 vs 企劃書 §八 預估，差異寫進報告

---

## W8 — 報告與 demo

**前置**：W7 評估數據完整
**完成判準**：報告交付、demo 影片產出、GitHub 整理乾淨

- [ ] 8.1 撰寫報告 Ch1–3（動機 / 目標 / 系統架構）— 直接從 v3 企劃書改寫
- [ ] 8.2 撰寫報告 Ch4–5（核心功能 / DB schema）
- [ ] 8.3 撰寫報告 Ch6（評估結果）— 灌 W7 數據
- [ ] 8.4 撰寫報告 Ch7 案例分析：挑 3–5 個從推送 → 收藏 → 完整生命週期事件，附時間軸圖
- [ ] 8.5 撰寫報告 Ch8 倫理章節（隱私 / 去識別化 / 資料刪除）
- [ ] 8.6 錄 5 分鐘 demo 影片：推送 → 收藏 → 後續觸發 → 問答
- [ ] 8.7 整理 GitHub README、清理 dev 殘留檔、確認 `.env.example` 完整
- [ ] 8.8 製作口頭簡報 slides（10–15 頁）

---

## 跨週風險檢查點

| 時點 | 檢查 | 觸發條件 |
|------|------|---------|
| W1 結束 | Apify 是否可用、成本是否爆 | NO-GO → 改備案：fake 跑通流水線 + 模擬資料案例 |
| W3 結束 | Haiku 與人工標記準確率 | < 60% → 多花 2 天調 prompt 再進 W4 |
| W4 結束 | Telegram bot 真的能推送 | 推不出 → 卡住一切後續，優先除錯 |
| W6 結束 | 問答 token 成本 | 單次 > $0.3 → 強制降中量 context 為預設 |
| W7 結束 | 收藏率 | < 15% → 報告誠實寫，但要分析原因（評分 vs 使用者口味）|
