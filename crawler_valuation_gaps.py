"""Fetch complete DART statements only for unresolved valuation input gaps."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import requests

from build_valuation_metrics import (RawReports, build_metrics, company_due_period,
                                     get_report, parse_report, read_json, report_period_end)
from collector_common import atomic_write_json, utc_now_iso
from dart_financial_raw_storage import ApiRawAccumulator
from dart_financial_storage import load_financial_panel
from env_loader import load_env_file

ENDPOINT = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
INCOME = {"net_income", "owners_net_income", "continuing_net_income", "discontinued_net_income"}
CAPITAL = {"assets", "equity", "owners_equity"}


def collect(data_dir, as_of, key, *, max_requests=600, codes=None, timeout=45, force=False):
    panel = load_financial_panel(data_dir / "dart_financial_panel.json")
    market = read_json(data_dir / "market_sum.json")
    interim = read_json(data_dir / "dart_financial_interim.json")
    store = RawReports(data_dir)
    metrics = build_metrics(panel, market, interim, store, as_of)["metrics"]
    latest = {}
    for row in sorted(panel.get("observations", []), key=lambda r: r["fiscal_year"]):
        latest[row["ticker"]] = row
    targets = {m.get("financial_ticker", t): m for t, m in metrics.items()
               if ("missing_income" in m["quality_reasons"] or m.get("fiscal_month", 12) != 12)
               and (not codes or m.get("financial_ticker", t) in codes)}
    progress_path = data_dir / "valuation_gap_progress.json"
    progress = read_json(progress_path)
    records = progress.setdefault("reports", {})
    accumulator = ApiRawAccumulator(data_dir / "dart_financial_raw")
    session = requests.Session()
    session.headers["User-Agent"] = "Stock dashboard DART valuation input verification"
    requests_used = 0
    outcomes = {"fetched": 0, "cached": 0, "errors": 0, "no_data": 0}
    exhausted = False

    def save():
        accumulator.flush()
        store.api_cache.clear()
        progress.update(updated_at_utc=utc_now_iso(), source_url=ENDPOINT,
                        last_run={"as_of": as_of.isoformat(), "requests": requests_used,
                                  "targets": len(targets), "outcomes": outcomes})
        atomic_write_json(progress_path, progress, compact=True)

    def report(ticker, year, code, basis, corp, month, fields, comparisons=None):
        nonlocal requests_used, exhausted
        result = get_report(store, year, code, ticker, basis, corp, month) or {}
        amounts = {**result.get("current", {}), **{k: v for k, v in (comparisons or {}).items() if k in INCOME}}
        if all(amounts.get(f) is not None for f in fields):
            return result
        identity = f"{ticker}:{year}:{code}:{basis}"
        prior = records.get(identity, {})
        if prior.get("checked_at_utc") and not force:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(prior["checked_at_utc"])).total_seconds()
            if age < (7 * 86400 if prior.get("status") == "000" else 86400):
                outcomes["cached"] += 1
                return result
        if requests_used >= max_requests or exhausted:
            exhausted = True
            return result
        params = {"corp_code": corp, "bsns_year": str(year), "reprt_code": code, "fs_div": basis}
        requests_used += 1
        try:
            response = session.get(ENDPOINT, params={**params, "crtfc_key": key}, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            payload = {"status": "network_error", "list": []}
        status, rows = payload.get("status"), payload.get("list", [])
        reference = accumulator.add(year=year, dataset=f"valuation_{code}", ticker=ticker,
            corp_code=corp, basis=basis, endpoint=ENDPOINT, request_parameters=params,
            response_status=status, rows=rows)
        records[identity] = {"checked_at_utc": utc_now_iso(), "status": status,
                             "raw_ref": reference, "row_count": len(rows)}
        if status == "000" and rows and all(r.get("currency") == "KRW" and r.get("corp_code") == corp
                and r.get("bsns_year") == str(year) and r.get("reprt_code") == code for r in rows):
            result = parse_report(rows, basis, report_period_end(year, code, month), [reference], code, year)
            outcomes["fetched"] += 1
        elif status == "013":
            outcomes["no_data"] += 1
        else:
            outcomes["errors"] += 1
        if status in {"010", "011", "012", "020", "800", "900", "901"}:
            exhausted = True
        if requests_used % 10 == 0:
            print(f"[VALUATION GAPS] requests={requests_used} {outcomes}", flush=True)
        time.sleep(0.1)
        return result

    print(f"[VALUATION GAPS] targets={len(targets)} max_requests={max_requests}", flush=True)
    try:
        for ticker, metric in sorted(targets.items()):
            row = latest.get(ticker, {})
            corp = row.get("corp_code")
            basis = row.get("detail_basis") or row.get("statement_basis")
            if not corp or not basis:
                continue
            month = metric.get("fiscal_month", 12)
            year, code, due_end = company_due_period(as_of, month)
            if metric.get("period_end") == due_end and metric.get("report_code"):
                code, year = metric["report_code"], metric["fiscal_year"]
            current = report(ticker, year, code, basis, corp, month, CAPITAL | INCOME)
            if code != "11011":
                annual_year = year if report_period_end(year, "11011", month) < due_end else year - 1
                report(ticker, annual_year, "11011", basis, corp, month, INCOME)
            report(ticker, year - 1, code, basis, corp, month,
                   CAPITAL | (set() if code == "11011" else INCOME), current.get("previous"))
            save()
            if exhausted:
                break
    finally:
        save()
    print(f"[VALUATION GAPS] saved requests={requests_used} {outcomes}", flush=True)
    return progress


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--as-of", default=datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat())
    parser.add_argument("--max-requests", type=int, default=600)
    parser.add_argument("--codes", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()
    load_env_file(Path(args.env_file))
    key = os.environ.get("DART_API_KEY")
    if not key:
        print("[VALUATION GAPS] DART_API_KEY not configured; saved inputs retained.")
        return
    collect(Path(args.data_dir), date.fromisoformat(args.as_of), key,
            max_requests=args.max_requests, codes=set(args.codes.split(",")) if args.codes else None, force=args.force)


if __name__ == "__main__":
    main()
