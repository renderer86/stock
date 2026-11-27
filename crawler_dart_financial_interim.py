"""Collect full quarterly DART statements in bounded, resumable batches."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from collector_common import atomic_write_json, utc_now_iso
from crawler_dart_financial_details import create_session, parse_amount, standardize_accounts, DART_FULL_ACCOUNT_URL
from crawler_dart_financial_panel import corp_code_map_from_existing_panel, fetch_corp_code_map
from dart_financial_raw_storage import ApiRawAccumulator, read_gzip_json, ticker_bucket
from dart_financial_quarterly_bulk import BULK_MAIN_URL, bulk_gap_reasons, load_quarterly_bulk
from dart_financial_storage import load_financial_panel
from env_loader import load_env_file
from stock_codes import normalize_stock_code


REPORTS = {1: ("11013", "03-31"), 2: ("11012", "06-30"), 3: ("11014", "09-30")}
KST = ZoneInfo("Asia/Seoul")


def latest_due_period(today: date) -> tuple[int, str, str]:
    for month, day, report_code in ((9, 30, "11014"), (6, 30, "11012"), (3, 31, "11013")):
        end = date(today.year, month, day)
        if today >= end + timedelta(days=45):
            return today.year, report_code, end.isoformat()
    return today.year - 1, "11014", f"{today.year - 1}-09-30"


def parse_interim(rows: list[dict], *, ticker: str, corp_code: str, year: int, report_code: str, basis: str, period_end: str) -> dict:
    if not rows or any(r.get("corp_code") != corp_code or r.get("currency") != "KRW" or r.get("bsns_year") != str(year) or r.get("reprt_code") != report_code for r in rows):
        raise ValueError("Interim report identity or currency mismatch")
    cash_rows = [r for r in rows if r.get("sj_div") == "CF"]
    current, _ = standardize_accounts(cash_rows)
    previous_rows = [{**r, "thstrm_amount": r.get("frmtrm_q_amount"), "thstrm_add_amount": None} for r in cash_rows]
    previous, _ = standardize_accounts(previous_rows)
    income = next((r for r in rows if r.get("account_id") == "dart_OperatingIncomeLoss"), {})
    current_income = parse_amount(income.get("thstrm_add_amount"))
    old_income = parse_amount(income.get("frmtrm_add_amount"))
    yoy = (current_income / old_income - 1) * 100 if current_income is not None and old_income is not None and old_income > 0 else None
    receipt = rows[0].get("rcept_no")
    accounts, _ = standardize_accounts(rows)
    return {"ticker": ticker, "corp_code": corp_code, "fiscal_year": year,
            "report_code": report_code, "basis": basis, "period_end": period_end,
            "status": "ok", "fetched_at_utc": utc_now_iso(),
            "dart_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
            "current": current, "previous": previous,
            "accounts": accounts, "available_statements": sorted({r.get("sj_div") for r in rows if r.get("sj_div")}),
            "operating_income_yoy_pct": round(yoy, 4) if yoy is not None else None,
            "raw_rows": rows}


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("all", "watchlist"), default="all")
    parser.add_argument("--bulk-mode", choices=("auto", "only", "skip"), default="auto", help="auto=ZIP first then gap API; only=ZIP without API; skip=API gaps using saved state.")
    parser.add_argument("--bulk-only", dest="bulk_mode", action="store_const", const="only")
    parser.add_argument("--panel", default="data/dart_financial_panel.json")
    parser.add_argument("--market", default="data/market_sum.json")
    parser.add_argument("--screens", default="data/investment_screens.json")
    parser.add_argument("--output", default="data/dart_financial_interim.json")
    parser.add_argument("--progress-dir", default="data/dart_financial_interim_progress")
    parser.add_argument("--raw-root", default="data/dart_financial_raw")
    parser.add_argument("--corp-codes", default="data/dart_corp_codes.json")
    parser.add_argument("--refresh-corp-codes", action="store_true", help="Refresh mapping, including new listings; also done automatically when cache is absent or 7 days old.")
    parser.add_argument("--year", type=int, default=0)
    parser.add_argument("--quarter", type=int, choices=(0, 1, 2, 3), default=0, help="0=latest due period; 2=half-year. Set year and quarter together.")
    parser.add_argument("--codes", default="", help="Collect only these comma-separated tickers.")
    parser.add_argument("--include-codes", default="")
    parser.add_argument("--max-companies", type=int, default=500, help="Companies attempted this run (0=all).")
    parser.add_argument("--max-requests", type=int, default=1000, help="Hard cap including mapping calls, retries and basis fallback.")
    parser.add_argument("--max-runtime-minutes", type=float, default=15)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--refresh-days", type=float, default=7)
    parser.add_argument("--retry-hours", type=float, default=24)
    parser.add_argument("--retry-failed", action="store_true", help="Ignore failed/no-data cooldown; successful reports still obey refresh-days.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", "--status", dest="dry_run", action="store_true", help="Print local coverage and next batch; no API calls or writes.")
    args = parser.parse_args(argv)
    if bool(args.year) != bool(args.quarter) or (args.year and args.year < 2015):
        parser.error("--year (2015+) and --quarter (1/2/3) must be set together")
    if args.max_companies < 0 or args.max_requests < 1 or args.max_runtime_minutes <= 0 or args.checkpoint_every < 1:
        parser.error("Invalid company/request/runtime/checkpoint limits")
    if min(args.delay, args.refresh_days, args.retry_hours) < 0:
        parser.error("Delay and cache intervals cannot be negative")
    return args


def age_seconds(timestamp: str | None, now: datetime) -> float:
    try:
        parsed = datetime.fromisoformat(timestamp or "")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KST)
        return (now - parsed).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


def code_set(value: str) -> set[str]:
    codes = set()
    for raw in value.split(","):
        if raw.strip():
            code = normalize_stock_code(raw)
            if not code:
                raise ValueError("Invalid stock code")
            codes.add(code)
    return codes


def collect_targets(panel: dict, market: dict, screens: dict, payload: dict, mapping: dict, args) -> tuple[dict, list[str]]:
    """Include financials and companies without complete annual detail data."""
    latest = {}
    for row in panel.get("observations", []):
        ticker = normalize_stock_code(row.get("ticker"))
        if ticker and row["fiscal_year"] > latest.get(ticker, {}).get("fiscal_year", 0):
            latest[ticker] = row
    listed = {normalize_stock_code(s.get("code")): s for s in market.get("stocks", []) if normalize_stock_code(s.get("code")) and s.get("security_type") not in {"etf", "etn"}}
    requested = set(listed or latest) if args.scope == "all" else {r["ticker"] for r in screens.get("rankings", {}).get("buffett_watchlist", [])}
    if args.scope == "watchlist":
        requested.update(payload.get("companies", {}))
    if args.codes:
        requested = code_set(args.codes)
    requested.update(code_set(args.include_codes))
    targets, unmapped = {}, []
    for ticker in sorted(requested):
        info = mapping.get(ticker) or {}
        if not info.get("corp_code"):
            unmapped.append(ticker)
            continue
        row = latest.get(ticker) or {}
        targets[ticker] = {"ticker": ticker, "corp_code": info["corp_code"], "company": info.get("corp_name") or row.get("company") or (listed.get(ticker) or {}).get("name"), "is_financial": bool(row.get("is_financial")), "preferred_basis": row.get("detail_basis") if row.get("detail_basis") in ("CFS", "OFS") else "CFS"}
    return targets, unmapped


def plan_queue(targets: dict, state: dict, payload: dict, end: str, now: datetime, args) -> list[str]:
    queue = []
    for ticker, target in targets.items():
        record = state.get(ticker) or {}
        old = payload.get("companies", {}).get(ticker) or {}
        # Legacy data can seed a checkpoint without fetching it again.
        if not record and old.get("period_end") == end and old.get("corp_code") == target["corp_code"]:
            record = old
            state[ticker] = {k: v for k, v in old.items() if k != "raw_rows"}
        if record.get("corp_code") != target["corp_code"]:
            record = {}
        status = record.get("status")
        if status == "ok":
            due = record.get("source") != "bulk_zip" and (args.force or age_seconds(record.get("fetched_at_utc"), now) >= args.refresh_days * 86400)
            priority, stamp = 2, record.get("fetched_at_utc", "")
        elif status in ("error", "no_data", "unsupported_currency"):
            due = args.force or args.retry_failed or age_seconds(record.get("attempted_at_utc"), now) >= args.retry_hours * 3600
            priority, stamp = 1, record.get("attempted_at_utc", "")
        else:
            due, priority, stamp = True, 0, ""
        if due:
            queue.append((priority, stamp, ticker))
    return [ticker for _, _, ticker in sorted(queue)]


class BatchStopped(Exception):
    pass


class BudgetSession:
    """Count every HTTP attempt, including the mapping helper's retries."""

    def __init__(self, session, args):
        self.session, self.args = session, args
        self.requests = 0
        self.deadline = time.monotonic() + args.max_runtime_minutes * 60

    def get(self, url, **kwargs):
        if self.requests >= self.args.max_requests:
            raise BatchStopped("request_budget")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise BatchStopped("runtime_budget")
        if self.requests and self.args.delay:
            time.sleep(min(self.args.delay, remaining))
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise BatchStopped("runtime_budget")
        kwargs["timeout"] = max(0.001, min(float(kwargs.get("timeout", 25)), remaining))
        self.requests += 1
        return self.session.get(url, **kwargs)


