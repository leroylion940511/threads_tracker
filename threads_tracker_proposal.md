# Threads 熱點文章後續追蹤系統 — 專題企劃書

## 一、專題動機與背景

Threads 自 2023 年推出以來，成為華語圈重要的短文社群平台之一。平台上經常出現素人發布的貼文意外爆紅的現象——可能是一段感情糾紛、職場觀察、突發事件目擊紀錄，或是引發共鳴的生活片段。

這類爆紅貼文的特徵是：**強時效性、強敘事性、但後續發展高度仰賴原 PO 主動更新**。讀者在當下被吸引，留言追問「後來呢？」「更新一下」，但若不持續回到該帳號頁面查看，極容易錯過後續發展。即便 Threads 提供追蹤功能，當追蹤對象增加，重要更新也會被資訊流稀釋。

本專題旨在打造一套**自動化熱點貼文偵測與後續追蹤系統**，讓使用者能夠以低成本的方式持續關注他們感興趣的事件演進，並透過 Telegram 接收摘要式推播。

## 二、專題目標

### 主要目標

1. 自動偵測 Threads 上正在爆紅的素人貼文，並提供使用者快速收藏追蹤的機制
2. 持續監測被追蹤貼文的後續動態，包含：原作者新貼文、原貼文留言更新、其他使用者引用討論
3. 運用 LLM 對追蹤內容進行語意理解與摘要，產出「事件演進敘事」而非單純資訊堆疊
4. 透過 Telegram Bot 提供推播通知與指令查詢雙向互動介面

### 次要目標

1. 建立可擴充的資料模型，未來可支援其他社群平台（X、Plurk 等）
2. 設計合理的輪詢與成本控制機制，使單一使用者月成本可控制在 1 美元以內
3. 探討第三方資料來源在學術專題中的合規性與可持續性

## 三、系統架構

### 整體架構圖

```
┌─────────────────────────┐         ┌──────────────────────────┐
│ Apify Threads Scraper   │         │ 使用者手動提交貼文連結    │
│ (第三方資料來源)         │         │ (透過 Telegram /track)    │
└───────────┬─────────────┘         └──────────────┬───────────┘
            │                                       │
            └───────────────┬───────────────────────┘
                            ↓
                ┌───────────────────────┐
                │ 資料擷取與正規化層     │
                │ (FastAPI + Pydantic)  │
                └───────────┬───────────┘
                            ↓
                ┌───────────────────────┐
                │ PostgreSQL 資料庫      │
                │ - tracked_posts       │
                │ - post_snapshots      │
                │ - users / subs        │
                │ - llm_summaries       │
                └───────────┬───────────┘
                            ↓
                ┌───────────────────────┐
                │ APScheduler 排程器     │
                │ (分級輪詢策略)         │
                └───────────┬───────────┘
                            ↓
            ┌───────────────┼───────────────┐
            ↓               ↓               ↓
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │ 爆紅偵測器    │ │ Haiku 分群    │ │ Opus 摘要     │
    │ (規則引擎)    │ │ (留言情緒)    │ │ (事件演進)    │
    └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
           └────────────────┼────────────────┘
                            ↓
                ┌───────────────────────┐
                │ Telegram Bot          │
                │ (python-telegram-bot) │
                │ - 推播通知             │
                │ - 指令查詢             │
                └───────────────────────┘
```

### 技術選型

| 層級 | 技術 | 選用理由 |
|------|------|---------|
| 後端框架 | Python 3.11 + FastAPI | 非同步友善、生態成熟、開發速度快 |
| 資料庫 | PostgreSQL 15 | 支援 JSONB 儲存彈性內容、時序查詢效能佳 |
| 排程 | APScheduler | 輕量級，不需另外架 Celery + Redis |
| 資料來源 | Apify Threads Scraper | 文件齊全、有免費額度、合規責任在服務商 |
| LLM | Anthropic Claude (Haiku + Opus) | 雙層架構平衡成本與品質 |
| 通知介面 | python-telegram-bot | Telegram Bot 主流 SDK、文件完整 |
| 部署 | Docker + Railway / Fly.io | 學生方案便宜、PostgreSQL 一鍵附加 |

