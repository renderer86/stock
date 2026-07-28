from __future__ import annotations

import argparse
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from collector_common import atomic_write_json, request_json, utc_now_iso


NASDAQ_SCREENER = "https://api.nasdaq.com/api/screener/stocks"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
DEFAULT_OUTPUT = Path("data/us_market_snapshot.json")
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    text = re.sub(r"[^0-9.+-]", "", str(value))
    if text in {"", "+", "-", "."}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_symbol(value: str) -> str:
    return value.strip().upper().replace("/", ".")


def yahoo_symbol(value: str) -> str:
    return normalize_symbol(value).replace(".", "-")


def rsi14(closes: list[float]) -> float | None:
    if len(closes) < 15:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(closes[-15:-1], closes[-14:]):
        delta = current - previous
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    average_gain = sum(gains) / 14
    average_loss = sum(losses) / 14
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return round(100 - (100 / (1 + relative_strength)), 2)


def pct_change(latest: float, earlier: float | None) -> float | None:
    if not earlier:
        return None
    return round((latest / earlier - 1) * 100, 2)


def fetch_universe(session: requests.Session) -> list[dict[str, Any]]:
    payload = request_json(
        session,
        "GET",
        NASDAQ_SCREENER,
        params={"tableonly": "true", "limit": 25, "download": "true"},
        attempts=2,
        timeout=60,
    )
    rows = (((payload or {}).get("data") or {}).get("rows") or [])
    universe: list[dict[str, Any]] = []
    for row in rows:
        symbol = normalize_symbol(str(row.get("symbol") or ""))
        if not re.fullmatch(r"[A-Z][A-Z0-9.~-]{0,9}", symbol):
            continue
        market_cap = parse_number(row.get("marketCap"))
        universe.append(
            {
                "symbol": symbol,
                "name": row.get("name"),
                "exchange": row.get("exchange"),
                "sector": row.get("sector"),
                "industry": row.get("industry"),
                "country": row.get("country"),
                "ipo_year": parse_number(row.get("ipoyear")),
                "price": parse_number(row.get("lastsale")),
                "change": parse_number(row.get("netchange")),
                "change_pct": parse_number(row.get("pctchange")),
                "volume": parse_number(row.get("volume")),
                "market_cap_usd": market_cap,
            }
        )
    universe.sort(key=lambda row: row.get("market_cap_usd") or 0, reverse=True)
    return universe


def fetch_history(symbol: str, range_value: str) -> dict[str, Any]:
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_USER_AGENT, "Accept": "application/json"})
    payload = request_json(
        session,
        "GET",
        YAHOO_CHART.format(symbol=quote(yahoo_symbol(symbol), safe="")),
        params={"range": range_value, "interval": "1d", "events": "div,splits"},
        timeout=30,
    )
    result = (((payload or {}).get("chart") or {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError("Yahoo chart returned no result")

    timestamps = result.get("timestamp") or []
    quote_row = (((result.get("indicators") or {}).get("quote") or [{}])[0])
    closes_raw = quote_row.get("close") or []
    opens = quote_row.get("open") or []
    highs = quote_row.get("high") or []
    lows = quote_row.get("low") or []
    volumes = quote_row.get("volume") or []
    bars: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        close = closes_raw[index] if index < len(closes_raw) else None
        if close is None:
            continue
        bars.append(
            {
                "timestamp": timestamp,
                "open": opens[index] if index < len(opens) else None,
                "high": highs[index] if index < len(highs) else None,
                "low": lows[index] if index < len(lows) else None,
                "close": close,
                "volume": volumes[index] if index < len(volumes) else None,
            }
        )
    if not bars:
        raise RuntimeError("Yahoo chart returned no valid bars")

    closes = [float(bar["close"]) for bar in bars]
    latest = closes[-1]
    metrics = {
        "latest_close": round(latest, 4),
        "return_1w": pct_change(latest, closes[-6] if len(closes) >= 6 else None),
        "return_1m": pct_change(latest, closes[-22] if len(closes) >= 22 else None),
        "return_3m": pct_change(latest, closes[-64] if len(closes) >= 64 else None),
        "return_1y": pct_change(latest, closes[-253] if len(closes) >= 253 else None),
        "rsi14": rsi14(closes),
        "sma20": round(sum(closes[-20:]) / 20, 4) if len(closes) >= 20 else None,
        "sma50": round(sum(closes[-50:]) / 50, 4) if len(closes) >= 50 else None,
        "sma200": round(sum(closes[-200:]) / 200, 4) if len(closes) >= 200 else None,
        "week52_high": round(max(closes[-252:]), 4),
        "week52_low": round(min(closes[-252:]), 4),
    }
    return {"metrics": metrics, "history": bars}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a U.S. stock universe from Nasdaq and price history from Yahoo Chart."
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--history-limit", type=int, default=200)
    parser.add_argument("--history-range", default="1y")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": BROWSER_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.nasdaq.com",
            "Referer": "https://www.nasdaq.com/",
        }
    )
    stocks = fetch_universe(session)
    by_symbol = {row["symbol"]: row for row in stocks}
    targets = [row["symbol"] for row in stocks[: max(0, args.history_limit)]]
    errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(fetch_history, symbol, args.history_range): symbol
            for symbol in targets
        }
        for index, future in enumerate(as_completed(futures), start=1):
            symbol = futures[future]
            try:
                by_symbol[symbol].update(future.result())
            except Exception as exc:  # noqa: BLE001
                errors[symbol] = str(exc)
            if index % 25 == 0 or index == len(targets):
                print(f"[US] history {index}/{len(targets)}")

    payload = {
        "source": ["Nasdaq stock screener", "Yahoo Finance Chart"],
        "crawled_at_utc": utc_now_iso(),
        "count": len(stocks),
        "history_count": sum(1 for row in stocks if row.get("history")),
        "history_limit": args.history_limit,
        "history_range": args.history_range,
        "errors": errors,
        "stocks": stocks,
    }
    atomic_write_json(Path(args.output), payload, compact=True)
    print(f"Output: {args.output}")
    print(f"Stocks: {len(stocks)}, history: {payload['history_count']}")


if __name__ == "__main__":
    main()
