# v3 Schema — ER 圖

10 張表，分四組：探索層 / 評分層 / 追蹤層 / LLM 紀錄。GitHub 直接渲染 mermaid。

```mermaid
erDiagram
    keyword_seeds {
        BIGINT id PK
        VARCHAR keyword UK
        VARCHAR category
        BOOL enabled
        TIMESTAMP last_polled_at
        INT total_candidates_yielded
        INT total_promoted
        INT total_collected
    }

    candidate_posts {
        BIGINT id PK
        VARCHAR threads_post_id UK
        VARCHAR author_username
        INT author_follower_count
        TEXT post_url
        TEXT content
        TIMESTAMP posted_at
        TIMESTAMP discovered_at
        VARCHAR discovery_source
        INT initial_likes
        INT initial_replies
        INT initial_reposts
        INT initial_views
        JSONB metadata
    }

    scoring_records {
        BIGINT id PK
        BIGINT candidate_post_id FK
        VARCHAR stage
        BOOL passed
        FLOAT score
        JSONB details
        TIMESTAMP scored_at
        NUMERIC cost_usd
    }

    daily_pushes {
        BIGINT id PK
        DATE push_date
        BIGINT candidate_post_id FK
        VARCHAR push_type
        INT rank
        TIMESTAMP pushed_at
    }

    feedback {
        BIGINT id PK
        BIGINT user_id FK
        BIGINT candidate_post_id FK
        VARCHAR action
        TIMESTAMP acted_at
    }

    tracked_posts {
        BIGINT id PK
        BIGINT candidate_post_id FK_UK
        BIGINT user_id FK
        TIMESTAMP promoted_at
        VARCHAR polling_tier
        TIMESTAMP last_polled_at
        VARCHAR status
        TEXT initial_summary
    }

    post_snapshots {
        BIGINT id PK
        BIGINT tracked_post_id FK
        TIMESTAMP captured_at
        INT like_count
        INT reply_count
        INT repost_count
        JSONB new_replies
    }

    related_posts {
        BIGINT id PK
        BIGINT tracked_post_id FK
        VARCHAR threads_post_id UK
        VARCHAR relation_type
        FLOAT relevance_score
        BOOL is_milestone
        TEXT content
        TIMESTAMP posted_at
        TIMESTAMP discovered_at
    }

    qa_sessions {
        BIGINT id PK
        BIGINT user_id FK
        BIGINT tracked_post_id FK
        VARCHAR context_mode
        TIMESTAMP started_at
        TIMESTAMP ended_at
        VARCHAR end_reason
    }

    qa_messages {
        BIGINT id PK
        BIGINT session_id FK
        VARCHAR role
        TEXT content
        VARCHAR question_type
        TIMESTAMP sent_at
    }

    llm_records {
        BIGINT id PK
        VARCHAR purpose
        BIGINT related_id
        VARCHAR model
        INT input_tokens
        INT output_tokens
        NUMERIC cost_usd
        TEXT content
        TIMESTAMP generated_at
    }

    users {
        BIGINT id PK
        BIGINT telegram_chat_id UK
        VARCHAR telegram_username
        JSONB settings
    }

    candidate_posts ||--o{ scoring_records : "scored in 3 stages"
    candidate_posts ||--o{ daily_pushes : "selected for push"
    candidate_posts ||--o{ feedback : "user reacts"
    candidate_posts ||--o| tracked_posts : "promoted by ❤️"

    tracked_posts ||--o{ post_snapshots : "polled over time"
    tracked_posts ||--o{ related_posts : "follow-up events"
    tracked_posts ||--o{ qa_sessions : "asked about"

    qa_sessions ||--o{ qa_messages : "conversation log"

    users ||--o{ feedback : "submits"
    users ||--o{ tracked_posts : "owns"
    users ||--o{ qa_sessions : "starts"

    keyword_seeds }o..o{ candidate_posts : "discovery_source tag"
```

## 流程對應

| 階段 | 寫入 | 讀取 |
|------|------|------|
| M2 探索層 | `candidate_posts` | `keyword_seeds.enabled` |
| M3 評分層 | `scoring_records` | `candidate_posts` |
| M4 推送層 | `daily_pushes` / `feedback` | `scoring_records` `candidate_posts` |
| M5 收藏追蹤層 | `tracked_posts` `post_snapshots` `related_posts` | `feedback` (collect) |
| M6 問答層 | `qa_sessions` `qa_messages` `llm_records` | `tracked_posts` 完整 context |

`llm_records` 是統一的 LLM 呼叫 audit trail — 評分 / 摘要 / 問答都寫這，藉 `purpose` + `related_id` 反查歸屬。
