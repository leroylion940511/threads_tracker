# Threads 素人爆文自動發現與後續追蹤系統 — 專題企劃書

## 一、專題動機與背景

Threads 自 2023 年推出後，已成為華語圈重要的短文社群平台。平台上經常出現**素人發布的貼文意外爆紅**——可能是一段感情糾紛、職場觀察、突發目擊、生活共鳴片段。這類內容的特質是強時效、強敘事、且後續發展高度依賴原 PO 主動更新。

讀者在當下被吸引，留言追問「後來呢？」「更新一下」，但若不持續回到該帳號頁面，極容易錯過後續。Threads 雖有追蹤功能，當追蹤對象增加，重要更新會被資訊流稀釋；更關鍵的是——**爆紅的素人貼文往往是讀者偶然滑到的，並不在原本的追蹤清單裡**。

本專題的核心構想是模擬「人在無限滑 Threads」的瀏覽行為，但加入演算法判斷：**只有當系統認為一則貼文具有後續追蹤價值時，才會深入分析該貼文，並將其加入長期追蹤池**。最終以 Telegram 作為使用者介面，採黑盒體驗——使用者只會看到系統判定有價值的內容。

這個設計把專題從「貼文監控工具」提升為「**自動化素人爆文發現引擎**」，研究價值與技術深度都更高。

## 二、專題目標

### 主要目標

1. 建立**自動化探索層**，模擬人類滑 Threads 的行為，持續產出候選貼文流
2. 設計**多階段評分演算法**，從大量候選中篩選出「值得追蹤」的素人爆文
3. 對通過篩選的貼文進行**深度抓取與長期追蹤**，包含原 PO 後續貼文、留言演進、相關討論
4. 運用 LLM 雙層架構，產出「事件演進敘事」式摘要
5. 透過 Telegram Bot 提供**黑盒推送體驗**——使用者只接收系統判定有價值的內容

### 次要目標

1. 探討「演算法判斷貼文價值」的可行性與量化評估方法
2. 評估第三方資料服務（Apify）與自建爬蟲在學術研究中的權衡
3. 建立可重現的素人爆文資料集，作為後續研究素材

### 範圍限定

本階段僅處理**繁體中文內容**，作者主要鎖定台灣使用者。語言限定有助於：聚焦評分模型的訓練、降低主題噪音、便於人工驗證系統判斷的準確性。

## 三、系統架構

### 整體架構：四階段漏斗

```
┌────────────────────────────────────────────────────────┐
│ 階段一：探索層 (Discovery)                              │
│ - 雙策略並行：關鍵字輪詢 + For You 流模擬              │
│ - 產出大量候選貼文 (每日數千篇)                        │
└──────────────────────┬─────────────────────────────────┘
                       ↓
┌────────────────────────────────────────────────────────┐
│ 階段二：評分層 (Scoring) — 三層快速篩選                │
│ - 第一層：硬規則 (互動速度、作者規模、語言檢測)        │
│ - 第二層：Haiku 語意判斷 (敘事完整性、後續潛力)        │
│ - 第三層：綜合分數加權                                  │
│ → 95% 以上的貼文在此被淘汰                              │
└──────────────────────┬─────────────────────────────────┘
                       ↓ 通過 (約 5%)
┌────────────────────────────────────────────────────────┐
│ 階段三：深挖層 (Deep Dive)                              │
│ - 完整留言串抓取                                        │
│ - 作者近期貼文脈絡分析                                  │
│ - Opus 產出初始事件摘要                                 │
│ - 加入長期追蹤池                                        │
└──────────────────────┬─────────────────────────────────┘
                       ↓
┌────────────────────────────────────────────────────────┐
│ 階段四：追蹤層 (Tracking)                               │
│ - 分級輪詢 (15min / 1hr / 6hr)                          │
│ - 三向監控：原 PO 新貼文 / 留言更新 / 引用討論         │
│ - 重大進展偵測                                          │
└──────────────────────┬─────────────────────────────────┘
                       ↓
┌────────────────────────────────────────────────────────┐
│ 階段五：推送層 (Delivery)                               │
│ - Telegram Bot 黑盒推送                                 │
│ - 每日彙整 + 即時重大進展                               │
└────────────────────────────────────────────────────────┘
```

### 技術選型

