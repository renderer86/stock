"""Build latest, auditable valuation inputs from saved DART statements."""
from __future__ import annotations

import argparse
import calendar
from collections import Counter, defaultdict
from functools import lru_cache
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import unicodedata
from zoneinfo import ZoneInfo

from collector_common import atomic_write_json, utc_now_iso
from crawler_dart_financial_details import ACCOUNT_SPECS, account_rows, select_account, create_session, normalize_text, normalize_account_id, parse_amount
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
    "noncontrolling_net_income": {"statements": {"IS", "CIS"},
        "ids": {"ifrs-full_ProfitLossAttributableToNoncontrollingInterests"},
        "aliases": set()},
    "owners_continuing_net_income": {"statements": {"IS", "CIS"},
        "ids": {"ifrs-full_IncomeFromContinuingOperationsAttributableToOwnersOfParent"},
        "aliases": set()},
    "owners_discontinued_net_income": {"statements": {"IS", "CIS"},
        "ids": {"ifrs-full_IncomeFromDiscontinuedOperationsAttributableToOwnersOfParent"},
        "aliases": set()},
}
SPECS = {key: ACCOUNT_SPECS[key] for key in
         ("assets", "liabilities", "equity", "owners_equity", "net_income", "owners_net_income", "revenue", "operating_income", "pretax_income", "income_tax_expense")}
SPECS.update(EXTRA_SPECS)
SPECS["net_income"] = {**SPECS["net_income"], "aliases": SPECS["net_income"]["aliases"] | {
    "분기순이익손실", "반기순이익손실", "분기순손실", "반기순손실", "당기순손실",
    "분기순손익", "당기순손익", "연결당기순이익손실", "분기순이익", "반기순이익",
    "분기순이이익손실"}}
SPECS["owners_net_income"] = {**SPECS["owners_net_income"], "aliases": SPECS["owners_net_income"]["aliases"] | {
    "지배기업의소유주에게귀속되는당기순이익손실", "지배기업소유주에게귀속되는분기순이익손실",
    "지배기업소유주지분순이익손실"}}
ACCOUNT_IDS = {normalize_account_id(i) for spec in SPECS.values() for i in spec["ids"]}
ACCOUNT_NAMES = {normalize_text(n) for spec in SPECS.values() for n in spec["aliases"]}
REPORTS = {"03-31": "11013", "06-30": "11012", "09-30": "11014", "12-31": "11011"}


def report_period_end(year, code, fiscal_month=12):
    month = (fiscal_month - 1 - {"11011": 0, "11013": 9, "11012": 6, "11014": 3}[code]) % 12 + 1
    return date(year, month, calendar.monthrange(year, month)[1]).isoformat()


@lru_cache(maxsize=256)
def company_due_period(as_of, fiscal_month=12, *, annual_only=False):
    periods = []
    for year in range(as_of.year - 2, as_of.year + 2):
        for code in (["11011"] if annual_only else REPORTS.values()):
            end = date.fromisoformat(report_period_end(year, code, fiscal_month))
            deadline = (date(year + 1, 3, 31) if code == "11011" and fiscal_month == 12
                        else end + timedelta(days=90 if code == "11011" else 45))
            if deadline <= as_of:
                periods.append((end.isoformat(), year, code))
    end, year, code = max(periods)
    return year, code, end


def get_report(store, year, code, ticker, basis, corp_code, fiscal_month=12, legacy_ref=None):
    bulk = store.bulk(year, code).get((ticker, basis))
    end = (bulk or {}).get("period_end") or report_period_end(year, code, fiscal_month)
    if isinstance(store, RawReports):
        ref = f"dart_financial_raw/{year}/api/valuation_{code}_{basis}_{ticker[0]}.json.gz"
        if (store.data_dir / ref).exists():
            report = store.api(ref, ticker, basis, end, corp_code, report_code=code, fiscal_year=year)
            if report:
                return report
        if legacy_ref:
            report = store.api(legacy_ref, ticker, basis, end, corp_code, report_code=code, fiscal_year=year)
            if report:
                return report
    elif legacy_ref:
        report = store.api(legacy_ref, ticker, basis, end, corp_code)
        if report:
            return report
    return bulk


