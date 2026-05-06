# Threads 素人爆文發現、追蹤與問答系統 — 專題企劃書 v3

> **v3 與 v2 的核心差異**
> v2 是純黑盒推薦：使用者只接收，不參與。
> v3 改為**半黑盒 + 三段互動**：系統推薦 → 使用者選擇收藏 → 收藏後系統追蹤後續 + 使用者可隨時對該事件做 LLM 問答。
> v3 砍掉 v2 的「For You 流模擬」探索性實驗，集中資源在「關鍵字探索 + 評分 + 收藏追蹤 + 問答」這條主線。

---

## 一、專題動機與背景

Threads 上每天都有素人貼文意外爆紅。讀者當下被吸引、留言追問「後來呢？」，但因為這類貼文不在原本追蹤清單內，極容易錯過後續發展。

v2 提出「自動化爆文發現引擎」純黑盒推送模型，但忽略了一個關鍵：**使用者的判斷比演算法準**。系統可以做粗篩，但「這篇我有興趣，幫我盯著」這個決定應該交給人。一旦使用者收藏，系統就有了明確的追蹤目標——這也是後續推送與問答能夠精準的前提。

v3 由此重新定位為「**素人爆文發現 + 收藏追蹤 + 對話式問答**」三段式系統。它不取代使用者滑 Threads 的習慣，而是補上兩個現有平台缺失的環節：(1) 把可能爆紅的素人貼文集中送到使用者眼前；(2) 對被收藏的事件做長期追蹤與隨時問答。

## 二、專題目標

### 主要目標

1. 建立**自動化探索 + 評分流水線**，每日從繁中 Threads 產出 Top 5 候選清單
2. 透過 Telegram Bot **每日定時推送**，使用者以 inline button 三選一（❤️ 收藏 / 👎 不感興趣 / 🔕 靜音）
3. 對使用者收藏的貼文進入**長期追蹤池**，自動偵測後續發展（原 PO 更新、後續貼文、有價值留言、引用討論）並推播
4. 提供 `/ask <id>` **對話式問答模式**，使用者可對單一事件做多輪 LLM 問答

### 次要目標

1. 探討「演算法判斷貼文價值」與「使用者收藏行為」的相關性（精確率指標）
2. 評估在重量級 context 下，LLM 對素人事件的問答品質
3. 建立可重現的素人爆文資料集（去識別化）

### 範圍限定

- 僅處理**繁體中文 / 台灣使用者**內容
- 使用者規模：個位數，所有人共用同一份每日推送清單，**不做個人化**
- 不啟用 For You 流模擬（與 v2 主要差異）

## 三、系統架構

### 整體架構：發現流水線 + 收藏追蹤雙環

```
[每日推送主環]                              [收藏追蹤副環]
                                            
┌─────────────────┐                         ┌──────────────────┐
│ ① 探索層         │                         │ ⑤ 收藏池          │
│ 關鍵字輪詢       │                         │ (使用者 ❤️ 後)    │
│ 每 60 分鐘       │                         └────────┬─────────┘
└────────┬────────┘                                  ↓
         ↓                                  ┌──────────────────┐
┌─────────────────┐                         │ ⑥ 追蹤層          │
│ ② 評分層         │                         │ 分級輪詢          │
│ 硬規則 → Haiku  │                         │ 15min/1h/6h      │
│ → 加權分數       │                         │ 抓四類後續事件    │
└────────┬────────┘                         └────────┬─────────┘
         ↓                                           ↓
┌─────────────────┐                         ┌──────────────────┐
│ ③ 候選排程層     │                         │ ⑦ 後續推送        │
│ 每日 09:00 取    │                         │ 有後續即推 / 整合 │
│ Top 5            │                         │ 至每日彙整        │
│ (3 已爆+2 早期)  │                         └──────────────────┘
└────────┬────────┘                                  ↑
         ↓                                           │
┌─────────────────┐                         ┌──────────────────┐
│ ④ 推送層         │                         │ ⑧ 問答層          │
│ Telegram +       │ ──────❤️ 收藏─────────→ │ /ask <id>        │
│ inline button    │                         │ 重量 context     │
│ + 即時破例推送   │                         │ 多輪對話 /exit   │
└─────────────────┘                         └──────────────────┘
```