| 層級 | 技術 | 選用理由 |
|------|------|---------|
| 後端框架 | Python 3.11 + FastAPI | 非同步友善、生態成熟 |
| 資料庫 | PostgreSQL 15 | JSONB 彈性 + 時序查詢效能 |
| 排程 | APScheduler | 輕量，不需 Celery + Redis |
| 主資料來源 | Apify Threads Scraper | 文件齊全、合規責任轉移 |
| 備案資料來源 | 自建 Playwright 爬蟲 | For You 流模擬、Apify 失效時備援 |
| LLM | Claude Haiku 4.5 + Opus 4.7 | 雙層架構平衡成本品質 |
| 通知介面 | python-telegram-bot | Telegram Bot 主流 SDK |
| 部署 | Docker + Railway | 學生方案便宜 |

## 四、核心功能設計

### 4.1 探索層：雙策略並行

#### 策略 A：關鍵字輪詢（主力，學術正當性高）

爆紅素人貼文的語言特徵高度集中。觀察台灣 Threads 上的爆文，常見「觸發詞」包括：

- **後續暗示型**：後來、更新一下、求後續、第二集、有人想知道
- **求助/共鳴型**：有人也、正常嗎、求解、是我的問題嗎、靠北
- **事件性型**：剛剛、目擊、現場、突然、嚇到
- **敘事開頭型**：分享一下、我朋友、我同事、我前男友、我們公司
- **情緒爆發型**：氣死、傻眼、無語、太扯、笑死

維護一份 30–50 個關鍵字的種子池，**每 30 分鐘輪詢一輪**，每個關鍵字抓取 20–50 篇最新貼文。預估每日產出 3000–5000 篇候選貼文進入評分層。

優點：可控、可重現、不需登入、學術上能清楚說明資料來源。

#### 策略 B：For You 流模擬（探索性）

使用 Playwright 自動化瀏覽器，登入備用 Threads 帳號，模擬滾動 For You 推薦流，持續記錄出現的貼文。

優點：更接近真實使用者經驗、能捕捉到關鍵字策略漏掉的內容。

缺點：需要登入帳號（可能被風控）、結果不可重現（推薦演算法個人化）、技術風險高、需要應對 Meta 的反爬蟲機制。

**處理方式**：本專題將 For You 流作為**探索性實驗**，主要為了與策略 A 做對照研究——比較兩種探索方式產出候選的差異，作為專題的研究貢獻之一。即便 For You 模擬最終效果不佳，這個對照本身就是有價值的觀察。

### 4.2 評分層：三層篩選

#### 第一層：硬規則（規則引擎，毫秒級）

對每篇候選貼文計算以下特徵：

| 特徵 | 篩選邏輯 |
|------|---------|
| 互動速度 | (likes + replies × 2) / 發文小時數 |
| 作者規模 | 粉絲數 < 5000 視為素人加分 |
| 內容長度 | 文字 30–500 字之間（過短缺乏敘事、過長轉發感重） |
| 語言檢測 | 必須為繁體中文 |
| 媒體屬性 | 純文字或單張圖片優先 |
| 黑名單 | 業配關鍵字、廣告連結直接淘汰 |

**通過標準**：互動速度 > 30 且 作者粉絲 < 10000 且 語言為繁中。預估通過率 10–15%。

#### 第二層：Haiku 語意判斷（每篇成本 < $0.001）

對通過第一層的貼文呼叫 Haiku，使用結構化輸出判斷：

```
任務：判斷這則貼文是否值得長期追蹤後續發展。

請評估以下面向，每項給 0–1 分：
1. 敘事未完性：是否暗示故事還沒結束？
2. 事件性：是否在描述一個進行中的具體事件？
3. 情緒張力：是否包含強烈情緒或衝突？
4. 後續可能：原 PO 是否可能會發後續更新？
5. 共鳴度：留言是否會出現「後來呢」類追問？

輸出 JSON：
{
  "narrative_open": 0.8,
  "event_concrete": 0.6,
  "emotion_intensity": 0.9,
  "followup_likely": 0.7,
  "resonance": 0.8,
  "verdict": "track" | "skip",
  "reason": "簡短理由"
}
```

**通過標準**：verdict = "track" 且 五項平均 > 0.6。預估通過率 30–40%。

#### 第三層：綜合分數加權

將硬規則分數與語意分數加權合併：

```
final_score = 0.4 × interaction_velocity_normalized 
            + 0.3 × semantic_score 
            + 0.2 × author_grassroots_score 
            + 0.1 × novelty_score
```

每小時取分數最高的 Top N（初期 N=5）進入深挖層。這樣可以**控制深挖層的吞吐量**，避免成本失控。

### 4.3 深挖層

對每篇通過評分的貼文執行：

1. 抓取完整留言串（最多 200 則）
2. 抓取作者近 30 篇貼文，建立作者敘事脈絡
3. 呼叫 Opus 產出**初始事件摘要**：包含「事件主體 / 當前狀態 / 待解問題 / 預期後續方向」
4. 寫入長期追蹤池，標記初始狀態

