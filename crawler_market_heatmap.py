from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from collector_common import atomic_write_json, utc_now_iso


ROOT_DIR = Path(__file__).resolve().parent
KOREA_INPUT = ROOT_DIR / "data" / "market_sum_by_roe.json"
US_INPUT = ROOT_DIR / "data" / "us_market_snapshot.json"
DEFAULT_OUTPUT = ROOT_DIR / "data" / "market_heatmap.json"
NAVER_SECTOR_URL = "https://finance.naver.com/sise/sise_group.naver"
NAVER_SECTOR_DETAIL_URL = "https://finance.naver.com/sise/sise_group_detail.naver"
NAVER_ITEM_URL = "https://finance.naver.com/item/main.naver"
NASDAQ_ITEM_URL = "https://www.nasdaq.com/market-activity/stocks"
CODE_PATTERN = re.compile(r"(?:\?|&)code=(\d{6})(?:&|$)")
REQUEST_TIMEOUT = 30


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def fetch_soup(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    attempts: int = 3,
) -> BeautifulSoup:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            response.encoding = "euc-kr"
            return BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"Request failed: {url}: {last_error}") from last_error


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/126.0 MarketHeatmap/1.0"
            ),
            "Referer": NAVER_SECTOR_URL,
        }
    )
    return session


def fetch_sector_catalog() -> list[dict[str, str]]:
    session = make_session()
    soup = fetch_soup(
        session,
        NAVER_SECTOR_URL,
        params={"type": "upjong"},
    )
    sectors: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in soup.select(
        "table.type_1 a[href*='sise_group_detail.naver'][href*='type=upjong']"
    ):
        href = str(link.get("href") or "")
        query = parse_qs(urlparse(href).query)
        sector_id = str((query.get("no") or [""])[0]).strip()
        name = link.get_text(" ", strip=True)
        if not sector_id or not name or sector_id in seen:
            continue
        seen.add(sector_id)
        sectors.append({"id": sector_id, "name": name})
    if not sectors:
        raise RuntimeError("Naver sector catalog is empty.")
    return sectors


def fetch_sector_members(sector: dict[str, str]) -> tuple[str, dict[str, str]]:
    session = make_session()
    soup = fetch_soup(
        session,
        NAVER_SECTOR_DETAIL_URL,
        params={"no": sector["id"], "type": "upjong"},
    )
    members: dict[str, str] = {}
    for link in soup.select("table.type_5 td.name a[href*='code=']"):
        href = str(link.get("href") or "")
        match = CODE_PATTERN.search(href)
        if match:
            members[match.group(1)] = sector["name"]
    return sector["name"], members


def previous_korea_sector_map(output: Path) -> dict[str, str]:
    if not output.exists():
        return {}
    try:
        payload = load_json(output)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    markets = payload.get("markets") or {}
    stocks = (markets.get("KR") or {}).get("stocks") or []
    return {
        str(row.get("symbol") or ""): str(row.get("sector") or "")
        for row in stocks
        if row.get("symbol") and row.get("sector")
    }


def crawl_korea_sector_map(
    output: Path,
    *,
    workers: int,
) -> tuple[dict[str, str], list[str], int]:
    fallback = previous_korea_sector_map(output)
    errors: list[str] = []
    try:
        catalog = fetch_sector_catalog()
    except Exception as exc:
        return fallback, [f"sector catalog: {exc}"], 0

    sector_map: dict[str, str] = {}
    completed = 0
    print(f"[SECTORS] Naver catalog: {len(catalog)}", flush=True)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(fetch_sector_members, sector): sector
            for sector in catalog
        }
        for future in as_completed(futures):
            sector = futures[future]
            try:
                _, members = future.result()
                sector_map.update(members)
            except Exception as exc:
                errors.append(f"{sector['name']}: {exc}")
            completed += 1
            if completed % 10 == 0 or completed == len(catalog):
                print(
                    f"[SECTORS] {completed}/{len(catalog)} "
                    f"({len(sector_map):,} symbols mapped)",
                    flush=True,
                )

    for code, sector in fallback.items():
        sector_map.setdefault(code, sector)
    return sector_map, errors, len(catalog)