def apply_report(payload: dict, report: dict) -> None:
    old = payload.setdefault("companies", {}).get(report["ticker"]) or {}
    if report["period_end"] >= old.get("period_end", ""):
        payload["companies"][report["ticker"]] = report


def refresh_report_flags(targets: dict, state: dict, payload: dict) -> None:
    for ticker, target in targets.items():
        report = state.get(ticker) or {}
        if report.get("status") == "ok" and report.get("source") == "api":
            report["missing_fields"] = bulk_gap_reasons(report, is_financial=target["is_financial"])
            report["calculation_complete"] = not report["missing_fields"]
            apply_report(payload, report)


def recover_foreign_currency_reports(state: dict, raw_root: Path, year: int, report_code: str) -> None:
    """Classify legacy validation failures from preserved raw rows, without HTTP."""
    shards = {}
    for ticker, record in state.items():
        if record.get("status") != "error" or record.get("error_type") != "ValueError":
            continue
        for basis in ("CFS", "OFS"):
            path = raw_root / str(year) / "api" / f"interim_{report_code}_{basis}_{ticker_bucket(ticker)}.json.gz"
            if path not in shards:
                shards[path] = read_gzip_json(path)
            raw_record = shards[path].get("records_by_ticker", {}).get(ticker, {})
            params = raw_record.get("request_parameters", {})
            rows = raw_record.get("rows", [])
            if raw_record.get("corp_code") != record.get("corp_code") or params.get("bsns_year") != str(year) or params.get("reprt_code") != report_code or not rows:
                continue
            currencies = sorted({str(row.get("currency") or "") for row in rows})
            if currencies != ["KRW"]:
                record.update(status="unsupported_currency", currencies=currencies, raw_ref=(Path(raw_root.name) / path.relative_to(raw_root)).as_posix())
                record.pop("error_type", None)
                break