### 4.4 追蹤層：分級輪詢

| 階段 | 頻率 | 抓取範圍 |
|------|------|---------|
| 入池後 0–24 小時 | 每 15 分鐘 | 留言、作者新貼文 |
| 入池後 1–7 天 | 每 1 小時 | 全項目 |
| 入池後 7–30 天 | 每 6 小時 | 全項目 |
| 30 天無新動態 | 自動歸檔 | — |

**重大進展偵測**：每次輪詢後，若有新留言或新貼文，呼叫 Haiku 判斷「是否構成事件重大進展」。若是，呼叫 Opus 更新事件摘要並觸發推播。

### 4.5 推送層：Telegram 黑盒體驗

使用者**不會看到候選池、不會看到評分過程**，只會收到系統判定有價值的內容。這個設計符合「自動化推薦」的產品定位，也讓系統可以較大膽地過濾。

**推送觸發條件**：

- 新貼文進入長期追蹤池（每篇推送一次「發現新事件」）
- 已追蹤事件偵測到重大進展
- 每日 21:00 推送當日彙整

**訊息格式範例**：

```
🔥 新事件發現

「公司新主管第一天就出包」
作者：@xxx | 發文 3 小時 | 1.2k 讚 | 340 留言

[Haiku 自動分類]
類型：職場 / 主管問題
情緒：氣憤、無奈
追蹤價值分數：0.84

[Opus 摘要]
原 PO 描述新主管第一天就要求全組加班開會討論「為何業績不佳」，
但她到職僅一週尚未交接完成。留言區出現大量類似經驗共鳴，
也有讀者追問後續是否提離職。

[追蹤狀態] 已加入追蹤池，後續更新會自動推送
```

**指令清單**（黑盒模式下指令較精簡）：

| 指令 | 功能 |
|------|------|
| `/feed` | 查看最近推送過的事件清單 |
| `/timeline <id>` | 查看單一事件的時間軸 |
| `/digest` | 立即取得今日彙整 |
| `/mute <id>` | 對單一事件取消後續推播 |
| `/settings` | 調整推播時段、頻率 |
| `/stats` | 查看系統統計（探索量、通過率、追蹤中數量）|

## 五、資料庫設計

```sql
-- 探索層產出的所有候選貼文（不論是否通過）
CREATE TABLE candidate_posts (
    id BIGSERIAL PRIMARY KEY,
    threads_post_id VARCHAR(64) UNIQUE NOT NULL,
    author_username VARCHAR(64),
    author_follower_count INT,
    content TEXT,
    posted_at TIMESTAMPTZ,
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    discovery_source VARCHAR(32),  -- 'keyword:<seed>' / 'foryou_simulator'
    initial_likes INT,
    initial_replies INT,
    metadata JSONB
);

-- 評分結果（每階段一筆紀錄，用於後續分析評分演算法）
CREATE TABLE scoring_records (
    id BIGSERIAL PRIMARY KEY,
    candidate_post_id BIGINT REFERENCES candidate_posts(id),
    stage VARCHAR(16),  -- 'rules' / 'haiku' / 'final'
    passed BOOLEAN,
    score FLOAT,
    details JSONB,  -- 各項子分數
    scored_at TIMESTAMPTZ DEFAULT NOW(),
    cost_usd NUMERIC(10, 6)
);

-- 進入追蹤池的貼文
CREATE TABLE tracked_posts (
    id BIGSERIAL PRIMARY KEY,
    candidate_post_id BIGINT REFERENCES candidate_posts(id),
    promoted_at TIMESTAMPTZ DEFAULT NOW(),
    polling_tier VARCHAR(16) DEFAULT 'hot',
    last_polled_at TIMESTAMPTZ,
    status VARCHAR(16) DEFAULT 'active',
    initial_summary TEXT,
    current_summary TEXT
);

-- 快照（時序資料）
CREATE TABLE post_snapshots (
    id BIGSERIAL PRIMARY KEY,
    tracked_post_id BIGINT REFERENCES tracked_posts(id),
    captured_at TIMESTAMPTZ DEFAULT NOW(),
    like_count INT,
    reply_count INT,
    repost_count INT,
    new_replies JSONB
);

-- 後續相關貼文
CREATE TABLE related_posts (
    id BIGSERIAL PRIMARY KEY,
    tracked_post_id BIGINT REFERENCES tracked_posts(id),
    threads_post_id VARCHAR(64) UNIQUE,
    relation_type VARCHAR(16),  -- 'author_followup' / 'quote' / 'discussion'
    relevance_score FLOAT,
    content TEXT,
    posted_at TIMESTAMPTZ,
    discovered_at TIMESTAMPTZ DEFAULT NOW()
);

-- LLM 摘要與決策日誌
CREATE TABLE llm_records (
    id BIGSERIAL PRIMARY KEY,
    tracked_post_id BIGINT REFERENCES tracked_posts(id),
    purpose VARCHAR(32),  -- 'initial_summary' / 'milestone_check' / 'evolution_update'
    model VARCHAR(32),
    input_tokens INT,
    output_tokens INT,
    cost_usd NUMERIC(10, 6),
    content TEXT,
    generated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 探索層的關鍵字種子池
CREATE TABLE keyword_seeds (
    id SERIAL PRIMARY KEY,
    keyword VARCHAR(64) UNIQUE,
    category VARCHAR(32),  -- 'followup' / 'help' / 'event' / 'narrative' / 'emotion'
    enabled BOOLEAN DEFAULT TRUE,
    last_polled_at TIMESTAMPTZ,
    total_candidates_yielded INT DEFAULT 0,
    total_promoted INT DEFAULT 0  -- 通過評分進入追蹤的數量（衡量種子品質）
);

-- 推播紀錄
CREATE TABLE notifications (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    tracked_post_id BIGINT REFERENCES tracked_posts(id),
    notification_type VARCHAR(32),  -- 'discovery' / 'milestone' / 'daily_digest'
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    user_feedback VARCHAR(16)  -- 'useful' / 'not_useful' / null
);
```