### 技術選型

| 層級 | 技術 | 選用理由 |
|------|------|---------|
| 後端框架 | Python 3.11 + FastAPI | 沿用 v1 baseline |
| 資料庫 | SQLite (dev) / PostgreSQL (prod) | 個位數使用者初期 SQLite 即可 |
| 排程 | APScheduler | 已驗證可行 |
| 主資料來源 | Apify Threads Scraper | 文件齊、合規責任轉移 |
| LLM 評分 | Claude Haiku 4.5 | 低成本快速判斷 |
| LLM 摘要 + 問答 | Claude Opus 4.7 | 重量 context 需強推理 |
| 通知介面 | python-telegram-bot | 已驗證可行 |
| 部署 | Docker + Railway / 本地 | 個位數使用者本地跑也夠 |

## 四、核心功能設計

### 4.1 探索層：純關鍵字輪詢

砍掉 v2 的 For You 流模擬。**單一策略**：維護 30–50 個觸發詞種子池，每 60 分鐘輪詢一輪，每個關鍵字抓最新 20–50 篇貼文。

關鍵字分類同 v2：後續暗示型 / 求助共鳴型 / 事件性 / 敘事開頭 / 情緒爆發。種子池與其產出量、命中率記錄在 `keyword_seeds`，可作為評估指標。

預估每日候選量：1500–3000 篇（v2 是 3000–5000，這裡降頻一倍以控成本）。

### 4.2 評分層：三層篩選

完全延用 v2 設計，但**閾值調嚴**以對應降頻後的容量。

**第一層 硬規則**：互動速度 > 30、作者粉絲 < 10000、繁中、文字 30–500 字、非業配。預估通過率 10%。

**第二層 Haiku 語意判斷**：五項評分 + verdict（track / skip）。預估通過率 30%。

**第三層 綜合分數**：
```
final_score = 0.4 × interaction_velocity_normalized
            + 0.3 × semantic_score
            + 0.2 × author_grassroots_score
            + 0.1 × novelty_score
```

每小時取 Top N（N=10）寫入候選池，等候每日 09:00 排程選取。

### 4.3 候選排程層：每日 Top 5 = 3 已爆 + 2 早期

每日 09:00 從過去 24 小時的候選池中挑 5 篇，**固定配比**：

| 類型 | 數量 | 條件 |
|------|------|------|
| 已爆 | 3 | 互動速度排名前 3，且發文時間 ≥ 6 小時 |
| 早期 | 2 | 發文時間 < 3 小時，semantic_score 排名前 2 |

「已爆」命中率高、回饋快；「早期」獨特性高，是專題的研究亮點（能否搶在大眾爆紅前發現）。比例與時間閾值寫進 config，可調。

#### 即時破例推送

**觸發條件**：候選池中出現「發文 1 小時內互動速度排名 Top 1% 且 Haiku verdict=track 且 semantic_score > 0.85」的貼文，立即推送，不等 09:00。

每日破例上限 2 則，避免洗版。

### 4.4 推送層：每日 09:00 + inline button

**訊息格式**：

```
🔥 今日推薦 (3/5)

「公司新主管第一天就出包」
作者：@xxx | 發文 3 小時 | 1.2k 讚 | 340 留言
類型：職場 | 情緒：氣憤、無奈 | 分數：0.84

[Opus 摘要 80–120 字]
原 PO 描述新主管要求全組加班...

[ ❤️ 收藏 ]  [ 👎 不感興趣 ]  [ 🔕 靜音 ]
```

按鈕語意：

