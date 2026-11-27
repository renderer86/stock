"""Build latest, auditable valuation inputs from saved DART statements."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from collector_common import atomic_write_json, utc_now_iso
from crawler_dart_financial_details import ACCOUNT_SPECS, account_rows, select_account, create_session, normalize_text, normalize_account_id
from crawler_dart_financial_bulk import fetch_bulk_listing, download_bulk_zip, parse_bulk_archive
from crawler_dart_financial_interim import latest_due_period
from dart_financial_raw_storage import bulk_group_tables, read_gzip_json, load_bulk_raw_statement, write_bulk_raw_shards
from dart_financial_storage import load_financial_panel
from financial_engine.valuation import evaluate_returns, trailing_income
from stock_codes import normalize_stock_code


EXTRA_SPECS = {
    "capital_stock": {"statements": {"BS"}, "ids": {"ifrs-full_IssuedCapital"}, "aliases": {"자본금"}},
    "continuing_net_income": {"statements": {"IS", "CIS"},
        "ids": {"ifrs-full_ProfitLossFromContinuingOperations"},
        "aliases": {"계속영업이익손실", "계속영업당기순이익손실", "계속영업순이익손실", "계속영업당기순이익"}},
    "discontinued_net_income": {"statements": {"IS", "CIS"},
        "ids": {"ifrs-full_ProfitLossFromDiscontinuedOperations"},
        "aliases": {"중단영업이익손실", "중단영업당기순이익손실", "중단영업순이익손실", "중단영업이익"}},
}
SPECS = {key: ACCOUNT_SPECS[key] for key in
         ("assets", "equity", "owners_equity", "net_income", "owners_net_income")}
SPECS.update(EXTRA_SPECS)
ACCOUNT_IDS = {normalize_account_id(i) for spec in SPECS.values() for i in spec["ids"]}
ACCOUNT_NAMES = {normalize_text(n) for spec in SPECS.values() for n in spec["aliases"]}
REPORTS = {"03-31": "11013", "06-30": "11012", "09-30": "11014", "12-31": "11011"}


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def standardized(rows, basis):
    normalized = account_rows(rows)
    values = {key: amount for key, spec in SPECS.items()
              if (amount := select_account(normalized, spec)[0]) is not None}
    income_rows = [r for r in normalized if r["statement"] in {"IS", "CIS"}]
    spec = SPECS["discontinued_net_income"]
    # A full income statement without a discontinued-operations line reports no
    # separate discontinued result. An explicit blank line remains unknown.
    if income_rows and "net_income" in values and not any(
        r["account_id"].replace("ifrs_", "ifrs-full_") in spec["ids"]
        or ("중단영업" in r["normalized_name"] and "주당" not in r["normalized_name"]
            and "포괄" not in r["normalized_name"])
        for r in income_rows
    ):
        values["discontinued_net_income"] = 0
    if "continuing_net_income" not in values and all(k in values for k in ("net_income", "discontinued_net_income")):
        values["continuing_net_income"] = values["net_income"] - values["discontinued_net_income"]
    # CFS must never mix total profit with parent-only capital. Missing parent
    # amounts are unknown; OFS is the only basis where totals are equivalent.
    if basis == "OFS":
        for parent, total in (("owners_equity", "equity"), ("owners_net_income", "net_income")):
            if parent not in values and total in values:
                values[parent] = values[total]
    return values


def parse_report(rows, basis, end, sources):
    quarter = not end.endswith("12-31")
    current_rows, previous_rows = [], []
    for row in rows:
        income = row.get("sj_div") in {"IS", "CIS"}
        current = row.get("thstrm_add_amount") if income and quarter else row.get("thstrm_amount")
        previous = row.get("frmtrm_add_amount") if income else row.get("frmtrm_amount")
        # The first quarter is itself cumulative; later quarters require YTD.
        if income and end.endswith("03-31"):
            current = current if current not in (None, "") else row.get("thstrm_amount")
            previous = previous if previous not in (None, "") else row.get("frmtrm_q_amount")
        current_rows.append({**row, "thstrm_amount": current, "thstrm_add_amount": None})
        previous_rows.append({**row, "thstrm_amount": previous, "thstrm_add_amount": None})
    return {"basis": basis, "period_end": end,
            "current": standardized(current_rows, basis), "previous": standardized(previous_rows, basis),
            "sources": sorted(set(sources))}


class RawReports:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.cache = {}
        self.api_cache = {}

    def bulk(self, year, code):
        key = (year, code)
        if key in self.cache:
            return self.cache[key]
        grouped, sources = defaultdict(list), defaultdict(set)
        prefix = "" if code == "11011" else f"{code}_"
        for statement in ("BS", "PL"):
            for path in sorted((self.data_dir / "dart_financial_raw" / str(year) / "bulk").glob(f"{prefix}{statement}_*.json.gz")):
                raw = read_gzip_json(path)
                for table in bulk_group_tables(raw):
                    headers = [re.sub(r"\s+", "", str(h)) for h in table.get("header", [])]
                    def column(test):
                        return next((i for i, h in enumerate(headers) if i >= 12 and test(h)), None)
                    cur = column(lambda h: h.startswith("당기"))
                    cum = column(lambda h: h.startswith("당기") and "누적" in h)
                    old = column(lambda h: h.startswith("전기") and ("말" in h if statement == "BS" else "누적" in h))
                    prev_quarter = column(lambda h: h.startswith("전기") and "누적" not in h)
                    if cur is None:
                        continue
                    # Some financial-industry TXT tables label their cumulative
                    # flows as a quarter-end balance, with no separate 3-month column.
                    if statement == "PL" and code != "11011" and cum is None and "말" in headers[cur]:
                        cum = cur
                    for cells in table.get("rows", []):
                        if len(cells) <= max(11, cur) or str(cells[9]).strip() != "KRW" or str(cells[6]).strip() != "12":
                            continue
                        ticker = normalize_stock_code(cells[1])
                        end = str(cells[7]).strip()
                        if not ticker or REPORTS.get(end[5:]) != code or not end.startswith(str(year)):
                            continue
                        account_id, account_name = str(cells[10]).strip(), str(cells[11]).strip()
                        if normalize_account_id(account_id) not in ACCOUNT_IDS and normalize_text(account_name) not in ACCOUNT_NAMES and "중단영업" not in normalize_text(account_name):
                            continue
                        def cell(i):
                            return str(cells[i]).strip() if i is not None and i < len(cells) else None
                        report_key = (ticker, raw["basis"], end)
                        grouped[report_key].append({"sj_div": "BS" if statement == "BS" else "IS",
                            "account_id": cell(10), "account_nm": cell(11), "thstrm_amount": cell(cur),
                            "thstrm_add_amount": cell(cum), "frmtrm_amount": cell(old),
                            "frmtrm_add_amount": cell(old), "frmtrm_q_amount": cell(prev_quarter)})
                        sources[report_key].add(path.relative_to(self.data_dir).as_posix())
        self.cache[key] = {(t, b): parse_report(rows, b, end, sources[(t, b, end)])
                           for (t, b, end), rows in grouped.items()}
        return self.cache[key]

    def api(self, reference, ticker, basis, end, corp_code):
        if not reference:
            return None
        if reference not in self.api_cache:
            self.api_cache[reference] = read_gzip_json(self.data_dir / reference)
        record = self.api_cache[reference].get("records_by_ticker", {}).get(ticker, {})
        params = record.get("request_parameters", {})
        if record.get("response_status") != "000" or params.get("fs_div") != basis or params.get("corp_code") != corp_code or params.get("bsns_year") != end[:4] or params.get("reprt_code") != REPORTS[end[5:]]:
            return None
        rows = record.get("rows", [])
        if not rows or any(row.get("currency") != "KRW" or row.get("corp_code") != corp_code
                           or row.get("bsns_year") != end[:4] or row.get("reprt_code") != REPORTS[end[5:]] for row in rows):
            return None
        return parse_report(rows, basis, end, [reference])


def ensure_prior_balances(data_dir, year, code):
    if code == "11011":
        return
    root = Path(data_dir) / "dart_financial_raw"
    session = create_session()
    period = {"11013": "FQ", "11012": "HY", "11014": "TQ"}[code]
    listing = fetch_bulk_listing(session, timeout=60, period=period)
    for statement in ("BS", "PL"):
        source = listing.get((year - 1, statement))
        if not source:
            raise RuntimeError("Prior-year comparable financial statements are not available")
        scoped = f"{code}_{statement}"
        if not load_bulk_raw_statement(root, year=year - 1, statement=scoped, source_file=source):
            content = download_bulk_zip(session, source, timeout=120, attempts=2)
            _, raw, _ = parse_bulk_archive(content, statement)
            write_bulk_raw_shards(root, year=year - 1, statement=scoped, source_file=source, raw_groups=raw)


def build_metrics(panel, market, interim, store, as_of):
    year, code, due_end = latest_due_period(as_of)
    annual_year = as_of.year - (1 if as_of >= date(as_of.year, 3, 31) else 2)
    required_end = max(due_end, f"{annual_year}-12-31")
    annual_by_ticker = defaultdict(list)
    for row in panel.get("observations", []):
        annual_by_ticker[row["ticker"]].append(row)
    metrics = {}
    market_stocks = market.get("stocks", [])
    preferred_by_common = defaultdict(list)
    common_by_prefix = {s["code"][:5]: s for s in market_stocks if s["code"].endswith("0")}
    for stock in market_stocks:
        common = common_by_prefix.get(stock["code"][:5])
        if common and stock["code"] != common["code"]:
            suffix = str(stock.get("name", ""))[len(str(common.get("name", ""))):]
            if str(stock.get("name", "")).startswith(str(common.get("name", ""))) and re.fullmatch(r"(?:\d+)?우[A-Z]?", suffix):
                preferred_by_common[common["code"]].append(stock)
    for stock in market_stocks:
        ticker = stock["code"]
        candidates = sorted(annual_by_ticker.get(ticker, []), key=lambda r: r["fiscal_year"])
        latest = candidates[-1] if candidates else {}
        basis = latest.get("detail_basis") or latest.get("statement_basis")
        corp_code = latest.get("corp_code")
        reports = {}
        for row in candidates[-3:]:
            if row["fiscal_year"] < annual_year - 2:
                continue
            b = row.get("detail_basis") or row.get("statement_basis")
            end = f"{row['fiscal_year']}-12-31"
            if end > as_of.isoformat() or b != basis or row.get("corp_code") != corp_code:
                continue
            report = store.api((row.get("detail_api_raw_refs") or {}).get(b), ticker, b, end, corp_code)
            report = report or store.bulk(row["fiscal_year"], "11011").get((ticker, b))
            if report:
                reports[end] = report
        # Quarterly eligibility only requires BS and IS. Missing cash-flow
        # lines in the collector must not hide an otherwise usable report.
        due_report = store.bulk(year, code).get((ticker, basis)) if due_end > f"{annual_year}-12-31" else None
        if due_report:
            reports[due_end] = due_report
        current = (interim.get("companies") or {}).get(ticker) or {}
        # Even a CF-incomplete report can have complete BS and IS for ROE.
        end = current.get("period_end", "")
        if current.get("status") == "ok" and end and end <= as_of.isoformat() and current.get("basis") == basis and current.get("corp_code") == corp_code:
            report = store.api(current.get("raw_ref"), ticker, basis, end, corp_code)
            report = report or store.bulk(current["fiscal_year"], current["report_code"]).get((ticker, basis))
            if report:
                reports[end] = report
        selected_end = max(reports, default="")
        reasons = []
        result = {"eligible": False, "roe_pct": None, "roa_pct": None,
                  "quality_reasons": reasons, "required_period_end": required_end,
                  "latest_available_period_end": selected_end or None}
        if not selected_end:
            reasons.append("missing_latest_report")
        elif selected_end < required_end:
            reasons.append("stale_report")
            result["period_end"] = selected_end
        else:
            selected = reports[selected_end]
            previous_end = str(int(selected_end[:4]) - 1) + selected_end[4:]
            if selected_end.endswith("12-31"):
                start = (reports.get(previous_end) or {}).get("current") or selected["previous"]
                income = selected["current"]
                sources = selected["sources"]
            else:
                annual = reports.get(f"{int(selected_end[:4]) - 1}-12-31") or {}
                prior = store.bulk(int(selected_end[:4]) - 1, REPORTS[selected_end[5:]]).get((ticker, basis)) or {}
                start = prior.get("current", {})
                prior_income = {**prior.get("current", {}), **selected["previous"]}
                income = trailing_income(annual.get("current", {}), selected["current"], prior_income)
                sources = selected["sources"] + annual.get("sources", []) + prior.get("sources", [])
            history = [r["current"] for e, r in reports.items() if e.endswith("12-31") and previous_end <= e <= selected_end]
            # Include the annual opening balance, which can expose a recovery
            # from capital impairment during the latest reporting window.
            if not selected_end.endswith("12-31"):
                history += [r["current"] for e, r in reports.items() if e == f"{int(selected_end[:4]) - 2}-12-31"]
            result.update(evaluate_returns(start, selected["current"], income, period_end=selected_end,
                          basis=basis, method="annual" if selected_end.endswith("12-31") else "ttm", capital_history=history))
            if (latest.get("detail_validation") or {}).get("calculation_blocked"):
                result["quality_reasons"].append("conflicting_financial_sources")
                result["eligible"] = False
            result["sources"] = sorted(set(sources))
            result["latest_available_period_end"] = selected_end
            result["share_count_as_of"] = market.get("crawled_at_utc")
            share_classes = [stock, *preferred_by_common[ticker]]
            shares = sum(s.get("listed_shares_exact") or (s.get("listed_shares") or 0) * 1000 for s in share_classes)
            if shares > 0:
                equity = result.get("owners_equity")
                profit = result.get("owners_net_income")
                result["bps"] = equity / shares if equity is not None and equity > 0 else None
                result["eps"] = profit / shares if profit is not None else None
                result["share_count_basis"] = "exact" if all(s.get("listed_shares_exact") for s in share_classes) else "rounded_thousand"
                result["share_count_includes_preferred"] = len(share_classes) > 1
            # Only clean historical annual ROEs can inform scenario bounds.
            clean_history = []
            for e, r in sorted(reports.items()):
                prior_end = str(int(e[:4]) - 1) + "-12-31"
                if not e.endswith("12-31") or prior_end not in reports:
                    continue
                historical = evaluate_returns(reports[prior_end]["current"], r["current"], r["current"],
                                              period_end=e, basis=basis, method="annual")
                if historical["eligible"]:
                    clean_history.append({"period": e, "roe": historical["roe_pct"]})
            result["clean_roe_history"] = clean_history
        result["ticker"] = ticker
        metrics[ticker] = result
    counts = Counter(reason for m in metrics.values() for reason in m["quality_reasons"])
    return {"schema_version": 1, "generated_at_utc": utc_now_iso(), "as_of": as_of.isoformat(),
            "market_data_updated_at_utc": market.get("crawled_at_utc"),
            "required_period_end": required_end, "source": "OpenDART full financial statements",
            "methodology": {"roe": "parent TTM net income / mean parent equity at matching year-apart endpoints",
                            "roa": "TTM total net income / mean total assets at matching endpoints",
                            "thin_equity_floor": 0.05, "material_discontinued_profit_share": 0.10,
                            "missing_latest_policy": "exclude; never use vendor ROE as fallback"},
            "summary": {"company_count": len(metrics), "eligible_count": sum(m["eligible"] for m in metrics.values()),
                        "excluded_by_reason": dict(counts)}, "metrics": metrics}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--as-of", default=datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat())
    parser.add_argument("--fetch-prior-balances", action="store_true")
    args = parser.parse_args()
    root, as_of = Path(args.data_dir), date.fromisoformat(args.as_of)
    year, code, _ = latest_due_period(as_of)
    if args.fetch_prior_balances:
        ensure_prior_balances(root, year, code)
    payload = build_metrics(load_financial_panel(root / "dart_financial_panel.json"),
                            read_json(root / "market_sum.json"), read_json(root / "dart_financial_interim.json"),
                            RawReports(root), as_of)
    atomic_write_json(root / "valuation_metrics.json", payload, compact=True)
    print("[VALUATION]", payload["summary"], flush=True)


if __name__ == "__main__":
    main()
