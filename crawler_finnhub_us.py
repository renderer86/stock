from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

from collector_common import USER_AGENT, atomic_write_json, utc_now_iso
from env_loader import load_env_file


ROOT_DIR = Path(__file__).resolve().parent
BASE_URL = "https://finnhub.io/api/v1"
DEFAULT_INPUT = Path("data/us_market_snapshot.json")
DEFAULT_OUTPUT = Path("data/us_finnhub.json")

ENDPOINTS = {
    "profile": ("stock/profile2", {}),
    "metrics": ("stock/metric", {"metric": "all"}),
    "recommendations": ("stock/recommendation", {}),
    "earnings_surprises": ("stock/earnings", {"limit": 12}),
}


class PacedClient:
    def __init__(self, api_key: str, interval: float) -> None:
        self.api_key = api_key
        self.interval = interval
        self.last_request = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": USER_AGENT, "Accept": "application/json"}
        )

    def get(self, endpoint: str, params: dict[str, Any]) -> Any:
        wait = self.interval - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        response = self.session.get(
            f"{BASE_URL}/{endpoint}",
            params={**params, "token": self.api_key},
            timeout=30,
        )
        self.last_request = time.monotonic()
        if response.status_code == 429:
            time.sleep(60)
            response = self.session.get(
                f"{BASE_URL}/{endpoint}",
                params={**params, "token": self.api_key},
                timeout=30,
            )
            self.last_request = time.monotonic()
        response.raise_for_status()
        return response.json()


def load_symbols(path: Path, limit: int) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("stocks") or []
    symbols: list[str] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
        if limit > 0 and len(symbols) >= limit:
            break
    return symbols


def load_existing(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("stocks") or {}
    except (OSError, ValueError):
        return {}


def main() -> None:
    load_env_file(ROOT_DIR / ".env")
    parser = argparse.ArgumentParser(
        description="Collect Finnhub company metrics, analyst recommendations, and EPS surprises."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--interval",
        type=float,
        default=1.05,
        help="Minimum seconds between API requests.",
    )
    args = parser.parse_args()

    api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("FINNHUB_API_KEY is not set.")

    symbols = load_symbols(Path(args.input), args.limit)
    if not symbols:
        raise SystemExit(f"No symbols found in {args.input}. Run crawler_us_market.py first.")

    client = PacedClient(api_key, max(0.0, args.interval))
    existing = load_existing(Path(args.output))
    collected: dict[str, Any] = {}
    errors: dict[str, dict[str, str]] = {}

    for index, symbol in enumerate(symbols, start=1):
        row: dict[str, Any] = {"symbol": symbol}
        symbol_errors: dict[str, str] = {}
        for field, (endpoint, extra_params) in ENDPOINTS.items():
            try:
                row[field] = client.get(endpoint, {"symbol": symbol, **extra_params})
            except (requests.RequestException, ValueError) as exc:
                symbol_errors[field] = str(exc)
        if len(row) > 1:
            collected[symbol] = {**(existing.get(symbol) or {}), **row}
        elif symbol in existing:
            collected[symbol] = existing[symbol]
        if symbol_errors:
            errors[symbol] = symbol_errors
        if index % 10 == 0 or index == len(symbols):
            print(f"[Finnhub] {index}/{len(symbols)}")

    payload = {
        "source": "Finnhub API",
        "endpoints": {key: value[0] for key, value in ENDPOINTS.items()},
        "crawled_at_utc": utc_now_iso(),
        "universe_count": len(symbols),
        "count": len(collected),
        "errors": errors,
        "stocks": collected,
    }
    atomic_write_json(Path(args.output), payload, compact=True)
    print(f"Output: {args.output}")
    print(f"Stocks: {len(collected)}, symbols with errors: {len(errors)}")


if __name__ == "__main__":
    main()
