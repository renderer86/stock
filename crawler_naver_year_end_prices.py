from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path
import threading
import time
from typing import Any
import xml.etree.ElementTree as ET

import requests

from collector_common import USER_AGENT, atomic_write_json, utc_now_iso


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_MARKET_SUM = ROOT_DIR / "data" / "market_sum.json"
DEFAULT_OUTPUT = ROOT_DIR / "data" / "naver_year_end_prices.json"
CHART_URL = "https://fchart.stock.naver.com/sise.nhn"
REQUEST_TIMEOUT = 30
_THREAD_LOCAL = threading.local()


def parse_monthly_chart(content: bytes) -> list[dict[str, Any]]:
    text = content.decode("euc-kr", errors="replace")
    declaration_end = text.find("?>")
    if text.lstrip().startswith("<?xml") and declaration_end >= 0:
        text = text[declaration_end + 2 :]
    root = ET.fromstring(text)
    by_year: dict[int, dict[str, Any]] = {}
    for element in root.iter("item"):
        fields = str(element.attrib.get("data") or "").split("|")
        if len(fields) < 5 or len(fields[0]) != 8:
            continue
        try:
            date = fields[0]
            year = int(date[:4])
            close = int(float(fields[4].replace(",", "")))
        except (TypeError, ValueError):
            continue
        current = by_year.get(year)
        if current is None or date > current["date"]:
            by_year[year] = {"year": year, "date": date, "close": close}
    return [by_year[year] for year in sorted(by_year)]


def _session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/xml,text/xml,*/*",
                "Referer": "https://finance.naver.com/",
            }
        )
        _THREAD_LOCAL.session = session
    return session


def fetch_year_end_prices(
    ticker: str,
    *,
    start_year: int,
    end_year: int,
    retries: int = 3,
) -> dict[str, Any]:
    month_count = max(24, (datetime.now().year - start_year + 2) * 12)
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            response = _session().get(
                CHART_URL,
                params={
                    "symbol": ticker,
                    "timeframe": "month",
                    "count": month_count,
                    "requestType": 0,
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            prices = [
                row
                for row in parse_monthly_chart(response.content)
                if start_year <= row["year"] <= end_year
            ]
            return {
                "status": "ok" if prices else "empty",
                "requested_start_year": start_year,
                "requested_end_year": end_year,
                "prices": prices,
            }
        except (requests.RequestException, ET.ParseError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(min(2**attempt, 5))
    return {
        "status": "error",
        "requested_start_year": start_year,
        "requested_end_year": end_year,
        "prices": [],
        "error": last_error,
    }


def load_json(path: Path, *, required: bool = True) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            raise SystemExit(f"Input file does not exist: {path}") from None
        return {}
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a JSON object: {path}")
    return payload


def ticker_universe(market_sum: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str(row.get("code") or "").strip()
            for row in market_sum.get("stocks") or []
            if str(row.get("code") or "").strip()
        }
    )


def cached_for_period(
    entry: dict[str, Any],
    *,
    end_year: int,
) -> bool:
    if entry.get("status") not in {"ok", "empty"}:
        return False
    return int(entry.get("requested_end_year") or 0) >= end_year


def crawl_year_end_prices(
    *,
    market_sum_path: Path,
    output_path: Path,
    start_year: int,
    end_year: int,
    workers: int,
    limit: int | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    market_sum = load_json(market_sum_path)
    existing = load_json(output_path, required=False)
    existing_stocks = existing.get("stocks") or {}
    tickers = ticker_universe(market_sum)
    if limit is not None:
        tickers = tickers[: max(0, limit)]

    stocks: dict[str, Any] = {
        ticker: dict(existing_stocks.get(ticker) or {}) for ticker in tickers
    }
    pending = [
        ticker
        for ticker in tickers
        if refresh
        or not cached_for_period(
            stocks.get(ticker) or {},
            end_year=end_year,
        )
    ]
    universe_changed = set(existing_stocks) != set(tickers)
    print(
        f"[NAVER YEAR-END] universe={len(tickers):,} "
        f"cached={len(tickers) - len(pending):,} fetch={len(pending):,}",
        flush=True,
    )
    if not pending and not universe_changed and existing:
        print("[NAVER YEAR-END] cache is current", flush=True)
        return existing

    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                fetch_year_end_prices,
                ticker,
                start_year=start_year,
                end_year=end_year,
            ): ticker
            for ticker in pending
        }
        for future in as_completed(futures):
            ticker = futures[future]
            stocks[ticker] = future.result()
            completed += 1
            if completed % 100 == 0 or completed == len(pending):
                print(
                    f"[NAVER YEAR-END] {completed:,}/{len(pending):,}",
                    flush=True,
                )

    payload = {
        "schema_version": 1,
        "source": "Naver Finance monthly chart",
        "source_url": CHART_URL,
        "crawled_at_utc": utc_now_iso(),
        "period": {"start_year": start_year, "end_year": end_year},
        "count": len(stocks),
        "success_count": sum(
            entry.get("status") == "ok" for entry in stocks.values()
        ),
        "stocks": stocks,
    }
    atomic_write_json(output_path, payload, compact=True)
    print(f"Output: {output_path}", flush=True)
    return payload


def parse_args() -> argparse.Namespace:
    current_year = datetime.now().year
    parser = argparse.ArgumentParser(
        description="Collect compact year-end closing prices from Naver monthly charts."
    )
    parser.add_argument("--market-sum", type=Path, default=DEFAULT_MARKET_SUM)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start-year", type=int, default=current_year - 10)
    parser.add_argument("--end-year", type=int, default=current_year - 1)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.start_year > args.end_year:
        raise SystemExit("start-year must be less than or equal to end-year")
    crawl_year_end_prices(
        market_sum_path=args.market_sum,
        output_path=args.output,
        start_year=args.start_year,
        end_year=args.end_year,
        workers=args.workers,
        limit=args.limit,
        refresh=args.refresh,
    )


if __name__ == "__main__":
    main()