## 六、演算法評估方法

這是本專題作為學術研究的關鍵章節。

### 評估資料集建立

從系統運行第二週起，每週**人工標記 200 篇候選貼文**，標記欄位包含：

- 是否為素人貼文
- 是否為爆紅候選
- 是否有後續追蹤價值
- 14 天後是否真的有後續發展

形成 ground truth 資料集，用於評估評分演算法。

### 量化指標

| 指標 | 定義 | 目標值 |
|------|------|--------|
| 召回率 (Recall) | 真正爆紅貼文中被系統捕捉到的比例 | ≥ 60% |
| 精確率 (Precision) | 系統推送的貼文中被使用者標記為有用的比例 | ≥ 70% |
| 後續命中率 | 加入追蹤池的貼文中，真的有後續發展的比例 | ≥ 50% |
| 探索效率 | 每 1000 篇候選 → 進入追蹤池的數量 | 30–80 |

### 對照實驗

比較三種探索策略的效果：

1. 純關鍵字輪詢
2. 純 For You 模擬
3. 兩者並行 + 去重

針對同一週的真實爆紅貼文（事後人工確認），比較三種策略各自的召回率。這個對照可以作為專題的核心研究貢獻。

## 七、開發時程（八週規劃）

新架構比原本複雜，從六週調整為八週。

### 第一週：可行性驗證（最關鍵）

- 註冊 Apify，測試 `automation-lab/threads-scraper` 的 search 模式
- 確認能否用關鍵字穩定取得貼文流，評估免費額度消耗速度
- 並行測試 Playwright 登入 Threads 模擬滑動的可行性
- **若兩個方案都失敗，需立即調整專題範圍**

### 第二週：探索層 + 資料庫

- PostgreSQL 部署
- 實作關鍵字輪詢排程（每 30 分鐘）
- 建立關鍵字種子池（先以 30 個觸發詞起步）
- 純記錄候選貼文，不做評分

### 第三週：評分層

- 實作硬規則篩選器
- 接入 Haiku 做語意判斷
- 撰寫並驗證 Prompt（用第二週累積的真實貼文做盲測）
- 實作綜合分數加權邏輯

### 第四週：深挖層 + 追蹤層

- 通過評分的貼文進入深挖流程
- 實作分級輪詢策略
- Opus 初始摘要產出
- 重大進展偵測邏輯

### 第五週：Telegram Bot 與推送

- 實作黑盒推送流程
- 實作核心指令 `/feed`、`/timeline`、`/digest`、`/mute`
- 訊息格式優化

### 第六週：For You 流模擬實驗

- Playwright 環境建置
- 自動滾動與貼文擷取邏輯
- 與關鍵字策略做對照分析
- 即便效果不佳也要保留作為研究觀察

### 第七週：評估與調優

- 建立人工標記資料集
- 計算召回率、精確率
- 調整評分閾值與關鍵字種子池
- Prompt 優化

### 第八週：報告與 Demo