def apply_bulk_reports(targets: dict, state: dict, payload: dict, grouped: dict, references: dict, sources: dict, *, year: int, report_code: str, end: str) -> dict:
    counts = Counter()
    fingerprint = "|".join(sources[s] for s in sorted(sources))
    for ticker, target in targets.items():
        old = state.get(ticker) or {}
        # An API supplement for this exact ZIP set must survive the next run.
        if old.get("status") == "ok" and old.get("source") == "api" and old.get("bulk_fingerprint") == fingerprint:
            counts["api_retained"] += 1
            continue
        bases = [target["preferred_basis"], "OFS" if target["preferred_basis"] == "CFS" else "CFS"]
        selected = next((basis for basis in bases if {"BS", "IS", "CF"} <= {r["sj_div"] for r in grouped.get((ticker, basis), [])}), bases[0])
        rows = [{**row, "corp_code": target["corp_code"]} for row in grouped.get((ticker, selected), [])]
        if not rows:
            counts["missing"] += 1
            continue
        report = parse_interim(rows, ticker=ticker, corp_code=target["corp_code"], year=year, report_code=report_code, basis=selected, period_end=end)
        report.pop("raw_rows")
        report.update(source="bulk_zip", company=target["company"], dart_url=BULK_MAIN_URL, bulk_sources=sources, bulk_fingerprint=fingerprint, raw_financial_statements=(references.get(ticker) or {}).get(selected, {}))
        gaps = bulk_gap_reasons(report, is_financial=target["is_financial"])
        if gaps:
            # Preserve an API failure's cooldown for an unchanged ZIP fingerprint.
            if old.get("bulk_fingerprint") == fingerprint and old.get("status") in ("error", "no_data", "pending"):
                counts["partial"] += 1
                continue
            report.update(status="bulk_partial", bulk_gap_reasons=gaps, calculation_complete=False)
            state[ticker] = report
            counts["partial"] += 1
        else:
            report["calculation_complete"] = True
            state[ticker] = report
            apply_report(payload, report)
            counts["imported"] += 1
    return dict(counts)


