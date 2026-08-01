from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from collector_common import atomic_write_json, utc_now_iso
from env_loader import load_env_file
from sec_edgar_client import SecAccessError, SecEdgarClient


ROOT_DIR = Path(__file__).resolve().parent
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
DEFAULT_INPUT = Path("data/us_market_snapshot.json")
DEFAULT_OUTPUT = Path("data/us_sec_filings.json")
DEFAULT_BACKFILL_DAYS = 45
DEFAULT_MAX_RESULTS = 10_000

FORM_CATEGORIES = {
    "insider": ("4", "4/A", "3", "3/A", "5", "5/A"),
    "activist_stakes": (
        "SCHEDULE 13D",
        "SCHEDULE 13D/A",
        "SCHEDULE 13G",
        "SCHEDULE 13G/A",
    ),
    "material_events": ("8-K", "8-K/A", "6-K", "6-K/A"),
    "ipo": ("S-1", "S-1/A", "F-1", "F-1/A", "424B4"),
}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def load_symbols(path: Path, limit: int) -> list[str]:
    payload = load_json(path)
    symbols: list[str] = []
    for row in payload.get("stocks") or []:
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
        if limit > 0 and len(symbols) >= limit:
            break
    return symbols


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def company_maps(
    payload: Any,
) -> tuple[dict[str, dict[str, Any]], dict[int, str]]:
    by_symbol: dict[str, dict[str, Any]] = {}
    by_cik: dict[int, str] = {}
    rows = payload.values() if isinstance(payload, dict) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = normalize_symbol(str(row.get("ticker") or ""))
        try:
            cik = int(row.get("cik_str") or 0)
        except (TypeError, ValueError):
            continue
        if not ticker or cik <= 0:
            continue
        by_symbol.setdefault(
            ticker,
            {
                "cik": cik,
                "name": str(row.get("title") or "").strip(),
            },
        )
        by_cik.setdefault(cik, ticker)
    return by_symbol, by_cik


def scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def source_ciks(source: dict[str, Any]) -> list[int]:
    values = source.get("ciks") or []
    if not isinstance(values, list):
        values = [values]
    result: list[int] = []
    for value in values:
        try:
            cik = int(value)
        except (TypeError, ValueError):
            continue
        if cik > 0 and cik not in result:
            result.append(cik)
    return result


def subject_ciks(source: dict[str, Any], category: str) -> list[int]:
    ciks = source_ciks(source)
    if category == "activist_stakes":
        # EFTS lists the subject company first and Schedule 13 filers after it.
        return ciks[:1]
    if category == "insider":
        # EFTS lists reporting owners first and the issuer last for Forms 3/4/5.
        return ciks[-1:]
    return ciks


def company_name(source: dict[str, Any], cik: int, fallback: str) -> str:
    ciks = source_ciks(source)
    names = source.get("display_names") or []
    if not isinstance(names, list):
        names = [names]
    try:
        name = str(names[ciks.index(cik)] or "")
    except (ValueError, IndexError):
        name = fallback
    name = re.sub(r"\s*\(CIK\s*\d+\)\s*$", "", name).strip()
    name = re.sub(r"\s+\([A-Z][A-Z0-9.-]{0,9}\)\s*$", "", name).strip()
    return name or fallback


def filing_url(source: dict[str, Any]) -> str:
    accession = str(source.get("adsh") or "").strip()
    ciks = source_ciks(source)
    if not accession:
        return ""
    try:
        filing_cik = int(accession.split("-", 1)[0])
    except (TypeError, ValueError):
        filing_cik = ciks[0] if ciks else 0
    if filing_cik <= 0:
        return ""
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{filing_cik}/{accession.replace('-', '')}/{accession}-index.html"
    )