def normalize_korea_stocks(
    payload: dict[str, Any],
    sector_map: dict[str, str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    stocks: list[dict[str, Any]] = []
    for row in payload.get("stocks") or []:
        code = str(row.get("code") or "").strip()
        price = number(row.get("current_price"))
        market_cap = number(row.get("market_cap_krw_100m"))
        change_pct = number(row.get("diff_rate"))
        if (
            not code
            or price is None
            or price <= 0
            or market_cap is None
            or market_cap <= 0
            or change_pct is None
            or row.get("is_suspended")
        ):
            continue
        stocks.append(
            {
                "market": "KR",
                "symbol": code,
                "name": str(row.get("name") or code).strip(),
                "group": str(row.get("market") or "KOREA").strip(),
                "sector": sector_map.get(code) or "기타",
                "price": price,
                "change_pct": change_pct,
                "market_cap": market_cap,
                "volume": number(row.get("volume")) or 0,
                "currency": "KRW",
                "roe": number(row.get("roe")),
                "roa": number(row.get("roa")),
                "pbr": number(row.get("pbr")),
                "per": number(row.get("per")),
                "foreigner_ratio": number(row.get("foreigner_ratio")),
                "sales_growth": number(row.get("sales_increasing_rate")),
                "url": f"{NAVER_ITEM_URL}?code={code}",
            }
        )
    stocks.sort(key=lambda item: item["market_cap"], reverse=True)
    return stocks[:limit] if limit > 0 else stocks


def normalize_us_stocks(
    payload: dict[str, Any],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    stocks: list[dict[str, Any]] = []
    for row in payload.get("stocks") or []:
        symbol = str(row.get("symbol") or "").strip().upper()
        price = number(row.get("price"))
        market_cap = number(row.get("market_cap_usd"))
        change_pct = number(row.get("change_pct"))
        if (
            not symbol
            or price is None
            or price <= 0
            or market_cap is None
            or market_cap <= 0
            or change_pct is None
        ):
            continue
        metrics = row.get("metrics") or {}
        stocks.append(
            {
                "market": "US",
                "symbol": symbol,
                "name": str(row.get("name") or symbol).strip(),
                "group": str(row.get("exchange") or "US").strip(),
                "sector": str(row.get("sector") or "Other").strip(),
                "industry": str(row.get("industry") or "").strip(),
                "price": price,
                "change_pct": change_pct,
                "market_cap": market_cap,
                "volume": number(row.get("volume")) or 0,
                "currency": "USD",
                "rsi14": number(metrics.get("rsi14")),
                "return_1w": number(metrics.get("return_1w")),
                "return_1m": number(metrics.get("return_1m")),
                "return_3m": number(metrics.get("return_3m")),
                "week52_high": number(metrics.get("week52_high")),
                "week52_low": number(metrics.get("week52_low")),
                "url": f"{NASDAQ_ITEM_URL}/{symbol.lower()}",
            }
        )
    stocks.sort(key=lambda item: item["market_cap"], reverse=True)
    return stocks[:limit] if limit > 0 else stocks


def sector_summaries(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for stock in stocks:
        grouped.setdefault(str(stock.get("sector") or "Other"), []).append(stock)
    summaries = []
    for name, rows in grouped.items():
        total_cap = sum(number(row.get("market_cap")) or 0 for row in rows)
        weighted_change = (
            sum(
                (number(row.get("change_pct")) or 0)
                * (number(row.get("market_cap")) or 0)
                for row in rows
            )
            / total_cap
            if total_cap
            else 0
        )
        summaries.append(
            {
                "name": name,
                "count": len(rows),
                "market_cap": total_cap,
                "change_pct": round(weighted_change, 4),
            }
        )
    return sorted(summaries, key=lambda row: row["market_cap"], reverse=True)


def build_payload(
    *,
    korea_payload: dict[str, Any],
    us_payload: dict[str, Any],
    sector_map: dict[str, str],
    sector_errors: list[str],
    sector_catalog_count: int,
    korea_limit: int,
    us_limit: int,
) -> dict[str, Any]:
    korea_stocks = normalize_korea_stocks(
        korea_payload,
        sector_map,
        limit=korea_limit,
    )
    us_stocks = normalize_us_stocks(us_payload, limit=us_limit)
    return {
        "schema_version": 1,
        "crawled_at_utc": utc_now_iso(),
        "source": [
            "Naver Finance market cap and sectors",
            "Nasdaq screener and Yahoo Finance snapshot",
        ],
        "source_urls": [
            NAVER_SECTOR_URL,
            "https://www.nasdaq.com/market-activity/stocks/screener",
        ],
        "sector_catalog_count": sector_catalog_count,
        "sector_mapping_count": len(sector_map),
        "errors": sector_errors,
        "count": len(korea_stocks) + len(us_stocks),
        "markets": {
            "KR": {
                "label": "한국",
                "data_date": korea_payload.get("crawled_at_utc"),
                "count": len(korea_stocks),
                "sectors": sector_summaries(korea_stocks),
                "stocks": korea_stocks,
            },
            "US": {
                "label": "미국",
                "data_date": us_payload.get("crawled_at_utc"),
                "count": len(us_stocks),
                "sectors": sector_summaries(us_stocks),
                "stocks": us_stocks,
            },
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a compact Korea/U.S. stock heatmap dataset with Naver "
            "industry mappings and existing market snapshots."
        )
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--korea-limit", type=int, default=1800)
    parser.add_argument("--us-limit", type=int, default=1800)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output = args.output if args.output.is_absolute() else ROOT_DIR / args.output
    korea_payload = load_json(KOREA_INPUT)
    us_payload = load_json(US_INPUT)
    sector_map, errors, sector_count = crawl_korea_sector_map(
        output,
        workers=args.workers,
    )
    payload = build_payload(
        korea_payload=korea_payload,
        us_payload=us_payload,
        sector_map=sector_map,
        sector_errors=errors,
        sector_catalog_count=sector_count,
        korea_limit=args.korea_limit,
        us_limit=args.us_limit,
    )
    atomic_write_json(output, payload, compact=True)
    print(f"Output: {output}", flush=True)
    print(
        "Heatmap stocks: "
        f"KR {payload['markets']['KR']['count']:,} / "
        f"US {payload['markets']['US']['count']:,}",
        flush=True,
    )
    if errors:
        print(f"[WARN] Sector pages failed: {len(errors)}", flush=True)


if __name__ == "__main__":
    main()
