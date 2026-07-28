from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import requests

from collector_common import atomic_write_json, request_json, utc_now_iso


TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
DEFAULT_INPUT = Path("data/us_market_snapshot.json")
DEFAULT_OUTPUT = Path("data/us_sec_filings.json")
SEC_USER_AGENT = (
    "renderer86-stock-data/1.0 renderer86@users.noreply.github.com"
)

FORM_CATEGORIES = {
    "insider": {"3", "3/A", "4", "4/A", "5", "5/A"},
    "activist_stakes": {
        "SC 13D",
        "SC 13D/A",
        "SC 13G",
        "SC 13G/A",
    },
    "material_events": {"8-K", "8-K/A", "6-K", "6-K/A"},
    "ipo": {"S-1", "S-1/A", "F-1", "F-1/A", "424B4"},
}


def load_symbols(path: Path, limit: int) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    symbols: list[str] = []
    for row in payload.get("stocks") or []:
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
        if limit > 0 and len(symbols) >= limit:
            break
    return symbols


def filing_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    recent = ((payload.get("filings") or {}).get("recent") or {})
    keys = [
        "accessionNumber",
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "act",
        "form",
        "fileNumber",
        "filmNumber",
        "items",
        "size",
        "isXBRL",
        "isInlineXBRL",
        "primaryDocument",
        "primaryDocDescription",
    ]
    length = len(recent.get("accessionNumber") or [])
    return [
        {key: (recent.get(key) or [None] * length)[index] for key in keys}
        for index in range(length)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect official SEC insider, 13D/G, 8-K, and IPO filing metadata."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--per-company", type=int, default=50)
    parser.add_argument("--interval", type=float, default=0.22)
    args = parser.parse_args()

    symbols = load_symbols(Path(args.input), args.limit)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": SEC_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        }
    )
    ticker_payload = request_json(session, "GET", TICKERS_URL, timeout=60)
    ticker_map = {
        str(row.get("ticker") or "").upper(): int(row["cik_str"])
        for row in ticker_payload.values()
        if row.get("ticker") and row.get("cik_str") is not None
    }

    categories: dict[str, list[dict[str, Any]]] = {
        name: [] for name in FORM_CATEGORIES
    }
    companies: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for index, symbol in enumerate(symbols, start=1):
        cik = ticker_map.get(symbol) or ticker_map.get(symbol.replace(".", "-"))
        if cik is None:
            errors[symbol] = "CIK not found"
            continue
        try:
            payload = request_json(
                session,
                "GET",
                SUBMISSIONS_URL.format(cik=cik),
                attempts=2,
                timeout=30,
            )
            companies[symbol] = {
                "cik": cik,
                "name": payload.get("name"),
                "sic": payload.get("sic"),
                "sic_description": payload.get("sicDescription"),
                "exchanges": payload.get("exchanges"),
            }
            used = 0
            for row in filing_rows(payload):
                form = str(row.get("form") or "")
                matched = [
                    name for name, forms in FORM_CATEGORIES.items() if form in forms
                ]
                if not matched:
                    continue
                accession = str(row.get("accessionNumber") or "")
                primary_document = str(row.get("primaryDocument") or "")
                accession_path = accession.replace("-", "")
                filing = {
                    **row,
                    "symbol": symbol,
                    "company": payload.get("name"),
                    "cik": cik,
                    "categories": matched,
                    "filing_url": (
                        "https://www.sec.gov/Archives/edgar/data/"
                        f"{cik}/{accession_path}/{primary_document}"
                    ),
                }
                for category in matched:
                    categories[category].append(filing)
                used += 1
                if args.per_company > 0 and used >= args.per_company:
                    break
        except Exception as exc:  # noqa: BLE001
            errors[symbol] = str(exc)
        time.sleep(max(0.0, args.interval))
        if index % 20 == 0 or index == len(symbols):
            print(f"[SEC] {index}/{len(symbols)}")

    for rows in categories.values():
        rows.sort(key=lambda row: str(row.get("filingDate") or ""), reverse=True)
    payload = {
        "source": "SEC EDGAR Submissions API",
        "crawled_at_utc": utc_now_iso(),
        "universe_count": len(symbols),
        "company_count": len(companies),
        "category_counts": {name: len(rows) for name, rows in categories.items()},
        "companies": companies,
        "filings": categories,
        "errors": errors,
    }
    atomic_write_json(Path(args.output), payload, compact=True)
    print(f"Output: {args.output}")
    print(f"Companies: {len(companies)}, errors: {len(errors)}")


if __name__ == "__main__":
    main()