def category_rows(
    hits: list[dict[str, Any]],
    category: str,
    universe_ciks: set[int],
    cik_to_symbol: dict[int, str],
    company_metadata: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        source = hit.get("_source") or {}
        if not isinstance(source, dict):
            continue
        matched_ciks = sorted(set(subject_ciks(source, category)) & universe_ciks)
        accession = str(source.get("adsh") or "").strip()
        for cik in matched_ciks:
            symbol = cik_to_symbol.get(cik, "")
            key = (accession, symbol)
            if not symbol or not accession or key in seen:
                continue
            seen.add(key)
            fallback_name = str(company_metadata.get(symbol, {}).get("name") or symbol)
            rows.append(
                {
                    "accessionNumber": accession,
                    "filingDate": source.get("file_date"),
                    "reportDate": source.get("period_ending"),
                    "acceptanceDateTime": None,
                    "act": None,
                    "form": source.get("form"),
                    "fileNumber": scalar(source.get("file_num")),
                    "filmNumber": scalar(source.get("film_num")),
                    "items": source.get("items") or [],
                    "size": None,
                    "isXBRL": None,
                    "isInlineXBRL": None,
                    "primaryDocument": "",
                    "primaryDocDescription": source.get("file_description"),
                    "symbol": symbol,
                    "company": company_name(source, cik, fallback_name),
                    "cik": cik,
                    "categories": [category],
                    "filing_url": filing_url(source),
                }
            )
    rows.sort(
        key=lambda row: (
            str(row.get("filingDate") or ""),
            str(row.get("accessionNumber") or ""),
        ),
        reverse=True,
    )
    return rows


def efts_hits(
    client: SecEdgarClient,
    forms: tuple[str, ...],
    start_date: str,
    end_date: str,
    max_results: int,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    per_form_cap = max(1, max_results)
    # EFTS treats a comma-delimited forms value as a literal/combined search,
    # not as an OR expression. Query each form independently and de-duplicate
    # amendments/results by accession and exact form.
    for form in forms:
        offset = 0
        form_count = 0
        while form_count < per_form_cap:
            payload = client.get_json(
                EFTS_URL,
                params={
                    "q": "",
                    "forms": form,
                    "startdt": start_date,
                    "enddt": end_date,
                    "from": offset,
                },
            )
            page = ((payload.get("hits") or {}).get("hits") or [])
            if not page:
                break
            for row in page:
                if not isinstance(row, dict):
                    continue
                source = row.get("_source") or {}
                key = (
                    str(source.get("adsh") or ""),
                    str(source.get("form") or form),
                )
                if key not in seen:
                    seen.add(key)
                    hits.append(row)
                    form_count += 1
                    if form_count >= per_form_cap:
                        break
            total_value = (payload.get("hits") or {}).get("total") or {}
            if isinstance(total_value, dict):
                total = int(total_value.get("value") or 0)
            else:
                total = int(total_value or 0)
            offset += len(page)
            if offset >= total or form_count >= per_form_cap:
                break
    return hits


def main() -> None:
    load_env_file(ROOT_DIR / ".env")
    parser = argparse.ArgumentParser(
        description="Collect recent official SEC filing metadata through EFTS."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--backfill-days", type=int, default=DEFAULT_BACKFILL_DAYS)
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    parser.add_argument("--interval", type=float, default=0.15)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    symbols = load_symbols(input_path, args.limit)
    if not symbols:
        raise SystemExit(f"No U.S. symbols were found in {input_path}.")

    client = SecEdgarClient(min_interval=args.interval)
    ticker_payload = client.get_json(TICKERS_URL)
    metadata_by_symbol, _ = company_maps(ticker_payload)

    selected_metadata: dict[str, dict[str, Any]] = {}
    missing_symbols: list[str] = []
    for original_symbol in symbols:
        symbol = normalize_symbol(original_symbol)
        metadata = metadata_by_symbol.get(symbol)
        if metadata:
            selected_metadata[symbol] = metadata
        else:
            missing_symbols.append(original_symbol)

    universe_ciks = {
        int(metadata["cik"])
        for metadata in selected_metadata.values()
    }
    cik_to_symbol: dict[int, str] = {}
    for symbol, metadata in selected_metadata.items():
        cik_to_symbol.setdefault(int(metadata["cik"]), symbol)

    end = datetime.now(ZoneInfo("America/New_York")).date()
    start = end - timedelta(days=max(0, args.backfill_days))
    start_date = start.isoformat()
    end_date = end.isoformat()
    existing = load_json(output_path)
    existing_filings = existing.get("filings") or {}

    filings: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    retained_categories: list[str] = []
    query_counts: dict[str, int] = {}
    successful_queries = 0

    for category, forms in FORM_CATEGORIES.items():
        try:
            hits = efts_hits(
                client,
                forms,
                start_date,
                end_date,
                max(1, args.max_results),
            )
            rows = category_rows(
                hits,
                category,
                universe_ciks,
                cik_to_symbol,
                selected_metadata,
            )
            filings[category] = rows
            query_counts[category] = len(hits)
            successful_queries += 1
            print(
                f"[SEC] {category}: {len(hits):,} hits -> "
                f"{len(rows):,} tracked filings",
                flush=True,
            )
        except SecAccessError as exc:
            errors[category] = str(exc)
            previous = existing_filings.get(category)
            filings[category] = previous if isinstance(previous, list) else []
            if previous is not None:
                retained_categories.append(category)
            print(f"[SEC WARNING] {category}: {exc}", flush=True)

    if successful_queries == 0:
        raise RuntimeError(
            "Every SEC category query failed; the existing output was preserved."
        )

    companies = {
        symbol: {
            "cik": metadata["cik"],
            "name": metadata.get("name"),
        }
        for symbol, metadata in selected_metadata.items()
    }
    payload = {
        "source": "SEC EDGAR Full-Text Search and company ticker mapping",
        "crawled_at_utc": utc_now_iso(),
        "period": {"start": start_date, "end": end_date},
        "universe_count": len(symbols),
        "company_count": len(companies),
        "matched_company_count": len(
            {
                row.get("symbol")
                for rows in filings.values()
                for row in rows
                if row.get("symbol")
            }
        ),
        "category_counts": {
            category: len(rows) for category, rows in filings.items()
        },
        "query_hit_counts": query_counts,
        "companies": companies,
        "filings": filings,
        "errors": {
            "missing_cik": missing_symbols,
            "categories": errors,
        },
        "retained_categories": retained_categories,
    }
    atomic_write_json(output_path, payload, compact=True)
    print(f"Output: {output_path}")
    print(
        f"Companies: {len(companies):,}; matched: "
        f"{payload['matched_company_count']:,}; category errors: {len(errors):,}",
        flush=True,
    )


if __name__ == "__main__":
    main()