@lru_cache(maxsize=65536)
def valuation_account_id(account_id, account_name=""):
    """Recognize explicit issuer extension tags without matching comprehensive income."""
    normalized = normalize_account_id(account_id)
    if not normalized.startswith("entity"):
        return normalized
    tag = normalized.split("_", 1)[-1]
    extensions = {
        "profitlossattributabletoownersofparentofprofitloss": "profitlossattributabletoownersofparent",
        "profitlossattributabletononcontrollinginterestsofprofitloss": "profitlossattributabletononcontrollinginterests",
        "noncontrollinginterestsofprofitloss": "profitlossattributabletononcontrollinginterests",
    }
    if tag in extensions:
        return "ifrs-full_" + extensions[tag]
    # Opaque issuer IDs sometimes still identify the ProfitLoss concept. The
    # exact owner label is usable only in that explicit profit/loss context.
    if tag.endswith(("_profitloss", "ofprofitloss")):
        name = normalize_text(re.sub(r"^\s*\d+[.)]\s*", "", str(account_name)))
        if name in {"지배기업소유주지분", "지배기업의소유주지분", "지배기업의소유지분",
                    "지배기업의소유주", "지배기업소유주"}:
            return "ifrs-full_profitlossattributabletoownersofparent"
        if name in {"비지배지분", "비지배주주지분"}:
            return "ifrs-full_profitlossattributabletononcontrollinginterests"
    return normalized