| 按鈕 | 動作 |
|------|------|
| ❤️ 收藏 | 寫入 `collections`，進入長期追蹤池 |
| 👎 不感興趣 | 寫入 `feedback`，作為日後個人化權重訓練資料；本次不再顯示 |
| 🔕 靜音 | 等同 👎 + 標記該作者後續貼文降權 |

**指令**：

| 指令 | 功能 |
|------|------|
| `/feed` | 重看最近 7 天推送過的清單 |
| `/saved` | 列出我收藏的事件 |
| `/timeline <id>` | 看單一事件的時間軸 |
| `/ask <id>` | 進入問答模式 |
| `/exit` | 離開問答模式 |
| `/digest` | 立即拉今日彙整 |
| `/settings` | 調推播時間 / 是否接收破例推送 |

### 4.5 收藏與追蹤層

使用者點 ❤️ 後，候選貼文升格進入 `tracked_posts`，啟動分級輪詢。

#### 分級輪詢

| 階段 | 頻率 | 抓取項目 |
|------|------|---------|
| 收藏後 0–24h | 每 15 分鐘 | 留言、作者新貼文 |
| 收藏後 1–7 天 | 每 1 小時 | 全項目 |
| 收藏後 7–30 天 | 每 6 小時 | 全項目 |
| 30 天無新動態 | 自動歸檔 | — |

#### 後續事件四類

每次輪詢比對前一次快照，偵測：

1. **作者後續貼文**（`author_followup`）：原 PO 在追蹤期間的新貼文，由 Haiku 判斷是否與原事件相關
2. **作者更新留言**（`author_reply`）：原 PO 在自己貼文下的新留言
3. **有價值留言**（`hot_reply`）：按讚數 / 回覆數突破閾值的他人留言
4. **引用討論**（`quote`）：搜尋 Threads 對該貼文的引用 / quote

每類偵測到都寫入 `related_posts`，並由 Haiku 判斷「是否構成事件重大進展」。

#### 後續推送

預設**整合至每日彙整**（追加在當日 5 篇推薦之後，標題改為「📌 你收藏的事件有更新」）。

例外：Haiku 判定「重大進展」（例如當事人現身、結局揭曉）→ 即時推送。

### 4.6 問答層：對話模式

使用者輸入 `/ask <id>` 進入該事件的問答模式，後續所有訊息都被視為對該事件的提問，直到使用者輸入 `/exit`。

#### Context 範圍（預設：重量）

問答模式啟動時，系統把以下內容組合成 system prompt 餵給 Opus：

| 區塊 | 內容 | 估計 token |
|------|------|-----------|
| 原貼文 | 標題 + 全文 + metadata | ~500 |
| 系統摘要 | 最新 `EvolutionSummary`（事件主體、當前狀態、待解問題、預期後續） | ~600 |
| 全部留言 | 截至此刻所有抓到的留言全文，按時序 | 5k–20k |
| 作者背景 | 作者近 30 篇貼文 + 粉絲數 | 2k–5k |
| 後續事件 | `related_posts` 全部 | 1k–10k |

預估每次 `/ask` 開場 8k–35k input tokens，後續每輪追問 +500 output。Opus 4.7 cache hit 後實際支出可控。

**保留輕量 / 中量模式作為旗標**（日後加）：`/ask <id> --light <問題>` 只給原文 + 摘要。

#### 對話狀態管理

- 每個使用者同時只能進入一個事件的問答模式
- `/exit` 或 5 分鐘無訊息自動結束
- 對話歷史寫入 `qa_sessions` 與 `qa_messages`，供日後分析使用者問什麼類型的問題（即評估方法的問題類型分布資料源）

#### 問題類型（預期）

事件結論型 / 輿情整理型 / 人物背景型 / 跨貼文連結型 / 細節考據型。實際分布由 `qa_messages` 統計後寫進報告。

## 五、資料庫設計

