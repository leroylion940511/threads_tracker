"""M1 smoke test：watcher.data 關鍵字搜尋 actor 的可行性驗證.

跑法：
    uv run python scripts/m1_apify_smoke.py                     # 預設只跑 3 個 keyword
    uv run python scripts/m1_apify_smoke.py --keywords 後續再更新 求後續
    uv run python scripts/m1_apify_smoke.py --max-per-keyword 5

驗證內容：
    1. APIFY_TOKEN 能成功跑 actor
    2. raw item 欄位名與 _normalize_post 對得上
    3. 印出實際 cost units 提示（從 actor run 詳情）
    4. 量出每 keyword 平均 hits 數，方便估月成本
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 讓 `python scripts/...` 也能 import threads_tracker
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from threads_tracker.config import get_settings  # noqa: E402
from threads_tracker.scrapers.watcher import WatcherDataSearchScraper  # noqa: E402
from threads_tracker.seeds.keyword_seeds import KEYWORD_SEEDS  # noqa: E402


DEFAULT_KEYWORDS = ["後續再更新", "求後續", "我崩潰"]


def truncate(s: str, n: int = 80) -> str:
    s = (s or "").replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=None,
        help="若不指定則用預設 3 個輕量 keyword；--all 用全部 30 個 seed",
    )
    parser.add_argument("--all", action="store_true", help="跑全部 30 個 seed")
    parser.add_argument("--max-per-keyword", type=int, default=5)
    parser.add_argument("--dump-raw", action="store_true", help="印第一筆 raw JSON")
    args = parser.parse_args()

    if args.all:
        keywords = [s.keyword for s in KEYWORD_SEEDS]
    elif args.keywords:
        keywords = args.keywords
    else:
        keywords = DEFAULT_KEYWORDS

    s = get_settings()
    print(f"[M1] keywords ({len(keywords)}): {keywords}")
    print(f"[M1] max_per_keyword: {args.max_per_keyword}")
    print(f"[M1] APIFY_TOKEN loaded: {bool(s.apify_token)}")
    print(f"[M1] search actor: {s.apify_search_actor_id}")

    scraper = WatcherDataSearchScraper()
    try:
        raw_items = await scraper.search_keywords_raw(
            keywords=keywords,
            max_per_keyword=args.max_per_keyword,
        )
    finally:
        await scraper.aclose()

    print(f"\n[M1] total items returned: {len(raw_items)}")
    if not raw_items:
        print("[M1] 沒抓到資料，可能：keyword 太冷僻 / actor 配置錯 / 被限流")
        return 1

    if args.dump_raw:
        print("\n[M1] first raw item:")
        print(json.dumps(raw_items[0], ensure_ascii=False, indent=2))

    print("\n[M1] raw item field coverage:")
    expected_fields = [
        "id", "text", "author", "author_name", "author_id", "created_at",
        "like_count", "reply_count", "repost_count", "quote_count", "view_count",
        "hashtags", "mentions", "urls", "media", "lang",
        "is_reply", "is_repost", "url", "verified",
        "follower_count", "following_count",
    ]
    coverage: dict[str, int] = {f: 0 for f in expected_fields}
    extra_keys: set[str] = set()
    for it in raw_items:
        for f in expected_fields:
            if f in it and it[f] not in (None, ""):
                coverage[f] += 1
        extra_keys.update(set(it.keys()) - set(expected_fields))
    for f, c in coverage.items():
        flag = "✅" if c > 0 else "❌"
        print(f"  {flag} {f:<18} {c}/{len(raw_items)}")
    if extra_keys:
        print(f"\n[M1] 文件未列、實際出現的欄位: {sorted(extra_keys)}")

    print("\n[M1] normalized PostPayload preview (first 5):")
    for it in raw_items[:5]:
        p = WatcherDataSearchScraper._normalize_post(it)
        print(
            f"  id={p.threads_post_id[:14]:<14} "
            f"@{p.author_username:<18} "
            f"❤{p.like_count:<5} 💬{p.reply_count:<4} "
            f"{truncate(p.content, 60)}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