@lru_cache(maxsize=65536)
def valuation_account_name(name):
    text = unicodedata.normalize("NFKC", str(name or "")).strip()
    return re.sub(r"^(?:[IVXLCDM]+|\d+)[.)．]\s*", "", text, flags=re.IGNORECASE)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def standardized(rows, basis):
    # SCE carries explicit owner allocations even when IS/CIS omits that split.
    # Only the aggregate member is valid; retained earnings is a subcomponent.
    allocations = defaultdict(list)
    owner_components = defaultdict(list)
    unhandled_component = False
    owner_members = {"지배기업의소유주에게귀속되는지분", "지배기업의소유주에게귀속되는자본", "지배기업소유주지분",
                     "지배기업지분", "지배기업소유지분", "지배주주지분계", "지배기업의소유주"}
    roots = {"자본", "자본의구성요소", "연결재무제표"}
    component_names = {"자본금", "자본잉여금", "주식발행초과금", "이익잉여금", "이익잉여금결손금",
                       "미처분이익잉여금미처리결손금",
                       "기타포괄손익누계액", "기타자본", "기타자본항목", "기타자본구성요소",
                       "기타불입자본", "기타적립금", "자기주식"}
    for row in rows:
        profit_name = normalize_text(valuation_account_name(row.get("account_nm")))
        profit_id = normalize_account_id(row.get("account_id"))
        profit_aliases = {normalize_text(n) for n in SPECS["net_income"]["aliases"]}
        if row.get("sj_div") != "SCE" or not (profit_id == "ifrs-full_profitloss" or profit_name in profit_aliases):
            continue
        detail = [normalize_text(re.sub(r"\[[^]]*\]", "", valuation_account_name(part))) for part in row.get("account_detail", "").split("|")]
        known_component = detail and detail[-1] in component_names and all(part in roots | owner_members for part in detail[:-1])
        aggregate_member = detail and detail[-1] in owner_members | {"비지배지분", "비지배주주지분"} and all(part in roots for part in detail[:-1])
        root_member = (len(detail) == 1 and detail[0] in roots) or (detail[-1] in {"합계", "합계구간", "자본총계", "자본합계"}
            and all(part in roots for part in detail[:-1]))
        nested_component = any(part in component_names for part in detail[:-1])
        if not (known_component or aggregate_member or root_member or nested_component) and parse_amount(row.get("thstrm_amount")) != 0:
            unhandled_component = True
        if detail and detail[-1] in component_names and all(part in roots | owner_members for part in detail[:-1]):
            owner_components[detail[-1]].append(row)
        if not detail or any(part not in roots for part in detail[:-1]):
            continue
        if detail[-1] in owner_members:
            account_id = "ifrs-full_ProfitLossAttributableToOwnersOfParent"
        elif detail[-1] in {"비지배지분", "비지배주주지분"}:
            account_id = "ifrs-full_ProfitLossAttributableToNoncontrollingInterests"
        else:
            continue
        allocations[account_id].append(row)
    additions = []
    for account_id, candidates in allocations.items():
        amounts = {str(r.get("thstrm_amount")) for r in candidates if r.get("thstrm_amount") not in (None, "")}
        if len(amounts) == 1:
            row = next(r for r in candidates if r.get("thstrm_amount") not in (None, ""))
            additions.append({**row, "sj_div": "IS", "account_id": account_id, "account_nm": ""})
    # A CF line explicitly tagged total ProfitLoss is the same cumulative
    # profit, not cash from operations. It can repair a blank IS total.
    additions.extend({**row, "sj_div": "IS", "account_nm": ""} for row in rows
        if row.get("sj_div") == "CF" and normalize_account_id(row.get("account_id")) == "ifrs-full_profitloss"
        and row.get("account_detail", "-") in {"", "-"})
    rows = [*rows, *additions]
    normalized = account_rows([{**row, "account_id": valuation_account_id(row.get("account_id"), row.get("account_nm", "")),
                                "account_nm": valuation_account_name(row.get("account_nm"))}
                               for row in rows])
    values = {key: amount for key, spec in SPECS.items()
              if (amount := select_account(normalized, spec)[0]) is not None}
    # Sum explicitly reported owner equity-component allocations only when
    # they reconcile exactly to total profit and any reported minority share.
    # Never treat a retained-earnings balance as period profit.
    if "owners_net_income" not in values and "net_income" in values and owner_components and not unhandled_component:
        component_amounts = [{parse_amount(r.get("thstrm_amount")) for r in candidates}
                             for candidates in owner_components.values()]
        if all(len(amounts) == 1 and None not in amounts for amounts in component_amounts):
            owner_total = sum(next(iter(amounts)) for amounts in component_amounts)
            if owner_total + values.get("noncontrolling_net_income", 0) == values["net_income"]:
                values["owners_net_income"] = owner_total
    # The reported parent and noncontrolling amounts reconcile to total profit.
    # A missing minority amount remains unknown, including when it is blank.
    def reconcile_income():
        minority = values.get("noncontrolling_net_income")
        if minority is not None:
            if "net_income" not in values and "owners_net_income" in values:
                values["net_income"] = values["owners_net_income"] + minority
            elif "owners_net_income" not in values and "net_income" in values:
                values["owners_net_income"] = values["net_income"] - minority

    reconcile_income()
    income_rows = [r for r in normalized if r["statement"] in {"IS", "CIS"}]
    spec = SPECS["discontinued_net_income"]
    has_discontinued_line = any(normalize_account_id(r["account_id"]) in {normalize_account_id(i) for i in spec["ids"]}
        or ("중단영업" in r["normalized_name"] and "주당" not in r["normalized_name"] and "포괄" not in r["normalized_name"])
        for r in income_rows)
    if "continuing_net_income" not in values and not has_discontinued_line and "net_income" not in values \
            and all(k in values for k in ("pretax_income", "income_tax_expense")):
        values["continuing_net_income"] = values["pretax_income"] - values["income_tax_expense"]
    if "discontinued_net_income" not in values and all(k in values for k in ("net_income", "continuing_net_income")):
        values["discontinued_net_income"] = values["net_income"] - values["continuing_net_income"]
    # A full income statement without a discontinued-operations line reports no
    # separate discontinued result. An explicit blank line remains unknown.
    if "discontinued_net_income" not in values and income_rows and ("net_income" in values or "continuing_net_income" in values) and not any(
        normalize_account_id(r["account_id"]) in {normalize_account_id(i) for i in spec["ids"]}
        or ("중단영업" in r["normalized_name"] and "주당" not in r["normalized_name"]
            and "포괄" not in r["normalized_name"])
        for r in income_rows
    ):
        values["discontinued_net_income"] = 0
    if "net_income" not in values and all(k in values for k in ("continuing_net_income", "discontinued_net_income")):
        values["net_income"] = values["continuing_net_income"] + values["discontinued_net_income"]
        reconcile_income()
    if "continuing_net_income" not in values and all(k in values for k in ("net_income", "discontinued_net_income")):
        values["continuing_net_income"] = values["net_income"] - values["discontinued_net_income"]
    if "owners_net_income" not in values and "owners_continuing_net_income" in values:
        if "owners_discontinued_net_income" in values:
            values["owners_net_income"] = values["owners_continuing_net_income"] + values["owners_discontinued_net_income"]
        elif values.get("discontinued_net_income") == 0:
            values["owners_net_income"] = values["owners_continuing_net_income"]
    # CFS must never mix total profit with parent-only capital. Missing parent
    # amounts are unknown; OFS is the only basis where totals are equivalent.
    if basis == "OFS":
        for parent, total in (("owners_equity", "equity"), ("owners_net_income", "net_income")):
            if parent not in values and total in values:
                values[parent] = values[total]
    return values