def collect_batch(targets: dict, queue: list[str], state: dict, payload: dict, *, year: int, report_code: str, end: str, args, session: BudgetSession, raw: ApiRawAccumulator, checkpoint) -> dict:
    attempted = fetched = 0
    stopped = "queue_exhausted"
    try:
        for ticker in queue:
            if args.max_companies and attempted >= args.max_companies:
                stopped = "company_budget"
                break
            target = targets[ticker]
            old_state = state.get(ticker) or {}
            bases = [target["preferred_basis"], "OFS" if target["preferred_basis"] == "CFS" else "CFS"]
            if old_state.get("status") == "pending" and old_state.get("corp_code") == target["corp_code"] and old_state.get("next_basis") in bases:
                bases = bases[bases.index(old_state["next_basis"]):]
            attempted += 1
            try:
                for basis in bases:
                    # Persist the exact basis to resume if the budget expires here.
                    state[ticker] = {**target, "status": "pending", "next_basis": basis, "attempted_at_utc": utc_now_iso(), "bulk_fingerprint": getattr(args, "bulk_fingerprint", "")}
                    params = {"corp_code": target["corp_code"], "bsns_year": str(year), "reprt_code": report_code, "fs_div": basis}
                    response = session.get(DART_FULL_ACCOUNT_URL, params={**params, "crtfc_key": args.api_key}, timeout=25)
                    response.raise_for_status()
                    data = response.json()
                    status = str(data.get("status") or "")
                    if status in ("000", "013"):
                        rows = data.get("list") or []
                        reference = raw.add(year=year, dataset=f"interim_{report_code}", ticker=ticker, corp_code=target["corp_code"], basis=basis, endpoint=DART_FULL_ACCOUNT_URL, request_parameters=params, response_status=status, rows=rows)
                        if status == "013":
                            state[ticker] = {**target, "status": "no_data", "dart_status": status, "attempted_at_utc": utc_now_iso(), "bulk_fingerprint": getattr(args, "bulk_fingerprint", "")}
                            if len(bases) > 1 and basis == bases[0]:
                                state[ticker].update(status="pending", next_basis=bases[1])
                            continue
                        currencies = sorted({str(row.get("currency") or "") for row in rows})
                        if currencies != ["KRW"]:
                            state[ticker] = {**target, "status": "unsupported_currency", "currencies": currencies, "raw_ref": reference, "attempted_at_utc": utc_now_iso(), "bulk_fingerprint": getattr(args, "bulk_fingerprint", "")}
                            break
                        report = parse_interim(rows, ticker=ticker, corp_code=target["corp_code"], year=year, report_code=report_code, basis=basis, period_end=end)
                        report.pop("raw_rows")
                        report.update(source="api", company=target["company"], raw_ref=reference, bulk_fingerprint=getattr(args, "bulk_fingerprint", ""))
                        report["missing_fields"] = bulk_gap_reasons(report, is_financial=target["is_financial"])
                        report["calculation_complete"] = not report["missing_fields"]
                        state[ticker] = report
                        apply_report(payload, report)
                        fetched += 1
                        break
                    state[ticker] = {**target, "status": "error", "dart_status": status, "attempted_at_utc": utc_now_iso(), "bulk_fingerprint": getattr(args, "bulk_fingerprint", "")}
                    if status in ("010", "011", "012", "020", "800", "901"):
                        stopped = f"dart_{status}"
                        break
                    break
            except BatchStopped as exc:
                stopped = str(exc)
                break
            except Exception as exc:
                # Exception messages may contain authenticated URLs: only store type.
                state[ticker] = {**target, "status": "error", "error_type": type(exc).__name__, "attempted_at_utc": utc_now_iso(), "bulk_fingerprint": getattr(args, "bulk_fingerprint", "")}
            if attempted % args.checkpoint_every == 0:
                checkpoint()
            if attempted == 1 or attempted % 25 == 0 or stopped.startswith("dart_"):
                print(f"[INTERIM] {ticker}: attempted={attempted} fetched={fetched} requests={session.requests}", flush=True)
            if stopped.startswith("dart_"):
                break
    except KeyboardInterrupt:
        stopped = "interrupted"
    finally:
        checkpoint()
    return {"attempted_companies": attempted, "fetched_companies": fetched, "request_count": session.requests, "stop_reason": stopped}


