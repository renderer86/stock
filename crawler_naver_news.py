from __future__ import annotations

import argparse
import html
import os
import re
from pathlib import Path
from typing import Any

import requests

from collector_common import USER_AGENT, atomic_write_json, request_json, utc_now_iso
from env_loader import load_env_file


ROOT_DIR = Path(__file__).resolve().parent
API_URL = "https://openapi.naver.com/v1/search/news.json"
DEFAULT_OUTPUT = Path("data/naver_news.json")
DEFAULT_QUERIES = [
    ("korea_market", "코스피 OR 코스닥 증시"),
    ("korea_rates", "국고채 금리 한국은행"),
    ("korea_flow", "외국인 기관 순매수 증시"),
    ("us_market", "미국 증시 나스닥 S&P500"),
    ("us_rates", "미국 국채 금리 연준"),
    ("semiconductor", "반도체 주식"),
    ("battery", "2차전지 주식"),
    ("bio", "바이오 주식"),
]


def clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return " ".join(html.unescape(text).split())


def main() -> None:
    load_env_file(ROOT_DIR / ".env")
    parser = argparse.ArgumentParser(description="Collect categorized Naver news search results.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--display", type=int, default=50)
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Additional query in category=query form.",
    )
    args = parser.parse_args()

    client_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise SystemExit("NAVER_CLIENT_ID and NAVER_CLIENT_SECRET are required.")

    queries = list(DEFAULT_QUERIES)
    for raw in args.query:
        if "=" not in raw:
            raise SystemExit(f"Invalid --query value: {raw}. Use category=query.")
        category, query = raw.split("=", 1)
        queries.append((category.strip(), query.strip()))

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        }
    )

    by_link: dict[str, dict[str, Any]] = {}
    categories: dict[str, int] = {}
    for category, query in queries:
        payload = request_json(
            session,
            "GET",
            API_URL,
            params={
                "query": query,
                "display": min(100, max(1, args.display)),
                "start": 1,
                "sort": "date",
            },
        )
        items = payload.get("items") or []
        categories[category] = len(items)
        for item in items:
            link = str(item.get("originallink") or item.get("link") or "").strip()
            if not link:
                continue
            current = by_link.setdefault(
                link,
                {
                    "title": clean_text(item.get("title")),
                    "description": clean_text(item.get("description")),
                    "link": link,
                    "naver_link": item.get("link"),
                    "published_at": item.get("pubDate"),
                    "categories": [],
                    "queries": [],
                },
            )
            if category not in current["categories"]:
                current["categories"].append(category)
            if query not in current["queries"]:
                current["queries"].append(query)
        print(f"[Naver News] {category}: {len(items)}")

    items = sorted(
        by_link.values(),
        key=lambda row: str(row.get("published_at") or ""),
        reverse=True,
    )
    payload = {
        "source": "NAVER Search API / news",
        "crawled_at_utc": utc_now_iso(),
        "queries": [{"category": category, "query": query} for category, query in queries],
        "raw_counts": categories,
        "count": len(items),
        "items": items,
    }
    atomic_write_json(Path(args.output), payload)
    print(f"Output: {args.output}")
    print(f"Unique articles: {len(items)}")


if __name__ == "__main__":
    main()