## 四、核心功能設計

### 4.1 熱點偵測（混合模式）

**自動偵測**採用雙訊號疊加判定：

- **絕對門檻**：貼文讚數超過 1000 或留言數超過 200
- **相對速度**：過去 1 小時互動數成長率超過 50%

兩個條件同時成立才視為爆紅候選。單看絕對數會漏掉小帳號的爆文，單看速度會被一般洗版內容干擾。

自動偵測的種子來源規劃為：追蹤特定 Threads 標籤、特定話題關鍵字、以及白名單素人帳號清單。

**手動補充**透過 Telegram 指令 `/track <貼文連結>` 即可加入追蹤清單，繞過自動偵測限制。這也是專題最重要的退路——若自動偵測效果不佳，手動模式仍能讓系統運作。

### 4.2 後續追蹤（三向監控）

針對每一則被追蹤的貼文，系統同時監控三個面向：

**原 PO 之後的新貼文**：抓取作者帳號的 timeline，比對自被追蹤之後是否有新貼文，並用 LLM 判斷新貼文是否與原事件相關。

**原貼文下的留言更新**：定期重新抓取留言串，記錄新增留言、被讚最高的留言、是否有原 PO 親自回覆。

**其他人引用/轉發的相關討論**：以原貼文連結或關鍵詞為查詢，搜尋平台上其他人發起的相關討論串。

### 4.3 LLM 雙層摘要架構

**第一層（Haiku 4.5）**負責高頻、低成本的處理：

- 留言情緒分類（支持/反對/中立/詢問）
- 留言主題分群
- 判斷新貼文與原事件的相關性

**第二層（Opus 4.7）**負責低頻、高品質的處理：

- 事件演進敘事摘要：把原貼文 + 後續新貼文 + 熱門留言串成一段「這件事現在發展到哪了」的敘事
- 重大進展偵測：判斷某次更新是否構成需要立即推播的「重大進展」

這個分層設計能讓平均每篇貼文每日 LLM 成本控制在 0.05 美元以內。

### 4.4 分級輪詢策略

為避免無謂的 API 呼叫成本，輪詢頻率隨追蹤時間衰減：

| 追蹤階段 | 輪詢頻率 | 適用情境 |
|---------|---------|---------|
| 加入後 0–24 小時 | 每 15 分鐘 | 爆紅高峰期，動態變化最快 |
| 加入後 1–7 天 | 每 1 小時 | 後續發酵期 |
| 加入後 7–30 天 | 每 6 小時 | 長尾觀察期 |
| 30 天無新動態 | 自動歸檔 | 釋放系統資源 |

使用者可透過 `/settings` 指令覆寫個別貼文的輪詢頻率。

### 4.5 Telegram Bot 互動設計

**主動推播觸發條件**：

- 原 PO 發布新貼文，且 LLM 判定與原事件相關
- 留言數於 1 小時內跨越預設閾值
- LLM 偵測到「事件重大進展」訊號（例如：原 PO 親自回覆、官方介入、事件結局揭曉）
- 每日固定時間（預設 21:00）推送當日所有追蹤貼文的彙整摘要

**指令清單**：

| 指令 | 功能 |
|------|------|
| `/track <連結>` | 加入新貼文到追蹤清單 |
| `/list` | 列出目前所有追蹤中的貼文 |
| `/untrack <id>` | 移除追蹤 |
| `/digest <id>` | 立即產生指定貼文的當下摘要 |
| `/timeline <id>` | 查看該貼文從加入追蹤至今的事件時間軸 |
| `/settings` | 調整個人推播偏好（閾值、頻率、靜音時段） |
| `/explore` | 瀏覽系統自動偵測到的熱點候選清單 |
| `/help` | 顯示說明 |

## 五、資料庫設計

### 主要資料表