```sql
-- 探索層產出
CREATE TABLE candidate_posts (
    id BIGSERIAL PRIMARY KEY,
    threads_post_id VARCHAR(64) UNIQUE NOT NULL,
    author_username VARCHAR(64),
    author_follower_count INT,
    content TEXT,
    posted_at TIMESTAMPTZ,
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    discovery_source VARCHAR(64),  -- 'keyword:<seed>'
    initial_likes INT,
    initial_replies INT,
    metadata JSONB
);

-- 評分結果
CREATE TABLE scoring_records (
    id BIGSERIAL PRIMARY KEY,
    candidate_post_id BIGINT REFERENCES candidate_posts(id),
    stage VARCHAR(16),  -- 'rules' / 'haiku' / 'final'
    passed BOOLEAN,
    score FLOAT,
    details JSONB,
    scored_at TIMESTAMPTZ DEFAULT NOW(),
    cost_usd NUMERIC(10, 6)
);

-- 每日推送清單
CREATE TABLE daily_pushes (
    id BIGSERIAL PRIMARY KEY,
    push_date DATE,
    candidate_post_id BIGINT REFERENCES candidate_posts(id),
    push_type VARCHAR(16),  -- 'already_hot' / 'early_bet' / 'breaking'
    rank INT,
    pushed_at TIMESTAMPTZ
);

-- 使用者反饋（按鈕）
CREATE TABLE feedback (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    candidate_post_id BIGINT REFERENCES candidate_posts(id),
    action VARCHAR(16),  -- 'collect' / 'dislike' / 'mute_event'
    acted_at TIMESTAMPTZ DEFAULT NOW()
);

-- 收藏池（升格的追蹤池）
CREATE TABLE tracked_posts (
    id BIGSERIAL PRIMARY KEY,
    candidate_post_id BIGINT REFERENCES candidate_posts(id),
    user_id BIGINT,
    promoted_at TIMESTAMPTZ DEFAULT NOW(),
    polling_tier VARCHAR(16) DEFAULT 'hot',
    last_polled_at TIMESTAMPTZ,
    status VARCHAR(16) DEFAULT 'active',  -- 'active' / 'muted' / 'archived'
    initial_summary TEXT
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

-- 後續事件（四類）
CREATE TABLE related_posts (
    id BIGSERIAL PRIMARY KEY,
    tracked_post_id BIGINT REFERENCES tracked_posts(id),
    threads_post_id VARCHAR(64) UNIQUE,
    relation_type VARCHAR(16),  -- 'author_followup' / 'author_reply' / 'hot_reply' / 'quote'
    relevance_score FLOAT,
    is_milestone BOOLEAN DEFAULT FALSE,  -- Haiku 判定的重大進展
    content TEXT,
    posted_at TIMESTAMPTZ,
    discovered_at TIMESTAMPTZ DEFAULT NOW()
);

-- LLM 紀錄（評分、摘要、問答全部寫這）
CREATE TABLE llm_records (
    id BIGSERIAL PRIMARY KEY,
    purpose VARCHAR(32),  -- 'scoring' / 'initial_summary' / 'evolution' / 'milestone_check' / 'qa'
    related_id BIGINT,    -- candidate_post_id 或 tracked_post_id 或 qa_session_id
    model VARCHAR(32),
    input_tokens INT,
    output_tokens INT,
    cost_usd NUMERIC(10, 6),
    content TEXT,
    generated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 問答 session
CREATE TABLE qa_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    tracked_post_id BIGINT REFERENCES tracked_posts(id),
    context_mode VARCHAR(16) DEFAULT 'heavy',  -- 'light' / 'medium' / 'heavy'
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    end_reason VARCHAR(16)  -- 'exit' / 'timeout'
);

CREATE TABLE qa_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT REFERENCES qa_sessions(id),
    role VARCHAR(16),  -- 'user' / 'assistant'
    content TEXT,
    question_type VARCHAR(32),  -- 事後由分析腳本標記
    sent_at TIMESTAMPTZ DEFAULT NOW()
);

-- 關鍵字種子池
CREATE TABLE keyword_seeds (
    id SERIAL PRIMARY KEY,
    keyword VARCHAR(64) UNIQUE,
    category VARCHAR(32),
    enabled BOOLEAN DEFAULT TRUE,
    last_polled_at TIMESTAMPTZ,
    total_candidates_yielded INT DEFAULT 0,
    total_promoted INT DEFAULT 0,
    total_collected INT DEFAULT 0  -- 真的被使用者 ❤️ 收藏的數量
);
```

