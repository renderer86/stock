from __future__ import annotations

import argparse
import csv
import io
import re
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from collector_common import utc_now_iso
from crawler_dart_financial_details import (
    derive_row_metrics,
    load_market_lookup,
    rebuild_screening_features,
    standardize_accounts,
    update_detail_summary,
)
from dart_financial_storage import load_financial_panel, save_financial_panel


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_PANEL = Path("data/dart_financial_panel.json")
DEFAULT_MARKET_SUM = Path("data/market_sum.json")
BULK_MAIN_URL = "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do"
BULK_LIST_URL = "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do"
BULK_DOWNLOAD_URL = "https://opendart.fss.or.kr/cmm/downloadFnlttZip.do"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138 Safari/537.36"
)
KST = ZoneInfo("Asia/Seoul")
STATEMENT_CODES = ("BS", "PL", "CF")


def parse_args() -> argparse.Namespace:
    current_year = datetime.now(KST).year
    parser = argparse.ArgumentParser(
        description=(
            "Download OpenDART annual bulk financial-statement ZIP files and "
            "merge standardized accounts into the local year-sharded panel."
        )
    )
    parser.add_argument("--panel", default=str(DEFAULT_PANEL))
    parser.add_argument("--market-sum", default=str(DEFAULT_MARKET_SUM))
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--start-year", type=int, default=0)
    parser.add_argument("--end-year", type=int, default=current_year - 1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--codes", default="")
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--refresh-latest", action="store_true")
    parser.add_argument(
        "--reset-bulk",
        action="store_true",
        help="Discard prior full-statement detail fields before importing ZIP data.",
    )
    parser.add_argument(
        "--include-equity-changes",
        action="store_true",
        help="Also download CE files for provenance; current screens do not require them.",
    )
    return parser.parse_args()


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": BROWSER_USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )
    return session


def parse_bulk_listing(html: str) -> dict[tuple[int, str], str]:
    pattern = re.compile(
        r"download_ext002\(\s*'(?P<year>20\d{2})'\s*,\s*'FY'\s*,\s*"
        r"'(?P<statement>BS|PL|CF|CE)'\s*,\s*'(?P<file>[^']+)'",
        re.IGNORECASE,
    )
    return {
        (int(match.group("year")), match.group("statement").upper()): match.group(
            "file"
        )
        for match in pattern.finditer(html)
    }


def fetch_bulk_listing(session: requests.Session, timeout: float) -> dict[tuple[int, str], str]:
    session.get(BULK_MAIN_URL, timeout=timeout).raise_for_status()
    response = session.get(
        BULK_LIST_URL,
        headers={"Referer": BULK_MAIN_URL, "X-Requested-With": "XMLHttpRequest"},
        timeout=timeout,
    )
    response.raise_for_status()
    listing = parse_bulk_listing(response.text)
    if not listing:
        raise RuntimeError("OpenDART bulk download listing did not contain annual files.")
    return listing


def download_bulk_zip(
    session: requests.Session,
    filename: str,
    *,
    timeout: float,
    attempts: int = 4,
) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(
                BULK_DOWNLOAD_URL,
                params={"fl_nm": filename},
                headers={
                    "Referer": BULK_MAIN_URL,
                    "Accept": "application/zip,application/octet-stream,*/*",
                },
                timeout=timeout,
            )
            response.raise_for_status()
            content = response.content
            if not content.startswith(b"PK"):
                content_type = response.headers.get("Content-Type", "unknown")
                raise RuntimeError(
                    f"OpenDART returned {content_type} instead of ZIP for {filename}."
                )
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if not archive.namelist():
                    raise RuntimeError(f"OpenDART ZIP is empty: {filename}")
            return content
        except (requests.RequestException, RuntimeError, zipfile.BadZipFile) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"Failed to download {filename}: {last_error}") from last_error


