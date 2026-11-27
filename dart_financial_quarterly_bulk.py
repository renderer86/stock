"""Adapt quarterly bulk TXT tables to the existing interim calculation schema."""
from __future__ import annotations

from collections import defaultdict
import re
from pathlib import Path

from crawler_dart_financial_bulk import (
    BULK_MAIN_URL,
    STATEMENT_CODES,
    download_bulk_zip,
    fetch_bulk_listing,
    parse_bulk_archive,
)
from dart_financial_raw_storage import bulk_group_tables, load_bulk_raw_statement, write_bulk_raw_shards
from stock_codes import normalize_stock_code


BULK_PERIODS = {"11013": "FQ", "11012": "HY", "11014": "TQ"}
REPORT_NAMES = {"11013": "1분기보고서", "11012": "반기보고서", "11014": "3분기보고서"}


def quarterly_calculation_rows(raw_groups: dict, statement: str, *, year: int, report_code: str, period_end: str) -> dict:
    """Keep three-month income, cumulative income and comparative CF distinct."""
    grouped = defaultdict(list)
    for (basis, _bucket), group in raw_groups.items():
        for table in bulk_group_tables(group):
            header = [re.sub(r"\s+", "", str(x)).lstrip("\ufeff") for x in table.get("header", [])]
            current = next((i for i, name in enumerate(header) if i >= 12 and name.startswith("당기")), None)
            if current is None:
                continue
            cumulative = next((i for i, name in enumerate(header) if name.startswith("당기") and "누적" in name), None)
            prior_cumulative = next((i for i, name in enumerate(header) if name.startswith("전기") and "누적" in name), None)
            prior_quarter = next((i for i, name in enumerate(header) if name.startswith("전기") and ("분기" in name or "반기" in name) and "누적" not in name and "말" not in name), None)
            for values in table.get("rows", []):
                if len(values) <= max(11, current):
                    continue
                ticker = normalize_stock_code(values[1])
                # Non-December issuers and foreign currencies stay in the raw archive.
                if not ticker or str(values[7]).strip() != period_end or str(values[8]).strip() != REPORT_NAMES[report_code] or str(values[9]).strip() != "KRW":
                    continue
                def cell(index):
                    return str(values[index]).strip() if index is not None and index < len(values) else None

                row = {"sj_div": {"PL": "IS", "CE": "SCE"}.get(statement, statement), "account_id": str(values[10]).strip(), "account_nm": str(values[11]).strip(), "thstrm_amount": cell(current), "thstrm_add_amount": cell(cumulative), "frmtrm_q_amount": cell(prior_quarter), "frmtrm_add_amount": cell(prior_cumulative), "currency": "KRW", "bsns_year": str(year), "reprt_code": report_code}
                if statement == "PL" and report_code == "11013":
                    row["thstrm_add_amount"] = row["thstrm_add_amount"] or row["thstrm_amount"]
                    row["frmtrm_add_amount"] = row["frmtrm_add_amount"] or row["frmtrm_q_amount"]
                # Missing current amounts remain unknown, not zero.
                if row["account_id"] and (row["thstrm_amount"] or row["thstrm_add_amount"]):
                    grouped[(ticker, basis)].append(row)
    return dict(grouped)


def load_quarterly_bulk(session, raw_root: Path, *, year: int, report_code: str, period_end: str, on_statement) -> tuple[dict, dict, dict]:
    """Reuse source fingerprints; save each ZIP's lossless rows before continuing."""
    listing = fetch_bulk_listing(session, timeout=180, period=BULK_PERIODS[report_code])
    grouped, references, sources = defaultdict(list), {}, {}
    for statement in STATEMENT_CODES:
        filename = listing.get((year, statement))
        if not filename:
            raise RuntimeError(f"Quarterly bulk {year}/{statement} is not available yet")
        scoped_statement = f"{report_code}_{statement}"
        cached = load_bulk_raw_statement(raw_root, year=year, statement=scoped_statement, source_file=filename)
        if cached:
            raw_groups, statement_refs, _entries = cached
            print(f"[QUARTERLY ZIP] {statement}: reused {filename}", flush=True)
        else:
            content = download_bulk_zip(session, filename, timeout=180, attempts=1)
            _, raw_groups, _metadata = parse_bulk_archive(content, statement)
            _, statement_refs = write_bulk_raw_shards(raw_root, year=year, statement=scoped_statement, source_file=filename, raw_groups=raw_groups)
            print(f"[QUARTERLY ZIP] {statement}: imported {filename} ({len(content):,} bytes)", flush=True)
        for key, rows in quarterly_calculation_rows(raw_groups, statement, year=year, report_code=report_code, period_end=period_end).items():
            grouped[key].extend(rows)
        for ticker, bases in statement_refs.items():
            for basis, refs in bases.items():
                references.setdefault(ticker, {}).setdefault(basis, {})[statement] = refs[scoped_statement]
        sources[statement] = filename
        on_statement(statement, filename)
    return dict(grouped), references, sources


def bulk_gap_reasons(report: dict, *, is_financial: bool) -> list[str]:
    statements = set(report.get("available_statements", []))
    missing = [f"statement:{s}" for s in ("BS", "CF") if s not in statements]
    if not statements.intersection({"IS", "CIS"}):
        missing.append("statement:IS")
    accounts = report.get("accounts", {})
    missing.extend(f"account:{key}" for key in ("assets", "equity", "net_income") if accounts.get(key) is None)
    if not is_financial:
        for side in ("current", "previous"):
            missing.extend(f"{side}:{key}" for key in ("operating_cash_flow", "capex_ppe", "capex_intangibles", "lease_principal_paid") if report.get(side, {}).get(key) is None)
    return missing
