# 自寫 Threads Scraper 可行性報告

**branch**: `research/self-scraper`
**研究日期**: 2026-05-10
**動機**: watcher.data Apify scraper 月成本 ~$246（每 6h × max=3）對畢業專案而言偏高，評估自建替代路徑的 ROI。

---

## TL;DR

**不建議全面自寫，但「降規 Apify 配置」+「未來可選的官方 API hybrid」是務實路徑。**

| 選項 | 月成本 | 開發工 | 維運風險 | 推薦度 |
|------|--------|--------|---------|--------|
| 1. **降規 watcher.data**（每 12h × max=2） | **~$80** | 0（改 cron 配置） | 低 | ⭐⭐⭐ 最務實 |
| 2. 換 Apify igview-owner | ~$154 | 半天 | 低 | ⭐⭐ |
| 3. **官方 API + 自寫 web 補抓 engagement**（hybrid） | <$5 | 2–4 週 + app review 2–4 週 | 中 | ⭐⭐ 學術價值高 |
| 4. 純自寫 Playwright（含 search） | <$5 + VPS | 4–6 週 | 高 | ❌ 不值 |
| 5. 反向工程 mobile API | <$5 | 6+ 週 | 極高（ToS） | ❌ |

論文寫作期內，**先採方案 1**，等 M2–M4 整條流水線跑通再評估是否往 hybrid 演進。

---

## 1. 現況問題

watcher.data 實測成本：

- 30 seed × max=3 一次 run = 258 筆 = $2.06
- 每 6h 跑 → $2.06 × 4 × 30 = **$246/月**

對畢業專案 6 個月跑期 = **$1,476 總成本**。預算偏緊。

---

## 2. 三條自寫路徑

### 路徑 A：Meta 官方 Threads API（純官方）

**摘要**：Meta 2024 年中開放 Threads API，2025 年加入 keyword search 端點。

| 項目 | 內容 |
|------|------|
| 端點 | `GET https://graph.threads.net/v1.0/keyword_search?q={keyword}&search_type=RECENT` |
| Auth | Facebook Developer App + access token + permissions `threads_basic` + `threads_keyword_search` |
| 速率上限 | **2,200 queries / 24h per user**（畢業專案實際只有 1 user） |
| 費用 | **完全免費** |
| 回傳欄位 | `id`, `text`, `media_type`, `permalink`, `timestamp`, `username`, `has_replies`, `is_quote_post`, `is_reply` |
| App Review | `threads_keyword_search` 需通過審核（2–4 週、需錄製 screencast 證明用途） |

**致命缺陷**：
- 🚨 **官方 API 不回 like_count / reply_count / view_count / repost_count**（這些 metrics 屬於 Insights API，**只開放本人擁有的貼文**）
- 沒有互動數 → v3 評分層的「互動速度」指標完全失效 → M3 評分層做不出來

**結論**：純官方 API **不能**取代 watcher.data。

---

### 路徑 B：Hybrid（官方 API search + 自寫 web 抓 engagement）

**思路**：官方 API 拿到 post id 與 permalink，再用 Playwright 抓對應公開頁，從 embedded JSON 解 like/reply count。

**技術可行性**：
- threads.net 公開貼文頁面 **免登入** 可訪問（已驗證）
- HTML 內 `<script type="application/json" data-sjs>` 標籤含完整資料（含 engagement counts）
- 用 `parsel + jmespath` 可解 JSON

**成本與效能估算**（30 seed × 每 6h × max=3 = ~258 筆/run × 4 runs/day = ~1000 unique posts/day）：

| 項目 | 估算 |
|------|------|
| 官方 search API call | 30 keywords × 4 runs = 120/day（額度 2200/day，<6%） |
| Playwright 抓公開頁 | 1000 posts/day → 約 35 req/hour |
| 主機費（VPS） | $5/月 |
| Apify 費用 | $0 |
| **每月總成本** | **~$5/月** |

**風險**：
- ❌ App Review 卡 2–4 週（學期時程吃緊）
- ❌ Playwright 跑量大要處理：page load 失敗、IP rate-limit、Cookie / fingerprint 偵測、HTML 結構變動
- ❌ Meta 隨時可改 keyword_search rate limit 或下架

