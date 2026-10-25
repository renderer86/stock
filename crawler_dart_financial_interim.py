"""Refresh interim cash flows for nonfinancial Buffett watchlist companies."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from collector_common import atomic_write_json, utc_now_iso
from crawler_dart_financial_details import create_session, standardize_accounts, DART_FULL_ACCOUNT_URL
from dart_financial_storage import load_financial_panel
from env_loader import load_env_file
from stock_codes import normalize_stock_code


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
    current_income = income.get("thstrm_add_amount")
    old_income = income.get("frmtrm_add_amount")
    yoy = (int(current_income) / int(old_income) - 1) * 100 if current_income and old_income and int(old_income) > 0 else None
    receipt = rows[0].get("rcept_no")
    return {"ticker": ticker, "corp_code": corp_code, "fiscal_year": year,
            "report_code": report_code, "basis": basis, "period_end": period_end,
            "status": "ok", "fetched_at_utc": utc_now_iso(),
            "dart_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
            "current": current, "previous": previous,
            "operating_income_yoy_pct": round(yoy, 4) if yoy is not None else None,
            "raw_rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-codes", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    load_env_file(Path(".env"))
    key = os.getenv("DART_API_KEY")
    if not key:
        print("[INTERIM] DART_API_KEY unavailable; retaining annual fallback and existing interim reports.", flush=True)
        return
    output = Path("data/dart_financial_interim.json")
    payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {"schema_version": 1, "source_url": DART_FULL_ACCOUNT_URL, "companies": {}}
    panel = load_financial_panel(Path("data/dart_financial_panel.json"))
    screens = json.loads(Path("data/investment_screens.json").read_text(encoding="utf-8"))
    requested = {r["ticker"] for r in screens["rankings"]["buffett_watchlist"]}
    requested.update(payload["companies"])
    requested.update(normalize_stock_code(code) for code in args.include_codes.split(",") if code.strip())
    latest = {}
    for row in panel["observations"]:
        ticker = row["ticker"]
        if ticker in requested and row["fiscal_year"] > latest.get(ticker, {}).get("fiscal_year", 0):
            latest[ticker] = row
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    year, report_code, end = latest_due_period(now.date())
    session = create_session()
    errors, fetched = [], 0
    for ticker, row in sorted(latest.items()):
        if row.get("is_financial") or row["fiscal_year"] != year - 1 or row.get("detail_status") != "complete":
            continue
        old = payload["companies"].get(ticker) or {}
        if not args.force and old.get("period_end") == end and old.get("fetched_at_utc") and (now - datetime.fromisoformat(old["fetched_at_utc"])).days < 7:
            continue
        basis = row.get("detail_basis")
        if basis not in ("CFS", "OFS"):
            continue
        try:
            response = session.get(DART_FULL_ACCOUNT_URL, params={"crtfc_key": key, "corp_code": row["corp_code"], "bsns_year": str(year), "reprt_code": report_code, "fs_div": basis}, timeout=25)
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "000":
                errors.append({"ticker": ticker, "status": data.get("status")})
                if data.get("status") == "020":
                    break
                continue
            payload["companies"][ticker] = parse_interim(data["list"], ticker=ticker, corp_code=row["corp_code"], year=year, report_code=report_code, basis=basis, period_end=end)
            fetched += 1
        except Exception as exc:
            # Never print requests' exception text: it may include the API key.
            errors.append({"ticker": ticker, "error_type": type(exc).__name__})
        print(f"[INTERIM] {ticker}: reports fetched {fetched}, unavailable/errors {len(errors)}", flush=True)
    payload.update({"updated_at_utc": utc_now_iso(), "requested_period_end": end, "errors": errors})
    atomic_write_json(output, payload, compact=True)
    print(f"[INTERIM] Saved {len(payload['companies'])} company reports; fetched {fetched}.", flush=True)


if __name__ == "__main__":
    main()
