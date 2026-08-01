from __future__ import annotations

import argparse
import ast
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

from collector_common import atomic_write_json, request_json, utc_now_iso


YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
NAVER_INDEX_CHART = "https://api.finance.naver.com/siseJson.naver"
DEFAULT_OUTPUT = Path("data/market_indices.json")
KST = ZoneInfo("Asia/Seoul")
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)

ASSETS = (
    {
        "id": "kospi",
        "symbol": "^KS11",
        "name": "코스피",
        "name_en": "KOSPI",
        "group": "Korea",
        "decimals": 2,
    },
    {
        "id": "kosdaq",
        "symbol": "^KQ11",
        "name": "코스닥",
        "name_en": "KOSDAQ",
        "group": "Korea",
        "decimals": 2,
    },
    {
        "id": "dow",
        "symbol": "^DJI",
        "name": "다우존스",
        "name_en": "Dow Jones",
        "group": "United States",
        "decimals": 2,
    },
    {
        "id": "nasdaq",
        "symbol": "^IXIC",
        "name": "나스닥",
        "name_en": "NASDAQ",
        "group": "United States",
        "decimals": 2,
    },
    {
        "id": "sp500",
        "symbol": "^GSPC",
        "name": "S&P 500",
        "name_en": "S&P 500",
        "group": "United States",
        "decimals": 2,
    },
    {
        "id": "russell2000",
        "symbol": "^RUT",
        "name": "러셀 2000",
        "name_en": "Russell 2000",
        "group": "United States",
        "decimals": 2,
    },
    {
        "id": "bitcoin",
        "symbol": "BTC-USD",
        "name": "비트코인",
        "name_en": "Bitcoin",
        "group": "Crypto",
        "decimals": 0,
    },
    {
        "id": "ethereum",
        "symbol": "ETH-USD",
        "name": "이더리움",
        "name_en": "Ethereum",
        "group": "Crypto",
        "decimals": 2,
    },
)


def pct_change(latest: float, earlier: float | None) -> float | None:
    if earlier is None or earlier == 0:
        return None
    return round((latest / earlier - 1) * 100, 2)


def history_return(closes: list[float], sessions: int) -> float | None:
    if len(closes) <= sessions:
        return None
    return pct_change(closes[-1], closes[-sessions - 1])


def parse_naver_index_history(text: str) -> list[dict[str, Any]]:
    """Parse Naver's JavaScript-style daily index array without eval()."""

    try:
        payload = ast.literal_eval(text.strip())
    except (SyntaxError, ValueError) as exc:
        raise RuntimeError("Naver index chart returned an invalid array.") from exc
    if not isinstance(payload, list) or len(payload) < 2:
        raise RuntimeError("Naver index chart returned no daily rows.")

    history: list[dict[str, Any]] = []
    for values in payload[1:]:
        if not isinstance(values, list) or len(values) < 6:
            continue
        date_digits = re.sub(r"\D", "", str(values[0] or ""))
        if not re.fullmatch(r"\d{8}", date_digits):
            continue
        try:
            session_date = datetime.strptime(date_digits, "%Y%m%d").replace(
                tzinfo=KST
            )
            open_value = float(values[1])
            high_value = float(values[2])
            low_value = float(values[3])
            close_value = float(values[4])
            volume_value = int(float(values[5]))
        except (TypeError, ValueError):
            continue
        history.append(
            {
                "date": session_date.date().isoformat(),
                "timestamp": int(session_date.timestamp()),
                "open": open_value,
                "high": high_value,
                "low": low_value,
                "close": round(close_value, 6),
                "volume": volume_value,
            }
        )
    if len(history) < 2:
        raise RuntimeError("Naver index chart returned insufficient daily history.")
    return sorted(history, key=lambda row: row["date"])