**開發工估算**：
- 申請 + 審核 app：**1 週工 + 2–4 週等待**
- 串 keyword_search → DB：3 天
- Playwright fetcher（含 retry / backoff / 反偵測）：1 週
- 解 embedded JSON 對應 v3 PostPayload schema：3 天
- 觀測 + 警報：3 天
- **總計：3–4 週 active dev + app review wait**

---

### 路徑 C：純 Playwright（不用官方 API）

**思路**：完全靠 web 自爬。
**致命缺陷**：threads.net **search/discovery 強制登入** — 不登入無法搜尋，登入帳號被 ban 風險高。
**結論**：❌ 不可行。

---

### 路徑 D：反向工程 mobile/web internal API

**思路**：解 threads.net 的 GraphQL 持久化查詢 hash + `x-ig-app-id: 238260118697367`。
**致命缺陷**：
- Meta 用 persisted queries（hash-based），需從前端 bundle 抽 hash
- 隨時換 hash 即破
- 違反 ToS，畢業論文不適合
**結論**：❌

---

## 3. 比較矩陣

| 維度 | A 官方 API | B Hybrid | watcher.data |
|------|----------|---------|--------------|
| keyword search | ✅ 免費 | ✅ 免費 | ✅ $8/1000 |
| like_count | ❌ | ✅ web 解 | ✅ |
| reply_count | ❌ | ✅ web 解 | ✅ |
| author 完整資料 | △（只 username） | ✅ | ✅ |
| 開發工 | 1 週 | 3–4 週 + 審核 | 0（已做） |
| 月成本 | $0 | ~$5 | ~$246 |
| 維運風險 | 低 | 中 | 低（除非 Apify 漲價） |
| 論文「自建系統」加分 | 低 | **高** | 低 |

---

## 4. 不自寫的「降規 Apify」選項（推薦）

**重點**：watcher.data 的成本可大幅壓低，不一定要全砍。

| 配置 | 單次成本 | 頻率 | 月成本 | 取得貼文/月 |
|------|---------|------|-------|-----------|
| 每 6h × max=3（M1 原計劃） | $2.06 | 4/day | $246 | ~30,000 |
| 每 12h × max=2 | ~$1.40 | 2/day | ~$84 | ~10,000 |
| 每 24h × max=2 | ~$1.40 | 1/day | ~$42 | ~5,000 |
| 每 6h × keyword 輪替（每次 10 個） | ~$0.7 | 4/day | ~$84 | ~10,000 |

10,000 候選/月 × 評分後篩選 = 仍能撐起每日推送 5 篇 + 收藏追蹤。

---

## 5. 建議路徑

### 短期（M2–M4）
**沿用 watcher.data，把頻率降到每 12h × max=2 ≈ $84/月**。先把整條流水線（探索→評分→推送→追蹤）跑通，蒐集真實使用資料，再評估是否需要更高頻率。

### 中期（M7 評估後）
若 M7 數據顯示需要更密集探索，再評估：
- **預算夠就升 watcher.data 頻率**（最便宜的工程選擇）
- **想要論文加分章節**：開 Hybrid POC，作為「成本控制與系統演進」案例分析

### 長期（畢業後若繼續維運）
Hybrid 路徑值得做，自由度與成本都最佳。

---

## 6. 若要做 Hybrid POC（給後續參考）

**Phase 1**：申請 Meta Developer App + app review（while doing Phase 2 prep）
**Phase 2**：寫 `scrapers/meta_official.py` 實作 keyword_search 呼叫
**Phase 3**：寫 `scrapers/threads_web.py` 用 Playwright 抓公開頁 + 解 embedded JSON
**Phase 4**：合併 → 同樣回 `PostPayload`，可無縫替換 watcher.data

技術細節參考：
- Scrapfly 2026 教學：https://scrapfly.io/blog/posts/how-to-scrape-threads
- Meta 官方文件：https://developers.facebook.com/docs/threads/keyword-search/
- Insights 限制：https://developers.facebook.com/docs/threads/insights/

---

## 7. 結論

**目前不要自寫**。降規 Apify 到 $84/月即可解決成本問題，省下的工時（3–4 週）拿去把 v3 主流程做完更划算。Hybrid 是好的「未來工作」章節題目，畢業前不必碰。