def decode_bulk_text(raw: bytes) -> str:
    for encoding in ("cp949", "utf-8-sig", "euc-kr"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp949", errors="replace")


def normalize_ticker(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-6:].zfill(6) if digits else ""


def _current_amount_index(header: list[str]) -> int:
    for index, name in enumerate(header):
        normalized = re.sub(r"\s+", "", name)
        if index >= 12 and normalized.startswith("당기"):
            return index
    return 12


def parse_bulk_archive(
    content: bytes,
    statement: str,
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[str, Any]]:
    """Return full-statement API-shaped rows keyed by (ticker, CFS/OFS)."""

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    entry_counts: dict[str, int] = {}
    api_statement = "IS" if statement == "PL" else statement
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for entry in archive.infolist():
            if entry.is_dir() or not entry.filename.lower().endswith(".txt"):
                continue
            text = decode_bulk_text(archive.read(entry))
            reader = csv.reader(io.StringIO(text), delimiter="\t")
            try:
                header = [value.strip().lstrip("\ufeff") for value in next(reader)]
            except StopIteration:
                continue
            amount_index = _current_amount_index(header)
            count = 0
            for values in reader:
                if len(values) <= max(11, amount_index):
                    continue
                ticker = normalize_ticker(values[1])
                account_id = values[10].strip()
                account_name = values[11].strip()
                amount = values[amount_index].strip()
                if not ticker or not account_id or not amount:
                    continue
                statement_name = values[0].strip()
                basis = "CFS" if "연결" in statement_name else "OFS"
                grouped[(ticker, basis)].append(
                    {
                        "sj_div": api_statement,
                        "account_id": account_id,
                        "account_nm": account_name,
                        "thstrm_amount": amount,
                    }
                )
                count += 1
            entry_counts[entry.filename] = count
    return grouped, {"entries": entry_counts, "row_count": sum(entry_counts.values())}


def _clear_bulk_detail(row: dict[str, Any]) -> None:
    for key in (
        "detail_status",
        "detail_basis",
        "detail_source",
        "detail_accounts",
        "detail_account_matches",
        "detail_match_summary",
        "detail_alias_matches",
        "detail_metrics",
        "detail_updated_at_utc",
        "detail_bulk_files",
        "detail_crosscheck",
    ):
        row.pop(key, None)


def merge_bulk_year(
    observations: list[dict[str, Any]],
    year: int,
    grouped: dict[tuple[str, str], list[dict[str, Any]]],
    filenames: list[str],
    *,
    allowed_codes: set[str] | None = None,
    reset_bulk: bool = False,
) -> dict[str, int]:
    counts = Counter()
    for row in observations:
        if int(row.get("fiscal_year") or 0) != year:
            continue
        ticker = normalize_ticker(row.get("ticker"))
        if allowed_codes and ticker not in allowed_codes:
            continue
        if reset_bulk:
            _clear_bulk_detail(row)

        candidates = [
            basis for basis in ("CFS", "OFS") if grouped.get((ticker, basis))
        ]
        selected_basis = (
            max(
                candidates,
                key=lambda basis: (
                    len(
                        {
                            item.get("sj_div")
                            for item in grouped[(ticker, basis)]
                            if item.get("sj_div")
                        }
                    ),
                    basis == "CFS",
                    len(grouped[(ticker, basis)]),
                ),
            )
            if candidates
            else ""
        )
        payload_rows = grouped.get((ticker, selected_basis), [])
        if not payload_rows:
            if row.get("detail_status") in {"complete", "no_data"}:
                counts["api_fallback_retained"] += 1
            else:
                row["detail_status"] = "bulk_no_data"
                row["detail_source"] = "bulk_zip"
                row["detail_updated_at_utc"] = utc_now_iso()
                counts["no_data"] += 1
            continue

        bulk_values, matches = standardize_accounts(payload_rows)
        existing_values = dict(row.get("detail_accounts") or {})
        existing_source = str(row.get("detail_source") or "")
        if existing_values and not existing_source.startswith("bulk_zip"):
            overlapping_keys = sorted(set(existing_values) & set(bulk_values))
            mismatch_keys = [
                key
                for key in overlapping_keys
                if existing_values.get(key) != bulk_values.get(key)
            ]
            row["detail_crosscheck"] = {
                "source": existing_source or "legacy_api",
                "overlap_count": len(overlapping_keys),
                "exact_match_count": len(overlapping_keys) - len(mismatch_keys),
                "mismatch_count": len(mismatch_keys),
                "mismatch_accounts": mismatch_keys,
            }
            counts["crosschecked_fields"] += len(overlapping_keys)
            counts["crosscheck_mismatches"] += len(mismatch_keys)
        api_fallbacks = {
            key: value
            for key, value in existing_values.items()
            if key not in bulk_values and value is not None
        }
        merged_values = {**api_fallbacks, **bulk_values}
        row["detail_status"] = "complete"
        row["detail_basis"] = selected_basis
        row["detail_source"] = (
            "bulk_zip+fallback" if api_fallbacks else "bulk_zip"
        )
        row["detail_accounts"] = merged_values
        row.pop("accounts", None)
        row.pop("detail_account_matches", None)
        row["detail_match_summary"] = dict(
            sorted(
                Counter(
                    match.get("match") or "unknown" for match in matches.values()
                ).items()
            )
        )
        alias_matches = {
            key: {
                "match": match.get("match"),
                "account_name": match.get("account_name"),
                "formula": match.get("formula"),
            }
            for key, match in matches.items()
            if match.get("match") != "account_id"
        }
        if alias_matches:
            row["detail_alias_matches"] = alias_matches
        else:
            row.pop("detail_alias_matches", None)
        row["detail_bulk_files"] = filenames
        row["detail_updated_at_utc"] = utc_now_iso()
        derive_row_metrics(row)
        counts["complete"] += 1
        if api_fallbacks:
            counts["api_fallback_fields"] += len(api_fallbacks)
    return dict(counts)


def main() -> None:
    args = parse_args()
    panel_path = Path(args.panel)
    panel = load_financial_panel(panel_path)
    observations = panel.get("observations") or []
    if not observations:
        raise SystemExit(
            "The core DART panel is missing or empty. Run "
            "crawler_dart_financial_panel.py first."
        )

    panel_period = panel.get("period") or {}
    end_year = min(args.end_year, int(panel_period.get("end_year") or args.end_year))
    start_year = args.start_year or end_year - max(args.years, 1) + 1
    start_year = max(start_year, int(panel_period.get("start_year") or start_year))
    years = [end_year] if args.refresh_latest else list(range(start_year, end_year + 1))
    requested_codes = {
        normalize_ticker(value) for value in args.codes.split(",") if value.strip()
    }
    if args.limit > 0 and not requested_codes:
        requested_codes = set(
            sorted({normalize_ticker(row.get("ticker")) for row in observations})[
                : args.limit
            ]
        )

    session = create_session()
    listing = fetch_bulk_listing(session, args.timeout)
    statement_codes = list(STATEMENT_CODES)
    if args.include_equity_changes:
        statement_codes.append("CE")
    missing_files = [
        f"{year}/{statement}"
        for year in years
        for statement in statement_codes
        if (year, statement) not in listing
    ]
    if missing_files:
        raise SystemExit(
            "OpenDART bulk listing is missing required annual files: "
            + ", ".join(missing_files)
        )

    prior_year_results = (
        (panel.get("bulk_financial_enrichment") or {}).get("year_results") or {}
    )
    if not args.reset_bulk and not args.refresh_latest and not requested_codes:
        pending_years = []
        for year in years:
            prior_sources = (prior_year_results.get(str(year)) or {}).get(
                "sources"
            ) or {}
            unchanged = all(
                (prior_sources.get(statement) or {}).get("filename")
                == listing[(year, statement)]
                for statement in STATEMENT_CODES
            )
            year_rows = [
                row
                for row in observations
                if int(row.get("fiscal_year") or 0) == year
            ]
            detail_present = bool(year_rows) and all(
                row.get("detail_status")
                in {"complete", "no_data", "bulk_no_data"}
                for row in year_rows
            )
            if unchanged and detail_present:
                print(
                    f"[DART BULK] {year}: current ZIP fingerprints already imported",
                    flush=True,
                )
            else:
                pending_years.append(year)
        years = pending_years

    if not years:
        save_financial_panel(panel_path, panel, split_by_year=True)
        print(
            "[DART BULK] all requested annual ZIP files are already current.",
            flush=True,
        )
        return

    company_scope = "all" if not requested_codes else f"{len(requested_codes):,}"
    print(
        f"[DART BULK] years {years[0]}-{years[-1]} | "
        f"ZIP files {len(years) * len(statement_codes):,} | "
        f"companies {company_scope}",
        flush=True,
    )
    started_at = time.monotonic()
    year_results: dict[str, Any] = {}
    for year_index, year in enumerate(years, start=1):
        combined: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        filenames: list[str] = []
        source_summaries: dict[str, Any] = {}
        for statement_index, statement in enumerate(statement_codes, start=1):
            filename = listing[(year, statement)]
            print(
                f"[DART BULK] {year} ({year_index}/{len(years)}) "
                f"{statement} ({statement_index}/{len(statement_codes)}) "
                f"downloading {filename}",
                flush=True,
            )
            content = download_bulk_zip(
                session,
                filename,
                timeout=args.timeout,
            )
            filenames.append(filename)
            if statement != "CE":
                parsed, parse_summary = parse_bulk_archive(content, statement)
                for key, rows in parsed.items():
                    combined[key].extend(rows)
                source_summaries[statement] = {
                    "filename": filename,
                    "compressed_bytes": len(content),
                    **parse_summary,
                }
            if args.delay > 0:
                time.sleep(args.delay)

        result = merge_bulk_year(
            observations,
            year,
            combined,
            filenames,
            allowed_codes=requested_codes or None,
            reset_bulk=args.reset_bulk,
        )
        year_results[str(year)] = {"merge": result, "sources": source_summaries}
        print(
            f"[DART BULK] {year} merged | {result} | "
            f"elapsed {time.monotonic() - started_at:.1f}s",
            flush=True,
        )

    market_lookup, market_as_of = load_market_lookup(Path(args.market_sum))
    rebuild_screening_features(panel, market_lookup, market_as_of)
    update_detail_summary(
        panel,
        request_count=0,
        errors=[],
        eligible_rows=observations,
        budget_reached=False,
    )
    all_year_results = dict(prior_year_results)
    all_year_results.update(year_results)
    recorded_years = sorted(int(year) for year in all_year_results)
    panel["bulk_financial_enrichment"] = {
        "schema_version": 1,
        "source": "OpenDART financial information bulk download",
        "source_url": BULK_MAIN_URL,
        "updated_at_utc": utc_now_iso(),
        "period": {
            "start_year": recorded_years[0] if recorded_years else years[0],
            "end_year": recorded_years[-1] if recorded_years else years[-1],
        },
        "statement_codes": statement_codes,
        "download_count_this_run": len(years) * len(statement_codes),
        "temporary_zip_retention": False,
        "statement_preference": "CFS first, OFS fallback",
        "year_results": all_year_results,
    }
    save_financial_panel(panel_path, panel, split_by_year=True)
    complete = sum(
        row.get("detail_status") == "complete"
        for row in observations
        if start_year <= int(row.get("fiscal_year") or 0) <= end_year
    )
    print(
        f"[DART BULK] saved {panel_path} as year shards | "
        f"detail-complete rows {complete:,}/{len(observations):,}",
        flush=True,
    )


if __name__ == "__main__":
    main()
