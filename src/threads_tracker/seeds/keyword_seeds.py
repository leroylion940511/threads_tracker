"""v3 探索層初始 keyword seeds（繁中、Threads 觸發詞）.

設計目標：找「故事開頭、暗示有後續、情緒驅動」的貼文，
而不是趨勢詞或新聞詞。每類 6 個，共 30 個。

M1 驗證階段先全列；M2 起會載進 keyword_seeds 資料表，
觀察兩週後依 total_collected = 0 砍掉效益差的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Category = Literal[
    "follow_up",   # 後續暗示：本文暗示有後續發展，是追蹤的好起點
    "help_empathy",  # 求助共鳴：徵求建議 / 求認同，留言區常出現劇情
    "event",       # 事件性：發生了某件具體的事
    "narrative",   # 敘事開頭：故事化開場
    "emotion",     # 情緒爆發：強烈情緒驅動，留言成長快
]


@dataclass(frozen=True, slots=True)
class KeywordSeed:
    keyword: str
    category: Category
    note: str = ""


KEYWORD_SEEDS: list[KeywordSeed] = [
    # --- 後續暗示 ---------------------------------------------------------
    KeywordSeed("後續再更新", "follow_up", "PO 自己預告會回來補"),
    KeywordSeed("求後續", "follow_up", "留言區/標題常見追更請求"),
    KeywordSeed("更新一下", "follow_up"),
    KeywordSeed("後來呢", "follow_up", "回覆第三人的後續詢問"),
    KeywordSeed("未完待續", "follow_up"),
    KeywordSeed("改天再說", "follow_up", "弱觸發詞，可能噪音多"),

    # --- 求助共鳴 ---------------------------------------------------------
    KeywordSeed("該怎麼辦", "help_empathy"),
    KeywordSeed("求建議", "help_empathy"),
    KeywordSeed("有人也這樣嗎", "help_empathy"),
    KeywordSeed("是不是只有我", "help_empathy"),
    KeywordSeed("我是不是想太多", "help_empathy"),
    KeywordSeed("請問大家", "help_empathy", "弱觸發詞，可能撈到 FAQ"),

    # --- 事件性 -----------------------------------------------------------
    KeywordSeed("今天發生", "event"),
    KeywordSeed("剛剛發生", "event"),
    KeywordSeed("真的太誇張", "event"),
    KeywordSeed("結果發現", "event"),
    KeywordSeed("沒想到", "event"),
    KeywordSeed("你們不會相信", "event"),

    # --- 敘事開頭 ---------------------------------------------------------
    KeywordSeed("故事是這樣", "narrative"),
    KeywordSeed("事情是這樣", "narrative"),
    KeywordSeed("先說背景", "narrative"),
    KeywordSeed("讓我說一下", "narrative"),
    KeywordSeed("想跟大家分享", "narrative", "弱觸發詞，與業配難分"),
    KeywordSeed("一切要從", "narrative"),

    # --- 情緒爆發 ---------------------------------------------------------
    KeywordSeed("我真的氣到", "emotion"),
    KeywordSeed("我崩潰", "emotion"),
    KeywordSeed("太傻眼", "emotion"),
    KeywordSeed("氣到睡不著", "emotion"),
    KeywordSeed("心好累", "emotion"),
    KeywordSeed("真的不行了", "emotion"),
]


assert len(KEYWORD_SEEDS) == 30, "Expected exactly 30 seeds"


def by_category(category: Category) -> list[KeywordSeed]:
    return [s for s in KEYWORD_SEEDS if s.category == category]


def keywords_only() -> list[str]:
    return [s.keyword for s in KEYWORD_SEEDS]