```sql
-- 追蹤中的貼文
CREATE TABLE tracked_posts (
    id BIGSERIAL PRIMARY KEY,
    threads_post_id VARCHAR(64) UNIQUE NOT NULL,
    author_username VARCHAR(64) NOT NULL,
    post_url TEXT NOT NULL,
    original_content TEXT,
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    detection_source VARCHAR(16),  -- 'auto' or 'manual'
    status VARCHAR(16) DEFAULT 'active',  -- active / archived / removed
    polling_tier VARCHAR(16) DEFAULT 'hot',  -- hot / warm / cold
    last_polled_at TIMESTAMPTZ,
    metadata JSONB
);

-- 每次抓取的快照（用於成長率計算）
CREATE TABLE post_snapshots (
    id BIGSERIAL PRIMARY KEY,
    tracked_post_id BIGINT REFERENCES tracked_posts(id),
    captured_at TIMESTAMPTZ DEFAULT NOW(),
    like_count INT,
    reply_count INT,
    repost_count INT,
    new_replies JSONB  -- 該次新增的留言陣列
);

-- 後續相關貼文（原 PO 新發的、其他人引用的）
CREATE TABLE related_posts (
    id BIGSERIAL PRIMARY KEY,
    tracked_post_id BIGINT REFERENCES tracked_posts(id),
    threads_post_id VARCHAR(64) UNIQUE NOT NULL,
    relation_type VARCHAR(16),  -- 'author_followup' / 'quote' / 'discussion'
    relevance_score FLOAT,  -- LLM 判定的相關性 0–1
    content TEXT,
    posted_at TIMESTAMPTZ,
    discovered_at TIMESTAMPTZ DEFAULT NOW()
);

-- LLM 摘要快取
CREATE TABLE llm_summaries (
    id BIGSERIAL PRIMARY KEY,
    tracked_post_id BIGINT REFERENCES tracked_posts(id),
    summary_type VARCHAR(32),  -- 'evolution' / 'sentiment' / 'milestone'
    model VARCHAR(32),
    content TEXT,
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    input_tokens INT,
    output_tokens INT
);

-- Telegram 使用者
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    telegram_chat_id BIGINT UNIQUE NOT NULL,
    telegram_username VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    settings JSONB DEFAULT '{}'::jsonb
);

-- 訂閱關係
CREATE TABLE subscriptions (
    user_id BIGINT REFERENCES users(id),
    tracked_post_id BIGINT REFERENCES tracked_posts(id),
    subscribed_at TIMESTAMPTZ DEFAULT NOW(),
    notification_settings JSONB DEFAULT '{}'::jsonb,
    PRIMARY KEY (user_id, tracked_post_id)
);
```

### 索引設計

```sql
CREATE INDEX idx_snapshots_post_time ON post_snapshots(tracked_post_id, captured_at DESC);
CREATE INDEX idx_tracked_polling ON tracked_posts(polling_tier, last_polled_at) WHERE status = 'active';
CREATE INDEX idx_related_post ON related_posts(tracked_post_id, posted_at DESC);
```

## 六、開發時程（六週規劃）

### 第一週：可行性驗證（最關鍵階段）

- 註冊 Apify 帳號，研究 Threads Scraper actor 的 API
- 撰寫測試腳本，確認可以穩定取得：貼文內容、留言、時間戳、互動數、作者資訊
- 評估免費額度是否足以支撐專題 demo
- 若 Apify 不可行，測試備案：自寫爬蟲走 Threads 網頁端 GraphQL
- **此週完成後若資料來源無法取得，需立即調整專題方向**

### 第二週：資料層與排程

- 建立 PostgreSQL 資料庫，部署到 Railway
- 實作資料表與 ORM 層（SQLAlchemy）
- 實作 APScheduler 排程器與分級輪詢邏輯
- 純爬蟲存資料，不接 LLM 不接 Telegram

### 第三週：Telegram Bot 基礎

- 註冊 Bot、設定 webhook
- 實作核心指令：`/track`、`/list`、`/untrack`
- 實作使用者註冊與訂閱關係管理
- 此階段完成最小可用迴路：手動丟連結 → 系統追蹤 → 可查清單

### 第四週：LLM 摘要整合

- 接入 Anthropic API
- 實作 Haiku 層：留言情緒分類、相關性判定
- 實作 Opus 層：事件演進摘要、重大進展偵測
- 設計摘要快取機制避免重複呼叫
- 撰寫並驗證 Prompt（用 5–10 篇真實貼文做盲測）