- 撰寫專題報告
- 製作 demo 影片
- 整理 GitHub 文件
- 準備口頭簡報

## 八、成本估算

### 每日成本估算（穩定運行階段）

假設每日探索 4000 篇候選貼文：

| 項目 | 計算 | 成本 |
|------|------|------|
| Apify 探索層 | 4000 篇 × $0.003 | $12 |
| Apify 深挖層 | 200 篇 × $0.01（含留言） | $2 |
| Apify 追蹤層 | 50 篇 × 8 次/日 × $0.005 | $2 |
| Haiku 評分 | 600 篇 × $0.001 | $0.6 |
| Opus 摘要 | 20 篇 × $0.05 | $1 |
| **每日總計** | | **約 $17.6** |
| **每月總計** | | **約 $530** |

這個成本對學生專題太高，需要**控制策略**：

1. 探索頻率從每 30 分鐘降為每 60 分鐘 → 成本減半
2. 關鍵字種子精簡為 15 個高品質觸發詞
3. 硬規則加嚴，減少進入 Haiku 的數量
4. Opus 摘要僅在重大進展時呼叫

優化後預估每月 $80–$120，搭配 Anthropic 學生額度與 Apify 免費額度，實質支出可壓在每月 $30 以內。

### 成本控制機制

設定每日上限熔斷：當 Apify 或 LLM 成本超過預設值，系統自動降頻或暫停探索層，避免突發成本。

## 九、風險與應對

### 風險一：Threads 公開搜尋限制

Threads 在 2025 年底開始要求 cookie 認證才能使用搜尋功能。應對措施：

- 主力使用支援 cookie 認證的 Apify Actor
- 維護備用 Threads 帳號專供 cookie 取用
- 若情況惡化，切換為「追蹤已知素人帳號清單」的退化模式

### 風險二：For You 流模擬失敗

Meta 可能偵測到自動化行為並封號。應對措施：

- 使用備用帳號，不影響主帳號
- 加入隨機延遲、滾動模式擬真
- 若失敗，誠實寫進報告作為「失敗的探索性嘗試」，仍有研究價值

### 風險三：評分演算法準確度不足

Haiku 判斷可能與人類直覺不一致。應對措施：

- 持續收集人工標記資料 fine-tune Prompt
- 提供使用者 feedback 機制（推播訊息附「有用 / 沒用」按鈕），形成迭代閉環
- 報告中誠實呈現混淆矩陣

### 風險四：成本失控

突發熱點可能讓深挖層被洗版。應對措施：

- 每日成本上限熔斷
- 深挖層每小時 Top N 限制
- 監控儀表板即時觀察成本

### 風險五：合規與隱私

追蹤素人貼文涉及隱私議題。應對措施：

- 僅處理公開貼文
- 不在公開報告或 demo 中展示真實使用者帳號（人工去識別化）
- 提供使用者完整資料刪除指令
- 專題僅作學術展示，不對外公開營運
- 報告中專章討論社群媒體研究的倫理議題

## 十、預期成果

### 可交付項目

1. 完整可運作的探索 + 追蹤系統，公開 Telegram demo Bot
2. 系統原始碼（GitHub repository）
3. 專題書面報告（中文，約 40 頁，含演算法評估章節）
4. 5 分鐘 demo 影片
5. **人工標記的素人爆文資料集**（去識別化版本，作為學術貢獻釋出）
6. 至少 3 個從發現到完整生命週期的真實事件案例分析
7. 兩種探索策略的對照研究結果

### 質性評估

- 系統是否能在使用者**不主動丟連結**的情況下，自主發現有價值的爆文
- 黑盒推送的內容是否讓使用者覺得「比自己滑 Threads 高效」
- 是否能捕捉到至少一個「演算法搶在大眾爆紅之前發現」的早期案例
- For You 模擬與關鍵字策略的差異是否具有研究啟發

## 十一、未來延伸方向

1. **多平台擴充**：X、Plurk、Dcard
2. **跨平台事件聚合**
3. **使用者個人化權重**：透過 feedback 學習使用者偏好
4. **公共議題追蹤模式**
5. **Web 介面**：視覺化事件演進時間軸
6. **將標記資料集釋出為開源研究資源**

## 附錄：關鍵技術文件參考

- Apify Threads Scraper: https://apify.com/automation-lab/threads-scraper
- Playwright Python: https://playwright.dev/python/
- python-telegram-bot: https://docs.python-telegram-bot.org
- Anthropic API: https://docs.claude.com
- APScheduler: https://apscheduler.readthedocs.io
- FastAPI: https://fastapi.tiangolo.com