## 六、演算法評估方法（大學專題層級）

v2 規劃了完整的人工標記資料集 + 三策略對照實驗。v3 是大學專題層級，**簡化為兩個量化指標 + 一個質性章節**。

### 6.1 量化指標

| 指標 | 定義 | 目標值 |
|------|------|--------|
| 收藏率 (Collection Rate) | 推送的貼文中被使用者 ❤️ 的比例 | ≥ 30% |
| 後續命中率 | 收藏的事件在 30 天內偵測到至少 1 個有效後續 (relation_type ≠ null) 的比例 | ≥ 50% |

評估期：系統穩定運行後第 4–8 週，由實際使用者按鈕資料直接統計。

### 6.2 質性章節

報告中針對 3–5 個從推送 → 收藏 → 完整生命週期的真實案例做敘事分析，重點：

- 系統推送時的評分依據
- 使用者收藏時點與當下事件狀態
- 後續發展是否符合系統預期
- 問答 session 中使用者問了什麼、Opus 答對了多少

### 6.3 問答品質評估

從問答記錄中抽 30 組 (問題, 回答) pair，研究者**自評**：

- 事實正確性（0–1）
- 引用 context 的精準度（0–1）
- 是否有幻覺

不做大規模對照實驗。

## 七、開發里程碑

依任務依賴排序，不綁週數。每個里程碑「完成判準」達標後才進下一個。任務級拆解見 `SCHEDULE.md`。

| 里程碑 | 主題 | 前置 | 主要產出 |
|--------|------|------|---------|
| M1 | Apify 可行性驗證 | — | 拿到 token、跑通關鍵字 search 模式、確認免費額度消耗速度 |
| M2 | 探索層 + DB 重構 | M1 GO | 建立新 schema、關鍵字種子池、每 60 分鐘輪詢、純記錄候選 |
| M3 | 評分層 | M2 累積 ≥ 200 筆 candidate | 硬規則 + Haiku + 加權；用 M2 資料盲測 prompt |
| M4 | 候選排程層 + 推送層 | M3 final_score 可算 | 每日 09:00 Top 5、inline button、即時破例推送 |
| M5 | 收藏追蹤層 | M4 ❤️ 能寫 feedback | 升格邏輯、分級輪詢、四類後續事件偵測 |
| M6 | 問答層 | M5 有追蹤資料 | `/ask` 對話模式、重量 context 組裝、`/exit` 與 timeout |
| M7 | 評估資料蒐集 + 調優 | M6 流水線完整 + 累積 7 天資料 | 收藏率、後續命中率統計；prompt / 閾值調整 |
| M8 | 報告與 demo | M7 評估數據完整 | 撰寫報告、3–5 個案例分析、demo 影片 |

M1 仍是最關鍵的里程碑——沒拿到 Apify token 之前，後面全是空轉。M1 結束沒拿到資料就要重新評估專題範圍。

## 八、成本估算

### 每日成本（穩定運行階段）

每日候選量降為 2000 篇：

| 項目 | 計算 | 成本 |
|------|------|------|
| Apify 探索層 | 2000 × $0.003 | $6 |
| Apify 深挖層（收藏的 5 篇）| 5 × $0.01 | $0.05 |
| Apify 追蹤層（追蹤池 ~30 篇）| 30 × 8 × $0.005 | $1.2 |
| Haiku 評分 | 200 × $0.001 | $0.2 |
| Opus 摘要 | 5 × $0.05 | $0.25 |
| Opus 問答（假設每日 5 次 /ask）| 5 × $0.1 | $0.5 |
| **每日總計** | | **約 $8.2** |
| **每月總計** | | **約 $246** |

