from __future__ import annotations

import argparse
import html
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from collector_common import USER_AGENT, atomic_write_json, request_json, utc_now_iso
from env_loader import load_env_file


ROOT_DIR = Path(__file__).resolve().parent
API_URL = "https://openapi.naver.com/v1/search/news.json"
DEFAULT_OUTPUT = Path("data/naver_news.json")
DEFAULT_QUERIES = [
    ("semiconductor", "반도체"),
    ("it", "IT 산업"),
    ("us", "미국 증시"),
    ("kospi", "코스피"),
    ("kosdaq", "코스닥"),
    ("korea_rates", "국고채 금리 한국은행"),
    ("korea_flow", "외국인 기관 순매수 증시"),
    ("us_rates", "미국 국채 금리 연준"),
    ("battery", "2차전지 주식"),
    ("bio", "바이오 주식"),
]
CATEGORY_LABELS = {
    "semiconductor": "반도체",
    "it": "IT",
    "us": "미국",
    "kospi": "코스피",
    "kosdaq": "코스닥",
    "korea_rates": "국내 금리",
    "korea_flow": "국내 수급",
    "us_rates": "미국 금리",
    "battery": "2차전지",
    "bio": "바이오",
}
THUMBNAIL_CATEGORIES = ("semiconductor", "it", "us", "kospi", "kosdaq")
THUMBNAIL_META_KEYS = {
    "og:image",
    "og:image:url",
    "twitter:image",
    "twitter:image:src",
}


class ThumbnailMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.image_urls: list[str] = []

    @property
    def image_url(self) -> str:
        return self.image_urls[0] if self.image_urls else ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        meta_key = (values.get("property") or values.get("name") or "").lower()
        if meta_key in THUMBNAIL_META_KEYS:
            image_url = html.unescape(values.get("content", "")).strip()
            if image_url and image_url not in self.image_urls:
                self.image_urls.append(image_url)


def clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return " ".join(html.unescape(text).split())


def published_timestamp(value: Any) -> float:
    try:
        return parsedate_to_datetime(str(value or "")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def valid_http_url(value: Any) -> bool:
    try:
        return urlparse(str(value or "")).scheme.lower() in {"http", "https"}
    except ValueError:
        return False


def is_generic_thumbnail(value: str) -> bool:
    normalized = value.lower()
    return any(
        marker in normalized
        for marker in (
            "/static.news/image/news/ogtag/",
            "/image/news/ogtag/navernews_",
            "/fb_share.",
            "/sns_share.",
            "/default_og.",
            "/og_default.",
            "/noimage.",
        )
    )


def fetch_article_thumbnail(url: str) -> str:
    if not valid_http_url(url):
        return ""
    try:
        with requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
            },
            timeout=(4, 8),
            allow_redirects=True,
            stream=True,
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()
            if "html" not in content_type:
                return ""
            body = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                body.extend(chunk)
                if len(body) >= 524288:
                    break
            text = bytes(body).decode(response.encoding or "utf-8", errors="replace")
            parser = ThumbnailMetaParser()
            parser.feed(text)
            for candidate in parser.image_urls:
                image_url = urljoin(response.url, candidate)
                if valid_http_url(image_url) and not is_generic_thumbnail(image_url):
                    return image_url
            return ""
    except (requests.RequestException, UnicodeError, ValueError):
        return ""


def add_article_thumbnails(
    items: list[dict[str, Any]],
    per_category: int,
    workers: int,
) -> int:
    if per_category <= 0 or workers <= 0:
        return 0

    selected: list[dict[str, Any]] = []
    selected_links: set[str] = set()
    for category in THUMBNAIL_CATEGORIES:
        category_count = 0
        for item in items:
            link = str(item.get("link") or "")
            if category not in (item.get("categories") or []) or link in selected_links:
                continue
            selected.append(item)
            selected_links.add(link)
            category_count += 1
            if category_count >= per_category:
                break

    def resolve(item: dict[str, Any]) -> tuple[dict[str, Any], str]:
        urls = []
        for key in ("naver_link", "link"):
            url = str(item.get(key) or "").strip()
            if url and url not in urls:
                urls.append(url)
        for url in urls:
            thumbnail_url = fetch_article_thumbnail(url)
            if thumbnail_url:
                return item, thumbnail_url
        return item, ""

    found = 0
    completed = 0
    print(f"[Naver News] thumbnails: {len(selected)} candidates")
    with ThreadPoolExecutor(max_workers=min(12, max(1, workers))) as executor:
        futures = [executor.submit(resolve, item) for item in selected]
        for future in as_completed(futures):
            item, thumbnail_url = future.result()
            completed += 1
            if thumbnail_url:
                item["thumbnail_url"] = thumbnail_url
                found += 1
            if completed % 10 == 0 or completed == len(selected):
                print(
                    f"[Naver News] thumbnails: {completed}/{len(selected)} "
                    f"checked, {found} found"
                )
    return found


def main() -> None:
    load_env_file(ROOT_DIR / ".env")
    parser = argparse.ArgumentParser(description="Collect categorized Naver news search results.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--display", type=int, default=50)
    parser.add_argument(
        "--thumbnails-per-category",
        type=int,
        default=12,
        help="Fetch Open Graph thumbnails for this many recent articles per dashboard category.",
    )
    parser.add_argument("--thumbnail-workers", type=int, default=8)
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
        key=lambda row: published_timestamp(row.get("published_at")),
        reverse=True,
    )
    thumbnail_count = add_article_thumbnails(
        items,
        per_category=max(0, args.thumbnails_per_category),
        workers=max(0, args.thumbnail_workers),
    )
    payload = {
        "source": "NAVER Search API / news",
        "crawled_at_utc": utc_now_iso(),
        "category_labels": CATEGORY_LABELS,
        "queries": [{"category": category, "query": query} for category, query in queries],
        "raw_counts": categories,
        "count": len(items),
        "thumbnail_count": thumbnail_count,
        "items": items,
    }
    atomic_write_json(Path(args.output), payload)
    print(f"Output: {args.output}")
    print(f"Unique articles: {len(items)}")


if __name__ == "__main__":
    main()