def main(argv=None):
    args = parse_args(argv)
    now = datetime.now(KST)
    year, report_code, end = latest_due_period(now.date())
    if args.year:
        report_code, month_day = REPORTS[args.quarter]
        year, end = args.year, f"{args.year}-{month_day}"
    if end > now.date().isoformat():
        raise SystemExit("Cannot collect a future reporting period")
    output = Path(args.output)
    payload = read_json(output) or {"schema_version": 2, "source_url": DART_FULL_ACCOUNT_URL, "companies": {}}
    panel = load_financial_panel(Path(args.panel))
    market = read_json(Path(args.market))
    if not panel.get("observations") and not market.get("stocks"):
        raise SystemExit("No stock universe available; build the annual panel or market data first")
    screens = read_json(Path(args.screens)) if args.scope == "watchlist" else {}
    progress_path = Path(args.progress_dir) / f"{year}_{report_code}.json"
    progress = read_json(progress_path)
    state = progress.setdefault("companies", {})
    for record in state.values():
        if record.get("status") == "ok":
            apply_report(payload, record)
    mapping_cache = read_json(Path(args.corp_codes))
    mapping = corp_code_map_from_existing_panel(panel)
    mapping.update(mapping_cache.get("companies", {}))
    targets, unmapped = collect_targets(panel, market, screens, payload, mapping, args)
    refresh_report_flags(targets, state, payload)
    recover_foreign_currency_reports(state, Path(args.raw_root), year, report_code)
    queue = plan_queue(targets, state, payload, end, now, args)
    counts = Counter((state.get(t) or {}).get("status", "pending") for t in targets)
    print(f"[INTERIM] period={end} scope={args.scope} targets={len(targets)} ok={counts['ok']} bulk_partial={counts['bulk_partial']} no_data={counts['no_data']} unsupported_currency={counts['unsupported_currency']} errors={counts['error']} pending={counts['pending']} eligible={len(queue)} next_batch={min(len(queue), args.max_companies or len(queue))} unmapped={len(unmapped)}", flush=True)
    if args.dry_run:
        print(f"[INTERIM] Dry run: ZIP mode={args.bulk_mode}, max_requests={args.max_requests} max_runtime_minutes={args.max_runtime_minutes}; no API calls or writes. Coverage is BEFORE any new ZIP import, using local mapping only.", flush=True)
        return
    load_env_file(Path(".env"))
    args.api_key = os.getenv("DART_API_KEY", "").strip()
    session = BudgetSession(create_session(), args)
    raw = ApiRawAccumulator(Path(args.raw_root))

    def checkpoint():
        raw.flush()
        progress.update(schema_version=1, fiscal_year=year, report_code=report_code, period_end=end, updated_at_utc=utc_now_iso(), scope=args.scope, target_count=len(targets), unmapped_codes=unmapped)
        progress["summary"] = dict(Counter((state.get(t) or {}).get("status", "pending") for t in targets))
        atomic_write_json(progress_path, progress, compact=True)
        # Reconcile first, so a crash between progress and output is recoverable.
        payload.update(schema_version=2, updated_at_utc=utc_now_iso(), requested_period_end=end)
        payload["errors"] = [{"ticker": t, **{k: v for k, v in record.items() if k in ("status", "dart_status", "error_type", "currencies", "attempted_at_utc")}} for t, record in state.items() if t in targets and record.get("status") in ("error", "no_data", "unsupported_currency")]
        payload["coverage"] = {"scope": args.scope, "period_end": end, "target_count": len(targets), **progress["summary"], "unmapped_count": len(unmapped)}
        atomic_write_json(output, payload, compact=True)

    grouped, references, sources = {}, {}, progress.get("bulk_sources", {})
    if args.bulk_mode != "skip":
        def on_statement(statement, filename):
            progress.setdefault("bulk_sources", {})[statement] = filename
            checkpoint()

        try:
            grouped, references, sources = load_quarterly_bulk(session, Path(args.raw_root), year=year, report_code=report_code, period_end=end, on_statement=on_statement)
        except BatchStopped as exc:
            progress["last_run"] = {"stage": "bulk", "stop_reason": str(exc), "request_count": session.requests}
            checkpoint()
            print(f"[INTERIM] ZIP stage stopped: {exc}; rerun to resume. API collection has not started.", flush=True)
            return
        except Exception as exc:
            checkpoint()
            raise SystemExit(f"ZIP stage failed ({type(exc).__name__}); saved ZIP checkpoints retained. Rerun before API supplementation.") from None

    # The ZIP stage runs without an API key. Refresh new-listing mappings only
    # after those public files have been saved, and count its HTTP attempts too.
    if args.api_key and args.bulk_mode != "only" and (args.refresh_corp_codes or age_seconds(mapping_cache.get("updated_at_utc"), now) >= 7 * 86400):
        try:
            fresh_mapping = fetch_corp_code_map(session, args.api_key)
            mapping.update(fresh_mapping)
            atomic_write_json(Path(args.corp_codes), {"updated_at_utc": utc_now_iso(), "companies": fresh_mapping}, compact=True)
            targets, unmapped = collect_targets(panel, market, screens, payload, mapping, args)
        except (RuntimeError, BatchStopped):
            print("[INTERIM] Mapping refresh unavailable; using saved mapping.", flush=True)
    if not targets:
        raise SystemExit("No mapped companies selected; check universe and stock codes")
    if grouped:
        progress["bulk_result"] = apply_bulk_reports(targets, state, payload, grouped, references, sources, year=year, report_code=report_code, end=end)
        print(f"[INTERIM] ZIP result: {json.dumps(progress['bulk_result'])}", flush=True)
        checkpoint()
    args.bulk_fingerprint = "|".join(sources[s] for s in sorted(sources))
    queue = plan_queue(targets, state, payload, end, datetime.now(KST), args)
    print(f"[INTERIM] After ZIP: API-eligible companies={len(queue)}; this batch <= {min(len(queue), args.max_companies or len(queue))}", flush=True)
    if args.bulk_mode == "only" or not args.api_key:
        progress["last_run"] = {"stage": "bulk", "stop_reason": "bulk_only" if args.bulk_mode == "only" else "api_key_unavailable", "request_count": session.requests, "api_eligible_count": len(queue)}
        checkpoint()
        print("[INTERIM] ZIP updates saved; API collection has not started.", flush=True)
        return
    result = collect_batch(targets, queue, state, payload, year=year, report_code=report_code, end=end, args=args, session=session, raw=raw, checkpoint=checkpoint)
    progress["last_run"] = result
    checkpoint()
    print(f"[INTERIM] Finished: {json.dumps(result)}; rerun the same command to resume.", flush=True)
    if result["stop_reason"] in ("dart_010", "dart_011", "dart_012", "dart_800", "dart_901", "interrupted"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