def parse_report(rows, basis, end, sources, report_code=None, fiscal_year=None):
    report_code = report_code or REPORTS.get(end[5:])
    quarter = report_code != "11011"
    current_rows, previous_rows = [], []
    for row in rows:
        income = row.get("sj_div") in {"IS", "CIS"}
        current = row.get("thstrm_add_amount") if income and quarter else row.get("thstrm_amount")
        previous = row.get("frmtrm_add_amount") if income and quarter else row.get("frmtrm_amount")
        if row.get("sj_div") in {"SCE", "CF"} and quarter:
            previous = row.get("frmtrm_q_amount")
        # The first quarter is itself cumulative; later quarters require YTD.
        if income and report_code == "11013":
            current = current if current not in (None, "") else row.get("thstrm_amount")
            previous = previous if previous not in (None, "") else row.get("frmtrm_q_amount")
        current_rows.append({**row, "thstrm_amount": current, "thstrm_add_amount": None})
        previous_rows.append({**row, "thstrm_amount": previous, "thstrm_add_amount": None})
    return {"basis": basis, "period_end": end, "report_code": report_code,
            "fiscal_year": fiscal_year or int(end[:4]),
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
                        if len(cells) <= max(11, cur) or str(cells[9]).strip() != "KRW":
                            continue
                        ticker = normalize_stock_code(cells[1])
                        end = str(cells[7]).strip()
                        month = str(cells[6]).strip()
                        if not ticker or not month.isdigit() or not 1 <= int(month) <= 12 or not end.startswith(str(year)):
                            continue
                        account_id, account_name = str(cells[10]).strip(), str(cells[11]).strip()
                        if valuation_account_id(account_id, account_name) not in ACCOUNT_IDS and normalize_text(valuation_account_name(account_name)) not in ACCOUNT_NAMES and "중단영업" not in normalize_text(account_name):
                            continue
                        def cell(i):
                            return str(cells[i]).strip() if i is not None and i < len(cells) else None
                        report_key = (ticker, raw["basis"], end)
                        grouped[report_key].append({"sj_div": "BS" if statement == "BS" else "IS",
                            "account_id": cell(10), "account_nm": cell(11), "thstrm_amount": cell(cur),
                            "thstrm_add_amount": cell(cum), "frmtrm_amount": cell(old),
                            "frmtrm_add_amount": cell(old), "frmtrm_q_amount": cell(prev_quarter)})
                        sources[report_key].add(path.relative_to(self.data_dir).as_posix())
        self.cache[key] = {(t, b): parse_report(rows, b, end, sources[(t, b, end)], code, year)
                           for (t, b, end), rows in grouped.items()}
        return self.cache[key]

    def api(self, reference, ticker, basis, end, corp_code, *, report_code=None, fiscal_year=None):
        if not reference:
            return None
        if reference not in self.api_cache:
            self.api_cache[reference] = read_gzip_json(self.data_dir / reference)
        record = self.api_cache[reference].get("records_by_ticker", {}).get(ticker, {})
        params = record.get("request_parameters", {})
        report_code = report_code or REPORTS.get(end[5:])
        fiscal_year = str(fiscal_year or end[:4])
        if record.get("response_status") != "000" or params.get("fs_div") != basis or params.get("corp_code") != corp_code or params.get("bsns_year") != fiscal_year or params.get("reprt_code") != report_code:
            return None
        rows = record.get("rows", [])
        if not rows or any(row.get("currency") != "KRW" or row.get("corp_code") != corp_code
                           or row.get("bsns_year") != fiscal_year or row.get("reprt_code") != report_code for row in rows):
            return None
        return parse_report(rows, basis, end, [reference], report_code, int(fiscal_year))


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
    market_by_code = {s["code"]: s for s in market_stocks}
    preferred_by_common = defaultdict(list)
    common_by_preferred = {}
    common_by_prefix = {s["code"][:5]: s for s in market_stocks if s["code"].endswith("0")}
    for stock in market_stocks:
        common = common_by_prefix.get(stock["code"][:5])
        if common and stock["code"] != common["code"]:
            suffix = str(stock.get("name", ""))[len(str(common.get("name", ""))):]
            if str(stock.get("name", "")).startswith(str(common.get("name", ""))) and re.fullmatch(r"(?:\d+)?우[A-Z]?", suffix):
                preferred_by_common[common["code"]].append(stock)
                common_by_preferred[stock["code"]] = common["code"]
    default_annual_year = annual_year
    for stock in market_stocks:
        ticker = stock["code"]
        annual_year = default_annual_year
        financial_ticker = common_by_preferred.get(ticker, ticker)
        candidates = sorted(annual_by_ticker.get(financial_ticker, []), key=lambda r: r["fiscal_year"])
        latest = candidates[-1] if candidates else {}
        basis = latest.get("detail_basis") or latest.get("statement_basis")
        corp_code = latest.get("corp_code")
        latest_annual = store.bulk(latest.get("fiscal_year", annual_year), "11011").get((financial_ticker, basis)) or {}
        settlement = (latest.get("share_data") or {}).get("settlement_date") or latest_annual.get("period_end") or f"{annual_year}-12-31"
        fiscal_month = int(settlement[5:7])
        company_year, company_code, company_end = company_due_period(as_of, fiscal_month)
        company_annual_year, _, _ = company_due_period(as_of, fiscal_month, annual_only=True)
        annual_year = company_annual_year
        reports = {}
        annual_candidates = {row["fiscal_year"]: row for row in candidates[-3:]}
        for annual_candidate in range(annual_year - 2, annual_year + 1):
            annual_candidates.setdefault(annual_candidate, {**latest, "fiscal_year": annual_candidate, "detail_api_raw_refs": {}})
        for row in annual_candidates.values():
            if row["fiscal_year"] < annual_year - 2:
                continue
            b = row.get("detail_basis") or row.get("statement_basis")
            end = report_period_end(row['fiscal_year'], "11011", fiscal_month)
            if end > as_of.isoformat() or b != basis or row.get("corp_code") != corp_code:
                continue
            report = get_report(store, row["fiscal_year"], "11011", financial_ticker, b, corp_code,
                                fiscal_month, (row.get("detail_api_raw_refs") or {}).get(b))
            if report:
                reports[report["period_end"]] = report
        # Quarterly eligibility only requires BS and IS. Missing cash-flow
        # lines in the collector must not hide an otherwise usable report.
        due_report = get_report(store, company_year, company_code, financial_ticker, basis, corp_code, fiscal_month)
        if due_report:
            reports[due_report["period_end"]] = due_report
        if fiscal_month != 12:
            for other_code in ("11013", "11012", "11014"):
                report = get_report(store, as_of.year, other_code, financial_ticker, basis, corp_code, fiscal_month)
                if report and report["period_end"] <= as_of.isoformat():
                    reports[report["period_end"]] = report
        current = (interim.get("companies") or {}).get(financial_ticker) or {}
        # Even a CF-incomplete report can have complete BS and IS for ROE.
        end = current.get("period_end", "")
        if current.get("status") == "ok" and end and end <= as_of.isoformat() and current.get("basis") == basis and current.get("corp_code") == corp_code:
            report = get_report(store, current["fiscal_year"], current["report_code"], financial_ticker, basis, corp_code,
                                fiscal_month, current.get("raw_ref"))
            if report and report["period_end"] <= as_of.isoformat():
                reports[report["period_end"]] = report
        selected_end = max(reports, default="")
        reasons = []
        result = {"eligible": False, "roe_pct": None, "roa_pct": None,
                  "quality_reasons": reasons, "required_period_end": company_end, "fiscal_month": fiscal_month,
                  "latest_available_period_end": selected_end or None}
        if not selected_end:
            reasons.append("missing_latest_report")
        elif selected_end < company_end:
            reasons.append("stale_report")
            result["period_end"] = selected_end
        else:
            selected = reports[selected_end]
            selected_code = selected.get("report_code") or REPORTS.get(selected_end[5:])
            selected_year = selected.get("fiscal_year") or int(selected_end[:4])
            is_annual = selected_code == "11011"
            selected_prior = selected["previous"]
            previous_end = report_period_end(selected_year - 1, selected_code, fiscal_month)
            if is_annual:
                start = (reports.get(previous_end) or {}).get("current") or selected["previous"]
                income = selected["current"]
                sources = selected["sources"]
            else:
                annual = max((r for e, r in reports.items() if (r.get("report_code") == "11011" or e.endswith("12-31"))
                              and e < selected_end), key=lambda r: r["period_end"], default={})
                prior = get_report(store, selected_year - 1, selected_code, financial_ticker, basis, corp_code, fiscal_month) or {}
                start = prior.get("current", {})
                prior_income = {**prior.get("current", {}), **selected["previous"]}
                selected_prior = prior_income
                income = trailing_income(annual.get("current", {}), selected["current"], prior_income)
                sources = selected["sources"] + annual.get("sources", []) + prior.get("sources", [])
            history = [r["current"] for e, r in reports.items() if e == report_period_end(int(e[:4]), "11011", fiscal_month) and previous_end <= e <= selected_end]
            # Include the annual opening balance, which can expose a recovery
            # from capital impairment during the latest reporting window.
            if not is_annual:
                prior_annual_year = int(annual.get("period_end", f"{selected_year - 1}-12-31")[:4]) - 1
                history += [r["current"] for e, r in reports.items() if e == report_period_end(prior_annual_year, "11011", fiscal_month)]
            result.update(evaluate_returns(start, selected["current"], income, period_end=selected_end,
                          basis=basis, method="annual" if is_annual else "ttm", capital_history=history))
            if (latest.get("detail_validation") or {}).get("calculation_blocked"):
                result["quality_reasons"].append("conflicting_financial_sources")
                result["eligible"] = False
            result["sources"] = sorted(set(sources))
            result["latest_available_period_end"] = selected_end
            result["report_code"] = selected_code
            result["fiscal_year"] = selected_year
            result["start_owners_equity"] = start.get("owners_equity")
            result["start_assets"] = start.get("assets")
            result["income_inputs"] = ({"annual": {"period_end": selected_end, **{k: income.get(k) for k in ("net_income", "owners_net_income")}}}
                if is_annual else {name: {"period_end": period, **{k: amounts.get(k) for k in ("net_income", "owners_net_income", "continuing_net_income", "discontinued_net_income")}}
                    for name, period, amounts in [("annual", annual.get("period_end"), annual.get("current", {})),
                        ("current_ytd", selected_end, selected["current"]), ("previous_ytd", previous_end, prior_income)]})
            def growth(key):
                current_value = selected["current"].get(key)
                prior_value = selected_prior.get(key)
                if current_value is None or prior_value is None or prior_value <= 0:
                    return None
                return round((current_value / prior_value - 1) * 100, 4)

            result["financials"] = {
                "source": "OpenDART", "period_end": selected_end, "basis": basis,
                "assets": selected["current"].get("assets"),
                "liabilities": selected["current"].get("liabilities"),
                "revenue_ytd": selected["current"].get("revenue"),
                "operating_income_ytd": selected["current"].get("operating_income"),
                "revenue_yoy_pct": growth("revenue"),
                "operating_income_yoy_pct": growth("operating_income"),
            }
            result["share_count_as_of"] = market.get("crawled_at_utc")
            share_classes = [market_by_code[financial_ticker], *preferred_by_common[financial_ticker]]
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
                prior_end = report_period_end(int(e[:4]) - 1, "11011", fiscal_month)
                if e != report_period_end(int(e[:4]), "11011", fiscal_month) or prior_end not in reports:
                    continue
                historical = evaluate_returns(reports[prior_end]["current"], r["current"], r["current"],
                                              period_end=e, basis=basis, method="annual")
                if historical["eligible"]:
                    clean_history.append({"period": e, "roe": historical["roe_pct"]})
            result["clean_roe_history"] = clean_history
        result["ticker"] = ticker
        result["financial_ticker"] = financial_ticker
        metrics[ticker] = result
    counts = Counter(reason for m in metrics.values() for reason in m["quality_reasons"])
    return {"schema_version": 1, "generated_at_utc": utc_now_iso(), "as_of": as_of.isoformat(),
            "market_data_updated_at_utc": market.get("crawled_at_utc"),
            "required_period_end": required_end, "source": "OpenDART full financial statements",
            "methodology": {"roe": "parent TTM net income / mean parent equity at matching year-apart endpoints",
                            "universe": "all KOSPI/KOSDAQ market quotes; no vendor ROE prefilter",
                            "financial_source": "OpenDART", "quote_source": "Naver",
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