### 第五週：爆紅偵測與推播

- 實作絕對門檻 + 相對速度的雙訊號偵測器
- 接入 Telegram 推播流程
- 實作每日彙整摘要（21:00 推送）
- 實作 `/explore` 指令瀏覽自動偵測候選

### 第六週：整合測試、優化、文件

- 端到端測試
- 效能調優（資料庫索引、API 呼叫批次化）
- 撰寫專題報告
- 製作 demo 影片
- 整理 GitHub README 與部署文件

## 七、成本估算

### 開發階段（一次性）

| 項目 | 費用 |
|------|------|
| Apify 訂閱（開發兩個月） | $0–$49 × 2 |
| Anthropic API 開發測試 | 約 $20 |
| Railway 部署 | 學生方案 $5/月 × 2 |
| 網域（選配） | $10/年 |

### 上線後（每月，假設 10 名使用者、追蹤 50 篇貼文）

| 項目 | 估算 |
|------|------|
| Apify API 呼叫 | $20–$30 |
| Anthropic API（Haiku + Opus） | $5–$10 |
| Railway 主機 + DB | $5 |
| **總計** | **約 $30–$45/月** |

每使用者月成本約 $3–$5，符合學生專題的可承擔範圍。

## 八、風險與應對

### 風險一：Threads API 政策變動

Meta 過去曾無預警關閉 Instagram 第三方資料 API。若 Apify 因此失效，備案是切換至自寫爬蟲（學術用途的合理使用範圍）或改用 X/Plurk 作為示範平台。

### 風險二：LLM 成本失控

若使用者活躍度高於預期，LLM 成本可能暴增。應對措施：摘要結果快取 24 小時、分級輪詢策略嚴格執行、設定每使用者每日 LLM 呼叫上限。

### 風險三：爆紅偵測誤判

雙訊號規則可能漏掉慢熱型貼文或誤判洗版內容。應對措施：保留手動補充模式作為主要互動路徑，自動偵測作為加值功能。專題報告中誠實說明偵測召回率與精確率。

### 風險四：合規與隱私

追蹤素人貼文涉及隱私議題。應對措施：僅追蹤公開貼文、不儲存使用者個資（僅儲存 Threads 公開可見資訊）、Telegram Bot 提供完整資料刪除功能、專題僅作學術展示不對外公開營運。

## 九、預期成果與評估指標

### 可交付成果

1. 完整可運作的 Telegram Bot，公開 demo 帳號
2. 系統原始碼（GitHub repository，含部署文件）
3. 專題書面報告（中文，約 30 頁）
4. 5 分鐘 demo 影片
5. 至少 3 個追蹤完整生命週期的真實案例分析

### 量化評估指標

- 系統穩定運行天數 ≥ 14 天
- 自動偵測召回率（recall）：對人工標記的爆紅貼文捕捉率 ≥ 60%
- LLM 摘要可讀性：使用者問卷平均分數 ≥ 4/5
- Telegram 推播相關性：使用者標記為「有用」的比例 ≥ 70%

### 質性評估

- 摘要是否真的能傳達「事件演進」而非單純資訊堆疊
- 系統是否能捕捉到至少一個「原 PO 後來發了續集」的完整案例
- 使用者是否願意持續使用（專題結束後仍主動 `/track` 新貼文）

## 十、未來延伸方向

1. **多平台支援**：擴充至 X、Plurk、Dcard
2. **跨平台事件聚合**：同一事件在不同平台的討論整合摘要
3. **使用者自訂偵測規則**：開放關鍵字訂閱、地理位置篩選
4. **LINE Bot / Discord Bot 介面**：擴大使用者觸及
5. **Web 介面**：提供事件演進的視覺化時間軸
6. **公共議題追蹤模式**：針對社會事件提供事實核查與多方觀點整合

## 附錄：關鍵技術文件參考

- Apify Threads Scraper: https://apify.com/apify/threads-scraper
- python-telegram-bot 官方文件: https://docs.python-telegram-bot.org
- Anthropic API 文件: https://docs.claude.com
- APScheduler 文件: https://apscheduler.readthedocs.io
- FastAPI 文件: https://fastapi.tiangolo.com