使用者沒設預算上限，但仍**保留三個降本旋鈕**以便日後微調：

1. 探索頻率降為每 90 分鐘 → Apify 探索成本砍 1/3
2. 關鍵字種子池精簡（依 `total_collected` 淘汰低品質種子）
3. Opus 問答 prompt cache（同一 tracked_post_id 的 system prompt 整段命中 cache）

### 成本控制機制

`llm_records` + Apify 用量寫入 metrics，每日 dashboard 即時看。設定每日 hard cap（預設 $20）作為保險絲，超過直接停止探索層。

## 九、風險與應對

### 風險一：Threads 公開搜尋限制
2025 年底起 Threads 搜尋需 cookie 認證。應對：用支援 cookie 的 Apify Actor、維護備用帳號、最壞退化成「追蹤已知素人帳號清單」。

### 風險二：Apify 額度燒得比預期快
M1 驗證階段就要算清楚 search 模式的 quota 消耗。應對：探索頻率可降、種子池可精簡。

### 風險三：使用者收藏率過低（< 10%）
表示評分演算法跟使用者口味落差大。應對：用收藏資料反向 fine-tune Haiku prompt、加大「早期」配額觀察是否使用者偏好獨特性內容。

### 風險四：問答模式 token 燒太快
重量 context 開場 8k–35k tokens，多人並用可能單日上看 $50。應對：prompt cache、自動降級成中量模式（`/ask` 旗標切換）、單日問答次數軟上限。

### 風險五：合規與隱私
- 僅處理公開貼文
- 不在報告中展示真實使用者帳號（去識別化）
- 提供 `/forget <id>` 指令完整刪除單一事件資料
- 報告專章討論社群媒體研究倫理

## 十、預期成果

### 可交付項目

1. 完整可運作的 Telegram bot demo
2. GitHub repository（已公開）
3. 專題書面報告（中文，約 30 頁）
4. 5 分鐘 demo 影片
5. 3–5 個從推送 → 收藏 → 完整生命週期的案例分析
6. 系統運行 4 週的量化評估數據（收藏率、後續命中率）
7. 30 組問答 pair 的品質自評結果

### 質性評估

- 系統能否持續產出讓使用者願意收藏的內容（收藏率）
- 收藏的事件是否真的有後續發展（後續命中率）
- 重量 context 下的問答品質是否值得成本
- 「早期捕捉」配額是否真的搶在大眾爆紅前發現過案例

## 十一、與 v2 的差異對照

| 面向 | v2 | v3 |
|------|----|----|
| 互動模型 | 純黑盒推送 | 半黑盒：推送 → 收藏 → 追蹤 + 問答 |
| 探索策略 | 關鍵字 + For You 流模擬對照 | 純關鍵字 |
| 個人化 | 規劃中 | 不做 |
| 推送節奏 | 每日 21:00 + 即時 | 每日 09:00 + 即時破例 |
| 問答 | 無 | 對話模式 + 重量 context |
| 評估 | 完整資料集 + 三策略對照 | 兩個指標 + 案例分析 + 問答自評 |
| 開發節奏 | 週度時程表 | 任務級里程碑（M1–M8） |

## 十二、未來延伸

1. 個人化權重（用 `feedback` 訓練）
2. For You 流模擬補回（v2 想做但 v3 砍掉的）
3. 多平台擴充（X、Dcard）
4. 問答時動態決定 context mode（依問題類型自動切換 light/medium/heavy）
5. Web 介面：時間軸視覺化

## 附錄：技術文件參考

- Apify Threads Scraper: https://apify.com/automation-lab/threads-scraper
- python-telegram-bot: https://docs.python-telegram-bot.org
- Anthropic API: https://docs.claude.com
- APScheduler: https://apscheduler.readthedocs.io
- FastAPI: https://fastapi.tiangolo.com