def fetch_naver_index_history(
    session: requests.Session,
    symbol: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = session.get(
                NAVER_INDEX_CHART,
                params={
                    "symbol": symbol,
                    "requestType": "1",
                    "startTime": start_date.replace("-", ""),
                    "endTime": end_date.replace("-", ""),
                    "timeframe": "day",
                },
                timeout=30,
            )
            response.raise_for_status()
            return parse_naver_index_history(response.text)
        except (requests.RequestException, RuntimeError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt)
    raise RuntimeError(
        f"Naver index history failed for {symbol}: {type(last_error).__name__}"
    ) from last_error


def merge_history(
    base_history: list[dict[str, Any]],
    preferred_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_date = {
        str(row.get("date")): row
        for row in base_history
        if row.get("date") and row.get("close") is not None
    }
    for row in preferred_history:
        if row.get("date") and row.get("close") is not None:
            by_date[str(row["date"])] = row
    return [by_date[key] for key in sorted(by_date)]


def fetch_asset(asset: dict[str, Any], range_value: str) -> dict[str, Any]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": BROWSER_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
        }
    )
    symbol = str(asset["symbol"])
    payload = request_json(
        session,
        "GET",
        YAHOO_CHART.format(symbol=quote(symbol, safe="")),
        params={
            "range": range_value,
            "interval": "1d",
            "events": "div,splits",
            "includePrePost": "false",
        },
        attempts=3,
        timeout=30,
    )
    result = (((payload or {}).get("chart") or {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"Yahoo chart returned no result for {symbol}")

    meta = result.get("meta") or {}
    timestamps = result.get("timestamp") or []
    quote_row = (((result.get("indicators") or {}).get("quote") or [{}])[0])
    closes_raw = quote_row.get("close") or []
    opens = quote_row.get("open") or []
    highs = quote_row.get("high") or []
    lows = quote_row.get("low") or []
    volumes = quote_row.get("volume") or []
    history: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        close = closes_raw[index] if index < len(closes_raw) else None
        if close is None:
            continue
        history.append(
            {
                "date": datetime.fromtimestamp(
                    int(timestamp),
                    tz=timezone.utc,
                ).date().isoformat(),
                "timestamp": int(timestamp),
                "open": opens[index] if index < len(opens) else None,
                "high": highs[index] if index < len(highs) else None,
                "low": lows[index] if index < len(lows) else None,
                "close": round(float(close), 6),
                "volume": volumes[index] if index < len(volumes) else None,
            }
        )
    if len(history) < 2:
        raise RuntimeError(f"Yahoo chart returned insufficient history for {symbol}")

    history_source = "Yahoo Finance Chart"
    naver_symbol = {"kospi": "KOSPI", "kosdaq": "KOSDAQ"}.get(
        str(asset.get("id"))
    )
    if naver_symbol:
        naver_history = fetch_naver_index_history(
            session,
            naver_symbol,
            history[0]["date"],
            datetime.now(KST).date().isoformat(),
        )
        history = merge_history(history, naver_history)
        history_source = "Naver Finance index daily + Yahoo Finance history"

    closes = [float(row["close"]) for row in history]
    # Yahoo의 chartPreviousClose는 요청 range 시작 직전 값일 수 있으므로
    # 일간 등락에는 마지막 두 유효 일봉 종가를 사용한다.
    current = closes[-1]
    previous_close = closes[-2]
    change = float(current) - float(previous_close)

    return {
        **asset,
        "currency": meta.get("currency") or "USD",
        "exchange": meta.get("exchangeName"),
        "timezone": meta.get("exchangeTimezoneName"),
        "market_state": meta.get("marketState"),
        "history_source": history_source,
        "current": round(float(current), 6),
        "previous_close": round(float(previous_close), 6),
        "change": round(change, 6),
        "change_pct": pct_change(float(current), float(previous_close)),
        "latest_date": history[-1]["date"],
        "returns": {
            "1w": history_return(closes, 5),
            "1m": history_return(closes, 21),
            "3m": history_return(closes, 63),
            "6m": history_return(closes, 126),
            "1y": history_return(closes, 252),
        },
        "history": history,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Collect daily charts for major U.S./Korean indices and BTC/ETH "
            "from Yahoo Finance Chart."
        )
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--range", dest="range_value", default="2y")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    print(
        f"[MARKET CHARTS] Collecting {len(ASSETS)} assets "
        f"(range={args.range_value})",
        flush=True,
    )
    rows_by_id: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(fetch_asset, asset, args.range_value): asset
            for asset in ASSETS
        }
        for index, future in enumerate(as_completed(futures), start=1):
            asset = futures[future]
            try:
                row = future.result()
                rows_by_id[str(asset["id"])] = row
                print(
                    f"[MARKET CHARTS] {index}/{len(ASSETS)} OK "
                    f"{asset['name']} {row['current']:,.2f} "
                    f"({row['change_pct']:+.2f}%)",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001
                errors[str(asset["id"])] = str(exc)
                print(
                    f"[MARKET CHARTS] {index}/{len(ASSETS)} FAIL "
                    f"{asset['name']}: {exc}",
                    flush=True,
                )

    assets = [
        rows_by_id[str(asset["id"])]
        for asset in ASSETS
        if str(asset["id"]) in rows_by_id
    ]
    if not assets:
        raise SystemExit("No market index or crypto chart was collected.")

    payload = {
        "schema_version": 1,
        "source": "Yahoo Finance Chart + Naver Finance index daily",
        "source_url": "https://finance.yahoo.com/",
        "source_urls": [
            "https://finance.yahoo.com/",
            "https://finance.naver.com/sise/",
        ],
        "crawled_at_utc": utc_now_iso(),
        "range": args.range_value,
        "count": len(assets),
        "errors": errors,
        "assets": assets,
    }
    atomic_write_json(Path(args.output), payload, compact=True)
    print(f"Output: {args.output}", flush=True)
    print(
        f"Assets: {len(assets)}/{len(ASSETS)}, errors: {len(errors)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
