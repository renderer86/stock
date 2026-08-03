from __future__ import annotations

import argparse
import math
import os
import re
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from collector_common import USER_AGENT, request_json, utc_now_iso
from dart_financial_storage import load_financial_panel, save_financial_panel
from dart_financial_raw_storage import ApiRawAccumulator, DEFAULT_RAW_ROOT
from env_loader import load_env_file


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_PANEL = Path("data/dart_financial_panel.json")
DEFAULT_MARKET_SUM = Path("data/market_sum.json")
DART_FULL_ACCOUNT_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
DART_STOCK_TOTAL_URL = "https://opendart.fss.or.kr/api/stockTotqySttus.json"
DART_DIVIDEND_URL = "https://opendart.fss.or.kr/api/alotMatter.json"
ANNUAL_REPORT_CODE = "11011"
KST = ZoneInfo("Asia/Seoul")
DETAIL_SCHEMA_VERSION = 1
TERMINAL_STATUSES = {"complete", "no_data", "not_required"}


class DartRateLimitError(RuntimeError):
    """Raised when OpenDART refuses more requests for the current day."""


class RequestBudgetReached(RuntimeError):
    """Raised before a request that would exceed this run's request budget."""


def parse_args() -> argparse.Namespace:
    current_year = datetime.now(KST).year
    parser = argparse.ArgumentParser(
        description=(
            "Enrich the DART annual panel with standardized full-statement accounts "
            "needed for ROIC, GP/A, cash conversion and Piotroski calculations."
        )
    )
    parser.add_argument("--panel", default=str(DEFAULT_PANEL))
    parser.add_argument("--market-sum", default=str(DEFAULT_MARKET_SUM))
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT))
    parser.add_argument("--start-year", type=int, default=0)
    parser.add_argument("--end-year", type=int, default=current_year - 1)
    parser.add_argument("--codes", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--max-requests",
        type=int,
        default=5000,
        help="Maximum OpenDART full-statement API requests in this run.",
    )
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument(
        "--max-runtime-minutes",
        type=float,
        default=150,
        help=(
            "Stop cleanly and save a checkpoint before the GitHub Actions job "
            "timeout. Set 0 to disable."
        ),
    )
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--max-consecutive-errors", type=int, default=5)
    parser.add_argument(
        "--reset-details",
        action="store_true",
        help="Remove every existing detail result before collecting.",
    )
    parser.add_argument(
        "--refresh-latest",
        action="store_true",
        help="Refetch details for the requested end year only.",
    )
    parser.add_argument(
        "--supplements-only",
        action="store_true",
        help="Skip full-statement API calls and collect only share/dividend supplements.",
    )
    parser.add_argument(
        "--supplement-profile",
        choices=("all", "screens", "none"),
        default="all",
        help=(
            "all=share/dividend for every year; screens=shares for oldest/latest-1/"
            "latest and dividends for latest 3 years; none=no share/dividend calls."
        ),
    )
    parser.add_argument(
        "--rebuild-screens-only",
        action="store_true",
        help=(
            "Recalculate screening_features from the stored panel and market "
            "snapshot without making OpenDART requests."
        ),
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_market_lookup(path: Path) -> tuple[dict[str, dict[str, Any]], str | None]:
    payload = load_json(path)
    lookup: dict[str, dict[str, Any]] = {}
    for stock in payload.get("stocks") or []:
        ticker = str(stock.get("code") or "").strip().zfill(6)
        market_cap_100m = stock.get("market_cap_krw_100m")
        if re.fullmatch(r"\d{6}", ticker):
            lookup[ticker] = {
                "current_price": stock.get("current_price"),
                "market_cap_krw_100m": market_cap_100m,
                "market_cap_krw": (
                    market_cap_100m * 100_000_000
                    if isinstance(market_cap_100m, (int, float))
                    else None
                ),
            }
    return lookup, (
        payload.get("crawled_at_utc")
        or payload.get("crawled_at")
        or payload.get("updated_at")
    )


def normalize_text(value: Any) -> str:
    return re.sub(r"[\s·ㆍ,()\[\]{}_\-]", "", str(value or "")).lower()


def normalize_account_id(value: Any) -> str:
    account_id = str(value or "").strip().lower()
    if account_id.startswith("ifrs_"):
        return "ifrs-full_" + account_id.removeprefix("ifrs_")
    return account_id


def parse_amount(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "N/A"}:
        return None
    negative_parentheses = text.startswith("(") and text.endswith(")")
    if negative_parentheses:
        text = text[1:-1]
    try:
        amount = int(float(text))
    except ValueError:
        return None
    return -amount if negative_parentheses else amount


def safe_ratio(
    numerator: int | float | None,
    denominator: int | float | None,
) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    value = float(numerator) / float(denominator)
    return round(value, 6) if math.isfinite(value) else None


def pct(
    numerator: int | float | None,
    denominator: int | float | None,
) -> float | None:
    value = safe_ratio(numerator, denominator)
    return round(value * 100, 4) if value is not None else None


def sum_known(*values: int | float | None) -> int | float | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )
    return session


# Exact account IDs are preferred. Korean aliases are fallbacks for issuer-specific IDs.
# `contains` is intentionally narrow because broad matching can silently select subtotals.
ACCOUNT_SPECS: dict[str, dict[str, Any]] = {
    "assets": {
        "statements": {"BS"},
        "ids": {"ifrs-full_Assets"},
        "aliases": {"자산총계"},
    },
    "current_assets": {
        "statements": {"BS"},
        "ids": {"ifrs-full_CurrentAssets"},
        "aliases": {"유동자산", "유동자산합계"},
    },
    "liabilities": {
        "statements": {"BS"},
        "ids": {"ifrs-full_Liabilities"},
        "aliases": {"부채총계"},
    },
    "current_liabilities": {
        "statements": {"BS"},
        "ids": {"ifrs-full_CurrentLiabilities"},
        "aliases": {"유동부채", "유동부채합계"},
    },
    "equity": {
        "statements": {"BS"},
        "ids": {"ifrs-full_Equity"},
        "aliases": {"자본총계"},
    },
    "owners_equity": {
        "statements": {"BS"},
        "ids": {
            "ifrs-full_EquityAttributableToOwnersOfParent",
            "dart_EquityAttributableToOwnersOfParent",
        },
        "aliases": {
            "지배기업의소유주에게귀속되는자본",
            "지배기업소유주지분",
            "지배주주지분",
        },
    },
    "cash": {
        "statements": {"BS"},
        "ids": {"ifrs-full_CashAndCashEquivalents"},
        "aliases": {"현금및현금성자산", "현금및현금성자산합계"},
    },
    "short_term_financial_assets": {
        "statements": {"BS"},
        "ids": {
            "ifrs-full_CurrentFinancialAssets",
            "dart_ShortTermFinancialInstruments",
        },
        "aliases": {
            "단기금융상품",
            "단기금융자산",
            "유동금융자산",
        },
    },
    "short_term_borrowings": {
        "statements": {"BS"},
        "ids": {"dart_ShortTermBorrowings"},
        "aliases": {"단기차입금"},
    },
    "current_portion_long_term_debt": {
        "statements": {"BS"},
        "ids": {
            "dart_CurrentPortionOfLongTermBorrowings",
            "dart_CurrentPortionOfLongTermDebt",
        },
        "aliases": {
            "유동성장기차입금",
            "유동성장기부채",
        },
    },
    "current_bonds": {
        "statements": {"BS"},
        "ids": {"dart_CurrentPortionOfBonds"},
        "aliases": {"유동성사채"},
    },
    "long_term_borrowings": {
        "statements": {"BS"},
        "ids": {
            "dart_LongTermBorrowingsGross",
            "dart_LongTermBorrowings",
        },
        "aliases": {"장기차입금"},
    },
    "bonds": {
        "statements": {"BS"},
        "ids": {"dart_BondsIssued", "dart_Bonds"},
        "aliases": {"사채", "회사채"},
    },
    "lease_liabilities_current": {
        "statements": {"BS"},
        "ids": {"ifrs-full_LeaseLiabilitiesCurrent"},
        "aliases": {"유동리스부채", "리스부채유동"},
    },
    "lease_liabilities_noncurrent": {
        "statements": {"BS"},
        "ids": {"ifrs-full_LeaseLiabilitiesNoncurrent"},
        "aliases": {"비유동리스부채", "리스부채비유동"},
    },
    "inventories": {
        "statements": {"BS"},
        "ids": {"ifrs-full_Inventories"},
        "aliases": {"재고자산"},
    },
    "property_plant_equipment": {
        "statements": {"BS"},
        "ids": {"ifrs-full_PropertyPlantAndEquipment"},
        "aliases": {"유형자산"},
    },
    "investment_property": {
        "statements": {"BS"},
        "ids": {"ifrs-full_InvestmentProperty"},
        "aliases": {"투자부동산"},
    },
    "land": {
        "statements": {"BS"},
        "ids": {"ifrs-full_Land"},
        "aliases": {"토지"},
    },
    "revenue": {
        "statements": {"IS", "CIS"},
        "ids": {"ifrs-full_Revenue"},
        "aliases": {"매출액", "수익매출액", "영업수익"},
    },
    "cost_of_sales": {
        "statements": {"IS", "CIS"},
        "ids": {"ifrs-full_CostOfSales"},
        "aliases": {"매출원가"},
    },
    "gross_profit": {
        "statements": {"IS", "CIS"},
        "ids": {"ifrs-full_GrossProfit"},
        "aliases": {"매출총이익", "매출총이익손실"},
    },
    "operating_income": {
        "statements": {"IS", "CIS"},
        "ids": {"dart_OperatingIncomeLoss"},
        "aliases": {"영업이익", "영업이익손실", "영업손익"},
    },
    "net_income": {
        "statements": {"IS", "CIS"},
        "ids": {"ifrs-full_ProfitLoss"},
        "aliases": {"당기순이익", "당기순이익손실", "연결당기순이익"},
    },
    "owners_net_income": {
        "statements": {"IS", "CIS"},
        "ids": {"ifrs-full_ProfitLossAttributableToOwnersOfParent"},
        "aliases": {
            "지배기업의소유주에게귀속되는당기순이익",
            "지배기업소유주지분순이익",
            "지배주주순이익",
        },
    },
    "pretax_income": {
        "statements": {"IS", "CIS"},
        "ids": {
            "ifrs-full_ProfitLossBeforeTax",
            "ifrs-full_ProfitLossFromContinuingOperationsBeforeTax",
        },
        "aliases": {
            "법인세비용차감전순이익",
            "법인세비용차감전순이익손실",
            "세전이익",
        },
    },
    "income_tax_expense": {
        "statements": {"IS", "CIS"},
        "ids": {
            "ifrs-full_IncomeTaxExpenseContinuingOperations",
            "ifrs-full_IncomeTaxExpense",
        },
        "aliases": {"법인세비용", "법인세비용수익"},
    },
    "interest_expense": {
        "statements": {"IS", "CIS"},
        "ids": {
            "ifrs-full_InterestExpense",
            "dart_InterestExpense",
        },
        "aliases": {"이자비용"},
    },
    "interest_paid": {
        "statements": {"CF"},
        "ids": {
            "ifrs-full_InterestPaidClassifiedAsOperatingActivities",
            "ifrs-full_InterestPaidClassifiedAsFinancingActivities",
        },
        "aliases": {"이자의지급", "이자지급"},
    },
    "basic_eps": {
        "statements": {"IS", "CIS"},
        "ids": {
            "ifrs-full_BasicEarningsLossPerShare",
            "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations",
        },
        "aliases": {"기본주당이익", "기본주당순이익"},
    },
    "operating_cash_flow": {
        "statements": {"CF"},
        "ids": {"ifrs-full_CashFlowsFromUsedInOperatingActivities"},
        "aliases": {"영업활동현금흐름", "영업활동으로인한현금흐름"},
    },
    "capex_ppe": {
        "statements": {"CF"},
        "ids": {
            "ifrs-full_PurchaseOfPropertyPlantAndEquipment",
            "dart_PurchaseOfPropertyPlantAndEquipment",
        },
        "aliases": {"유형자산의취득", "유형자산취득"},
    },
    "capex_intangibles": {
        "statements": {"CF"},
        "ids": {
            "ifrs-full_PurchaseOfIntangibleAssets",
            "dart_PurchaseOfIntangibleAssets",
        },
        "aliases": {"무형자산의취득", "무형자산취득"},
    },
    "dividends_paid": {
        "statements": {"CF"},
        "ids": {
            "ifrs-full_DividendsPaidClassifiedAsFinancingActivities",
            "dart_DividendsPaid",
        },
        "aliases": {"배당금지급", "배당금의지급"},
    },
    "treasury_stock_purchases": {
        "statements": {"CF"},
        "ids": {
            "ifrs-full_PaymentsForPurchaseOfTreasuryShares",
            "dart_AcquisitionOfTreasuryShares",
        },
        "aliases": {"자기주식의취득", "자기주식취득"},
    },
    "depreciation_amortization": {
        "statements": {"CF"},
        "ids": {
            "ifrs-full_AdjustmentsForDepreciationAndAmortisationExpense",
            "ifrs-full_DepreciationDepletionAndAmortisationExpense",
            "dart_DepreciationAndAmortization",
        },
        "aliases": {
            "감가상각비및무형자산상각비",
            "감가상각비와무형자산상각비",
        },
    },
    "depreciation_expense": {
        "statements": {"CF"},
        "ids": {
            "ifrs-full_AdjustmentsForDepreciationExpense",
            "ifrs-full_DepreciationExpense",
            "dart_Depreciation",
        },
        "aliases": {"감가상각비", "유형자산감가상각비"},
    },
    "amortization_expense": {
        "statements": {"CF"},
        "ids": {
            "ifrs-full_AdjustmentsForAmortisationExpense",
            "ifrs-full_AmortisationExpense",
            "dart_Amortization",
        },
        "aliases": {
            "무형자산상각비",
            "무형자산감가상각비",
            "상각비",
        },
    },
}


def account_rows(payload_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, row in enumerate(payload_rows):
        amount = parse_amount(row.get("thstrm_amount"))
        if amount is None:
            amount = parse_amount(row.get("thstrm_add_amount"))
        result.append(
            {
                "index": index,
                "statement": str(row.get("sj_div") or "").strip().upper(),
                "account_id": str(row.get("account_id") or "").strip(),
                "account_name": str(row.get("account_nm") or "").strip(),
                "normalized_name": normalize_text(row.get("account_nm")),
                "amount": amount,
            }
        )
    return result


def select_account(
    rows: list[dict[str, Any]],
    spec: dict[str, Any],
) -> tuple[int | None, dict[str, Any] | None]:
    statement_rows = [
        row
        for row in rows
        if row["statement"] in spec["statements"] and row["amount"] is not None
    ]
    ids = {normalize_account_id(value) for value in spec["ids"]}
    aliases = {normalize_text(value) for value in spec["aliases"]}

    for row in statement_rows:
        if normalize_account_id(row["account_id"]) in ids:
            return row["amount"], {
                "account_id": row["account_id"],
                "account_name": row["account_name"],
                "statement": row["statement"],
                "match": "account_id",
            }
    for row in statement_rows:
        if row["normalized_name"] in aliases:
            return row["amount"], {
                "account_id": row["account_id"],
                "account_name": row["account_name"],
                "statement": row["statement"],
                "match": "exact_alias",
            }
    return None, None


def standardize_accounts(
    payload_rows: list[dict[str, Any]],
) -> tuple[dict[str, int | None], dict[str, dict[str, Any]]]:
    rows = account_rows(payload_rows)
    values: dict[str, int | None] = {}
    matches: dict[str, dict[str, Any]] = {}
    for key, spec in ACCOUNT_SPECS.items():
        amount, match = select_account(rows, spec)
        values[key] = amount
        if match:
            matches[key] = match

    if values["gross_profit"] is None:
        revenue = values["revenue"]
        cost = values["cost_of_sales"]
        if revenue is not None and cost is not None:
            values["gross_profit"] = revenue - abs(cost)
            matches["gross_profit"] = {
                "match": "derived",
                "formula": "revenue - abs(cost_of_sales)",
            }
    return {
        key: value for key, value in values.items() if value is not None
    }, matches


def fetch_full_statement(
    session: requests.Session,
    api_key: str,
    corp_code: str,
    year: int,
    basis: str,
) -> tuple[str, list[dict[str, Any]], str]:
    payload = request_json(
        session,
        "GET",
        DART_FULL_ACCOUNT_URL,
        params={
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": ANNUAL_REPORT_CODE,
            "fs_div": basis,
        },
        attempts=3,
        timeout=60,
    )
    status = str(payload.get("status") or "")
    message = str(payload.get("message") or "")
    if status == "020":
        raise DartRateLimitError("OpenDART daily request limit was reached.")
    if status in {"000", "013"}:
        return status, payload.get("list") or [], message
    raise RuntimeError(f"OpenDART {status}: {message or 'unknown error'}")


def fetch_annual_report_api(
    session: requests.Session,
    api_key: str,
    url: str,
    corp_code: str,
    year: int,
) -> tuple[str, list[dict[str, Any]]]:
    payload = request_json(
        session,
        "GET",
        url,
        params={
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": ANNUAL_REPORT_CODE,
        },
        attempts=3,
        timeout=60,
    )
    status = str(payload.get("status") or "")
    if status == "020":
        raise DartRateLimitError("OpenDART daily request limit was reached.")
    if status in {"000", "013"}:
        return status, payload.get("list") or []
    raise RuntimeError(
        f"OpenDART {status}: {payload.get('message') or 'unknown error'}"
    )


def parse_stock_total(rows: list[dict[str, Any]]) -> dict[str, Any]:
    parsed = [
        {
            "share_class": str(row.get("se") or "").strip(),
            "issued_shares": parse_amount(row.get("istc_totqy")),
            "treasury_shares": parse_amount(row.get("tesstk_co")),
            "distributed_shares": parse_amount(row.get("distb_stock_co")),
            "settlement_date": str(row.get("stlm_dt") or "").strip() or None,
        }
        for row in rows
    ]
    total = next(
        (
            row
            for row in parsed
            if normalize_text(row["share_class"]) in {"합계", "총계"}
            and row["issued_shares"] is not None
        ),
        None,
    )
    if total is None:
        security_rows = [
            row
            for row in parsed
            if row["issued_shares"] is not None
            and normalize_text(row["share_class"]) not in {"비고", "합계", "총계"}
        ]
        total = {
            "share_class": "calculated_total",
            "issued_shares": sum(row["issued_shares"] for row in security_rows),
            "treasury_shares": (
                sum(row["treasury_shares"] for row in security_rows)
                if security_rows
                and all(row["treasury_shares"] is not None for row in security_rows)
                else None
            ),
            "distributed_shares": (
                sum(row["distributed_shares"] for row in security_rows)
                if security_rows
                and all(
                    row["distributed_shares"] is not None
                    for row in security_rows
                )
                else None
            ),
            "settlement_date": next(
                (
                    row["settlement_date"]
                    for row in security_rows
                    if row["settlement_date"]
                ),
                None,
            ),
        }
    return {
        "issued_shares": total.get("issued_shares") if total else None,
        "treasury_shares": total.get("treasury_shares") if total else None,
        "distributed_shares": (
            total.get("distributed_shares") if total else None
        ),
        "settlement_date": total.get("settlement_date") if total else None,
        "share_class_count": len(parsed),
    }


def parse_dividend_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    compact_rows = [
        {
            "item": str(row.get("se") or "").strip(),
            "share_class": str(row.get("stock_knd") or "").strip() or None,
            "current": parse_amount(row.get("thstrm")),
        }
        for row in rows
        if row.get("se")
    ]

    def values_for(*item_names: str) -> list[int]:
        normalized = {normalize_text(name) for name in item_names}
        return [
            row["current"]
            for row in compact_rows
            if normalize_text(row["item"]) in normalized
            and row["current"] is not None
        ]

    cash_total_values = values_for(
        "현금배당금총액",
        "현금배당금 총액",
        "현금배당금총액(백만원)",
    )
    payout_values = values_for("현금배당성향", "현금배당성향(%)")
    dps_values = values_for(
        "주당현금배당금",
        "주당 현금배당금",
        "주당현금배당금(원)",
    )
    return {
        # OpenDART commonly reports the total in KRW millions for this row.
        "cash_dividend_total_reported": (
            max(cash_total_values) if cash_total_values else None
        ),
        "cash_dividend_payout_ratio_pct": (
            max(payout_values) if payout_values else None
        ),
        "cash_dividend_per_share": max(dps_values) if dps_values else None,
        "has_cash_dividend": bool(
            any(value > 0 for value in cash_total_values + dps_values)
        ),
    }


def derive_row_metrics(row: dict[str, Any]) -> None:
    values = row.get("detail_accounts") or {}
    if not values:
        row.pop("detail_metrics", None)
        return

    equity = values.get("equity")
    if equity is None:
        equity = values.get("owners_equity")
    net_income = values.get("net_income")
    if net_income is None:
        net_income = values.get("owners_net_income")
    cash = values.get("cash")
    debt = sum_known(
        values.get("short_term_borrowings"),
        values.get("current_portion_long_term_debt"),
        values.get("current_bonds"),
        values.get("long_term_borrowings"),
        values.get("bonds"),
        values.get("lease_liabilities_current"),
        values.get("lease_liabilities_noncurrent"),
    )
    invested_capital = (
        equity + debt - cash
        if equity is not None and debt is not None and cash is not None
        else None
    )
    pretax_income = values.get("pretax_income")
    tax_expense = values.get("income_tax_expense")
    raw_tax_rate = safe_ratio(tax_expense, pretax_income)
    if raw_tax_rate is not None and 0 <= raw_tax_rate <= 0.5:
        tax_rate = raw_tax_rate
        tax_rate_source = "reported_effective"
    else:
        tax_rate = 0.24
        tax_rate_source = "fallback_24pct"
    operating_income = values.get("operating_income")
    nopat = (
        round(operating_income * (1 - tax_rate))
        if operating_income is not None
        else None
    )
    capex = sum_known(
        abs(values["capex_ppe"]) if values.get("capex_ppe") is not None else None,
        (
            abs(values["capex_intangibles"])
            if values.get("capex_intangibles") is not None
            else None
        ),
    )
    ocf = values.get("operating_cash_flow")
    free_cash_flow = ocf - capex if ocf is not None and capex is not None else None
    depreciation = values.get("depreciation_amortization")
    if depreciation is None:
        depreciation = sum_known(
            values.get("depreciation_expense"),
            values.get("amortization_expense"),
        )
    ebitda = (
        operating_income + abs(depreciation)
        if operating_income is not None and depreciation is not None
        else None
    )
    net_debt = debt - cash if debt is not None and cash is not None else None
    interest_denominator = values.get("interest_expense")
    interest_source = "reported_interest_expense"
    if interest_denominator is None and values.get("interest_paid") is not None:
        interest_denominator = values.get("interest_paid")
        interest_source = "cash_interest_paid_proxy"

    row["detail_metrics"] = {
        "effective_tax_rate_pct": round(tax_rate * 100, 4),
        "effective_tax_rate_source": tax_rate_source,
        "nopat": nopat,
        "interest_bearing_debt": debt,
        "net_debt": net_debt,
        "invested_capital": invested_capital,
        "roic_pct": pct(nopat, invested_capital),
        "gross_margin_pct": pct(values.get("gross_profit"), values.get("revenue")),
        "gross_profit_to_assets_pct": pct(
            values.get("gross_profit"), values.get("assets")
        ),
        "roa_pct": pct(net_income, values.get("assets")),
        "capex": capex,
        "free_cash_flow": free_cash_flow,
        "fcf_to_net_income": safe_ratio(free_cash_flow, net_income),
        "ebitda_proxy": ebitda,
        "net_debt_to_ebitda": safe_ratio(net_debt, ebitda),
        "current_ratio": safe_ratio(
            values.get("current_assets"), values.get("current_liabilities")
        ),
        "debt_to_equity_pct": pct(values.get("liabilities"), equity),
        "interest_coverage": safe_ratio(
            operating_income,
            abs(interest_denominator)
            if interest_denominator is not None
            else None,
        ),
        "interest_coverage_source": (
            interest_source if interest_denominator is not None else None
        ),
        "asset_turnover": safe_ratio(values.get("revenue"), values.get("assets")),
        "long_term_debt_to_assets": safe_ratio(
            sum_known(values.get("long_term_borrowings"), values.get("bonds")),
            values.get("assets"),
        ),
        "basic_eps": values.get("basic_eps"),
        "net_income": net_income,
        "operating_cash_flow": ocf,
        "dividends_paid": (
            abs(values["dividends_paid"])
            if values.get("dividends_paid") is not None
            else None
        ),
        "treasury_stock_purchases": (
            abs(values["treasury_stock_purchases"])
            if values.get("treasury_stock_purchases") is not None
            else None
        ),
    }


def _annual_change_pass(
    current: float | int | None,
    previous: float | int | None,
    direction: str,
) -> bool | None:
    if current is None or previous is None:
        return None
    return current > previous if direction == "up" else current < previous


def piotroski_partial(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    metrics = current.get("detail_metrics") or {}
    previous_metrics = (previous or {}).get("detail_metrics") or {}
    current_shares = (current.get("share_data") or {}).get("issued_shares")
    previous_shares = ((previous or {}).get("share_data") or {}).get(
        "issued_shares"
    )
    net_income = metrics.get("net_income")
    ocf = metrics.get("operating_cash_flow")
    roa = metrics.get("roa_pct")
    previous_roa = previous_metrics.get("roa_pct")
    criteria = {
        "roa_positive": None if roa is None else roa > 0,
        "ocf_positive": None if ocf is None else ocf > 0,
        "roa_improved": _annual_change_pass(roa, previous_roa, "up"),
        "ocf_exceeds_net_income": (
            None if ocf is None or net_income is None else ocf > net_income
        ),
        "long_term_leverage_decreased": _annual_change_pass(
            metrics.get("long_term_debt_to_assets"),
            previous_metrics.get("long_term_debt_to_assets"),
            "down",
        ),
        "current_ratio_improved": _annual_change_pass(
            metrics.get("current_ratio"),
            previous_metrics.get("current_ratio"),
            "up",
        ),
        "no_new_shares": (
            current_shares <= previous_shares
            if current_shares is not None and previous_shares is not None
            else None
        ),
        "gross_margin_improved": _annual_change_pass(
            metrics.get("gross_margin_pct"),
            previous_metrics.get("gross_margin_pct"),
            "up",
        ),
        "asset_turnover_improved": _annual_change_pass(
            metrics.get("asset_turnover"),
            previous_metrics.get("asset_turnover"),
            "up",
        ),
    }
    known = [value for value in criteria.values() if value is not None]
    return {
        "score_partial": sum(bool(value) for value in known),
        "known_criteria_count": len(known),
        "score_complete": len(known) == 9,
        "criteria": criteria,
        "missing": [name for name, value in criteria.items() if value is None],
    }


def standard_deviation(values: list[float]) -> float | None:
    return round(statistics.pstdev(values), 4) if len(values) >= 2 else None


def company_screening_features(
    rows: list[dict[str, Any]],
    market: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = sorted(rows, key=lambda item: int(item.get("fiscal_year") or 0))
    detail_rows = [
        row for row in rows if row.get("detail_status") == "complete"
    ][-10:]
    latest = detail_rows[-1] if detail_rows else None
    previous = detail_rows[-2] if len(detail_rows) >= 2 else None
    metrics = [row.get("detail_metrics") or {} for row in detail_rows]
    is_financial = bool(rows[-1].get("is_financial")) if rows else False

    roic_values = [
        value
        for value in (item.get("roic_pct") for item in metrics)
        if value is not None
    ]
    roe_values = [
        value
        for value in (
            (row.get("metrics") or {}).get("roe_pct") for row in detail_rows
        )
        if value is not None
    ]
    net_incomes = [
        item.get("net_income")
        for item in metrics
        if item.get("net_income") is not None
    ]
    margins = [
        item.get("gross_margin_pct")
        for item in metrics
        if item.get("gross_margin_pct") is not None
    ]
    fcfs = [
        item.get("free_cash_flow")
        for item in metrics
        if item.get("free_cash_flow") is not None
    ]
    normalized_fcf = None
    normalized_fcf_basis = None
    normalized_fcf_years = 0
    detail_years = [
        int(row.get("fiscal_year") or 0) for row in detail_rows
    ]
    ten_years_consecutive = (
        len(detail_years) == 10
        and detail_years == list(range(detail_years[0], detail_years[0] + 10))
    )
    if ten_years_consecutive and len(fcfs) == 10:
        normalized_fcf = statistics.mean(fcfs)
        normalized_fcf_basis = "10y_average"
        normalized_fcf_years = 10
    elif len(detail_rows) >= 3:
        recent_years = detail_years[-3:]
        recent_fcfs = [
            item.get("free_cash_flow") for item in metrics[-3:]
        ]
        if (
            recent_years
            == list(range(recent_years[0], recent_years[0] + 3))
            and all(value is not None for value in recent_fcfs)
        ):
            normalized_fcf = statistics.mean(recent_fcfs)
            normalized_fcf_basis = "3y_average_fallback"
            normalized_fcf_years = 3
    eps_values = [
        item.get("basic_eps")
        for item in metrics[-5:]
        if item.get("basic_eps") is not None
    ]

    incremental_roic = None
    incremental_roic_basis = {
        "delta_nopat": None,
        "delta_invested_capital": None,
        "minimum_delta_invested_capital": None,
        "denominator_valid": False,
    }
    if len(detail_rows) >= 6:
        old = detail_rows[-6].get("detail_metrics") or {}
        new = detail_rows[-1].get("detail_metrics") or {}
        delta_nopat = (
            new["nopat"] - old["nopat"]
            if new.get("nopat") is not None and old.get("nopat") is not None
            else None
        )
        delta_capital = (
            new["invested_capital"] - old["invested_capital"]
            if new.get("invested_capital") is not None
            and old.get("invested_capital") is not None
            else None
        )
        old_capital = old.get("invested_capital")
        minimum_delta_capital = (
            old_capital * 0.20
            if old_capital is not None and old_capital > 0
            else None
        )
        denominator_valid = bool(
            delta_capital is not None
            and minimum_delta_capital is not None
            and delta_capital > minimum_delta_capital
        )
        incremental_roic_basis = {
            "delta_nopat": delta_nopat,
            "delta_invested_capital": delta_capital,
            "minimum_delta_invested_capital": minimum_delta_capital,
            "denominator_valid": denominator_valid,
        }
        if denominator_valid:
            incremental_roic = pct(delta_nopat, delta_capital)

    payout_total = sum(
        (item.get("dividends_paid") or 0)
        + (item.get("treasury_stock_purchases") or 0)
        for item in metrics
    )
    positive_income_sum = sum(value for value in net_incomes if value > 0)
    payout_ratio = pct(payout_total, positive_income_sum)
    fcf_conversion = (
        safe_ratio(sum(fcfs), sum(net_incomes))
        if len(fcfs) == len(detail_rows)
        and len(net_incomes) == len(detail_rows)
        and sum(net_incomes) != 0
        else None
    )
    eps_cv = None
    if len(eps_values) >= 2:
        eps_mean = statistics.mean(eps_values)
        if eps_mean != 0:
            eps_cv = round(statistics.pstdev(eps_values) / abs(eps_mean), 6)

    persistence_values = roe_values if is_financial else roic_values
    persistence_hurdle = 10 if is_financial else 12
    persistence_count = sum(
        value >= persistence_hurdle for value in persistence_values
    )
    share_values = [
        (row.get("share_data") or {}).get("issued_shares")
        for row in detail_rows
    ]
    shares_not_increased = (
        share_values[-1] <= share_values[0]
        if len(share_values) == 10
        and share_values[0] is not None
        and share_values[-1] is not None
        else None
    )
    buffett_conditions = {
        "persistence_9_of_10": (
            persistence_count >= 9
            if len(persistence_values) == 10
            else None
        ),
        "positive_net_income_all_10y": (
            all(value > 0 for value in net_incomes)
            if len(net_incomes) == 10
            else None
        ),
        "gross_margin_sigma_le_5pp": (
            standard_deviation(margins) <= 5
            if len(margins) == 10
            else None
        ),
        "fcf_conversion_ge_0_8": (
            fcf_conversion >= 0.8 if fcf_conversion is not None else None
        ),
        "net_debt_to_ebitda_le_2_or_net_cash": (
            (
                (latest["detail_metrics"].get("net_debt") or 0) <= 0
                or latest["detail_metrics"].get("net_debt_to_ebitda") <= 2
            )
            if latest
            and latest.get("detail_metrics", {}).get("net_debt") is not None
            and (
                latest["detail_metrics"].get("net_debt") <= 0
                or latest["detail_metrics"].get("net_debt_to_ebitda") is not None
            )
            else None
        ),
        "shares_not_increased_10y": shares_not_increased,
        "incremental_roic_ge_15_or_payout_ge_50": (
            (incremental_roic is not None and incremental_roic >= 15)
            or (payout_ratio is not None and payout_ratio >= 50)
            if incremental_roic is not None or payout_ratio is not None
            else None
        ),
    }
    known_buffett = [
        value for value in buffett_conditions.values() if value is not None
    ]

    latest_metrics = (latest or {}).get("detail_metrics") or {}
    latest_accounts = (latest or {}).get("detail_accounts") or {}
    latest_primary_metrics = (latest or {}).get("metrics") or {}
    f_score = piotroski_partial(latest, previous) if latest else None
    quality_conditions = {
        "gpa_market_top_30pct": None,
        "piotroski_f_score_ge_7": (
            f_score["score_partial"] >= 7
            if f_score and f_score["score_complete"]
            else None
        ),
        "eps_cv_market_lowest": None,
        "debt_to_equity_le_100pct": (
            latest_metrics["debt_to_equity_pct"] <= 100
            if latest_metrics.get("debt_to_equity_pct") is not None
            else None
        ),
        "dividend_or_buyback_recent_3y": (
            any(
                (item.get("dividends_paid") or 0) > 0
                or (item.get("treasury_stock_purchases") or 0) > 0
                or bool(
                    (
                        detail_rows[index].get("dividend_data") or {}
                    ).get("has_cash_dividend")
                )
                for index, item in enumerate(
                    metrics[-3:],
                    start=max(0, len(detail_rows) - 3),
                )
            )
            if len(metrics) >= 3
            else None
        ),
    }
    market = market or {}
    latest_fcf = latest_metrics.get("free_cash_flow")
    market_cap = market.get("market_cap_krw")
    fcf_yield = pct(normalized_fcf, market_cap)
    latest_cash = latest_accounts.get("cash")
    cash_to_market_cap = pct(latest_cash, market_cap)
    cash_gate = (
        True
        if is_financial
        else cash_to_market_cap <= 50
        if cash_to_market_cap is not None
        else None
    )
    return {
        "ticker": rows[-1].get("ticker") if rows else None,
        "company": rows[-1].get("company") if rows else None,
        "is_financial": is_financial,
        "detail_year_count": len(detail_rows),
        "detail_years": [row.get("fiscal_year") for row in detail_rows],
        "buffett": {
            "persistence_metric": "ROE" if is_financial else "ROIC",
            "persistence_hurdle_pct": persistence_hurdle,
            "persistence_pass_years": persistence_count,
            "gross_margin_sigma_pct_points": standard_deviation(margins),
            "fcf_conversion_10y": fcf_conversion,
            "latest_net_debt_to_ebitda": latest_metrics.get(
                "net_debt_to_ebitda"
            ),
            "latest_roic_pct": latest_metrics.get("roic_pct"),
            "latest_roe_pct": latest_primary_metrics.get("roe_pct"),
            "incremental_roic_5y_pct": incremental_roic,
            "incremental_roic_5y_basis": incremental_roic_basis,
            "payout_ratio_observed_years_pct": payout_ratio,
            "conditions": buffett_conditions,
            "pass": (
                all(known_buffett)
                if len(known_buffett) == len(buffett_conditions)
                else None
            ),
            "missing_conditions": [
                name
                for name, value in buffett_conditions.items()
                if value is None
            ],
            "valuation": {
                "latest_annual_fcf": latest_fcf,
                "normalized_annual_fcf": normalized_fcf,
                "normalized_fcf_basis": normalized_fcf_basis,
                "normalized_fcf_years": normalized_fcf_years,
                "current_market_cap_krw": market_cap,
                "fcf_yield_pct": fcf_yield,
                "fcf_yield_ge_5pct": (
                    fcf_yield >= 5 if fcf_yield is not None else None
                ),
                "latest_cash": latest_cash,
                "cash_to_market_cap_pct": cash_to_market_cap,
                "cash_to_market_cap_le_50pct_or_financial": cash_gate,
                "cash_ratio_financial_exempt": is_financial,
                "note": (
                    "FCF yield uses a 10-year average when complete, otherwise "
                    "a complete recent 3-year average. Non-financial companies "
                    "with cash above 50% of market cap fail the excess-cash gate."
                ),
            },
        },
        "quality": {
            "latest_gross_profit_to_assets_pct": latest_metrics.get(
                "gross_profit_to_assets_pct"
            ),
            "eps_cv_5y": eps_cv,
            "piotroski": f_score,
            "conditions": quality_conditions,
            "pass": None,
            "missing_conditions": [
                name
                for name, value in quality_conditions.items()
                if value is None
            ],
        },
    }


def apply_cross_sectional_quality_ranks(
    features: dict[str, dict[str, Any]],
) -> None:
    gpa = [
        (ticker, row["quality"]["latest_gross_profit_to_assets_pct"])
        for ticker, row in features.items()
        if row["quality"]["latest_gross_profit_to_assets_pct"] is not None
    ]
    eps_cv = [
        (ticker, row["quality"]["eps_cv_5y"])
        for ticker, row in features.items()
        if row["quality"]["eps_cv_5y"] is not None
    ]
    gpa.sort(key=lambda item: item[1], reverse=True)
    eps_cv.sort(key=lambda item: item[1])
    gpa_pass = {
        ticker for ticker, _ in gpa[: math.ceil(len(gpa) * 0.30)]
    }
    # The user's phrase "시장 하위 5" is treated as the lowest 50% until clarified.
    eps_pass = {
        ticker for ticker, _ in eps_cv[: math.ceil(len(eps_cv) * 0.50)]
    }
    gpa_rank = {ticker: index + 1 for index, (ticker, _) in enumerate(gpa)}
    eps_rank = {ticker: index + 1 for index, (ticker, _) in enumerate(eps_cv)}

    for ticker, row in features.items():
        quality = row["quality"]
        conditions = quality["conditions"]
        if ticker in gpa_rank:
            conditions["gpa_market_top_30pct"] = ticker in gpa_pass
            quality["gpa_market_rank"] = gpa_rank[ticker]
            quality["gpa_market_count"] = len(gpa)
        if ticker in eps_rank:
            conditions["eps_cv_market_lowest"] = ticker in eps_pass
            quality["eps_cv_market_rank"] = eps_rank[ticker]
            quality["eps_cv_market_count"] = len(eps_cv)
        quality["missing_conditions"] = [
            name for name, value in conditions.items() if value is None
        ]
        known = [value for value in conditions.values() if value is not None]
        quality["pass"] = (
            all(known) if len(known) == len(conditions) else None
        )


def rebuild_screening_features(
    panel: dict[str, Any],
    market_lookup: dict[str, dict[str, Any]] | None = None,
    market_data_as_of: str | None = None,
) -> None:
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in panel.get("observations") or []:
        by_ticker[str(row.get("ticker") or "")].append(row)
    features = {
        ticker: company_screening_features(
            rows,
            (market_lookup or {}).get(ticker),
        )
        for ticker, rows in by_ticker.items()
    }
    apply_cross_sectional_quality_ranks(features)
    panel["screening_features"] = features
    panel["screening_features_market_data_as_of"] = market_data_as_of


def update_detail_summary(
    panel: dict[str, Any],
    *,
    request_count: int,
    errors: list[dict[str, Any]],
    eligible_rows: list[dict[str, Any]],
    budget_reached: bool,
) -> None:
    stages = ("detail_status", "share_status", "dividend_status")
    stage_counts = {
        stage.replace("_status", ""): dict(
            sorted(
                Counter(
                    str(row.get(stage) or "pending") for row in eligible_rows
                ).items()
            )
        )
        for stage in stages
    }
    completed = sum(
        all(row.get(stage) in TERMINAL_STATUSES for stage in stages)
        for row in eligible_rows
    )
    panel["detail_enrichment"] = {
        "schema_version": DETAIL_SCHEMA_VERSION,
        "source": (
            "OpenDART bulk/API full financial statements, stock totals and "
            "dividend matters"
        ),
        "source_urls": [
            DART_FULL_ACCOUNT_URL,
            DART_STOCK_TOTAL_URL,
            DART_DIVIDEND_URL,
        ],
        "updated_at_utc": utc_now_iso(),
        "complete": completed >= len(eligible_rows),
        "budget_reached": budget_reached,
        "eligible_observation_count": len(eligible_rows),
        "completed_observation_count": completed,
        "pending_observation_count": len(eligible_rows) - completed,
        "stage_status_counts": stage_counts,
        "api_request_count_this_run": request_count,
        "errors_this_run": errors[-100:],
        "methodology": {
            "statement_preference": "CFS first, OFS fallback",
            "stored_scope": (
                "Every bulk TXT row and every API response row is retained in "
                "source-specific gzip JSON shards. Standardized accounts and screen "
                "metrics are a separate calculation layer with raw references."
            ),
            "source_precedence": (
                "Complete CFS bulk statement, then complete OFS bulk statement; "
                "OpenDART API is used only for a missing/partial bulk company-year. "
                "CFS and OFS fields are never mixed within one calculation basis."
            ),
            "roic": (
                "NOPAT / (total equity + interest-bearing debt - cash); "
                "reported effective tax rate is capped to 0-50%, otherwise 24%."
            ),
            "capex": "absolute PPE purchases + absolute intangible purchases",
            "free_cash_flow": "operating cash flow - capex",
            "normalized_fcf_yield": (
                "10-year average FCF when all ten observations exist; otherwise "
                "a complete recent 3-year average"
            ),
            "incremental_roic_guard": (
                "5-year incremental ROIC is calculated only when the increase in "
                "invested capital exceeds 20% of starting invested capital"
            ),
            "excess_cash_gate": (
                "Non-financial companies fail the Buffett interest gate when cash "
                "exceeds 50% of current market capitalization; financials are exempt"
            ),
            "shares": (
                "OpenDART stockTotqySttus `istc_totqy`; total row preferred, "
                "otherwise security-class rows are summed."
            ),
            "limitations": [
                "Cash-flow dividends/buybacks are accounting proxies, not a full "
                "corporate-action history.",
                "PER/PBR bands, quarterly turnaround signals, ownership and note-level "
                "asset appraisal require separate collectors.",
            ],
        },
    }


def main() -> None:
    load_env_file(ROOT_DIR / ".env")
    args = parse_args()
    panel_path = Path(args.panel)
    panel = load_financial_panel(panel_path)
    market_lookup, market_data_as_of = load_market_lookup(Path(args.market_sum))
    observations = panel.get("observations")
    if not isinstance(observations, list) or not observations:
        raise SystemExit(
            "The core DART panel is missing or empty. Run "
            "crawler_dart_financial_panel.py first."
        )
    if args.rebuild_screens_only:
        rebuild_screening_features(
            panel,
            market_lookup=market_lookup,
            market_data_as_of=market_data_as_of,
        )
        save_financial_panel(panel_path, panel, split_by_year=True)
        print(
            f"[DART DETAILS] rebuilt screening features for "
            f"{len(panel['screening_features']):,} companies",
            flush=True,
        )
        return

    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DART_API_KEY is not set.")
    if args.max_requests < 1:
        raise SystemExit("--max-requests must be at least 1.")

    requested_codes = {
        value.strip().zfill(6)
        for value in args.codes.split(",")
        if value.strip()
    }
    panel_period = panel.get("period") or {}
    start_year = args.start_year or int(panel_period.get("start_year") or 0)
    end_year = min(
        args.end_year,
        int(panel_period.get("end_year") or args.end_year),
    )
    eligible = [
        row
        for row in observations
        if start_year <= int(row.get("fiscal_year") or 0) <= end_year
        and (not requested_codes or row.get("ticker") in requested_codes)
    ]
    if args.limit > 0:
        allowed = sorted({row.get("ticker") for row in eligible})[: args.limit]
        eligible = [row for row in eligible if row.get("ticker") in allowed]

    years_by_ticker: dict[str, list[int]] = defaultdict(list)
    for row in eligible:
        ticker = str(row.get("ticker") or "")
        year = int(row.get("fiscal_year") or 0)
        if year:
            years_by_ticker[ticker].append(year)
    share_required: set[tuple[str, int]] = set()
    dividend_required: set[tuple[str, int]] = set()
    for ticker, ticker_years in years_by_ticker.items():
        ordered = sorted(set(ticker_years))
        if args.supplement_profile == "all":
            share_years = ordered
            dividend_years = ordered
        elif args.supplement_profile == "screens":
            share_years = sorted(set(ordered[:1] + ordered[-2:]))
            dividend_years = ordered[-3:]
        else:
            share_years = []
            dividend_years = []
        share_required.update((ticker, year) for year in share_years)
        dividend_required.update((ticker, year) for year in dividend_years)

    if args.reset_details:
        for row in eligible:
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
                "detail_validation",
                "detail_basis_selection",
                "share_status",
                "share_data",
                "share_updated_at_utc",
                "dividend_status",
                "dividend_data",
                "dividend_updated_at_utc",
            ):
                row.pop(key, None)
    elif args.refresh_latest:
        for row in eligible:
            if int(row.get("fiscal_year") or 0) == end_year:
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
                    "detail_validation",
                    "detail_basis_selection",
                    "share_status",
                    "share_data",
                    "share_updated_at_utc",
                    "dividend_status",
                    "dividend_data",
                    "dividend_updated_at_utc",
                ):
                    row.pop(key, None)

    for row in eligible:
        key = (str(row.get("ticker") or ""), int(row.get("fiscal_year") or 0))
        if key not in share_required and row.get("share_status") not in {
            "complete",
            "no_data",
        }:
            row["share_status"] = "not_required"
            row.pop("share_data", None)
        if key not in dividend_required and row.get("dividend_status") not in {
            "complete",
            "no_data",
        }:
            row["dividend_status"] = "not_required"
            row.pop("dividend_data", None)

    pending = []
    for row in eligible:
        key = (str(row.get("ticker") or ""), int(row.get("fiscal_year") or 0))
        needs_detail = (
            not args.supplements_only
            and row.get("detail_status") not in TERMINAL_STATUSES
        )
        needs_share = (
            key in share_required
            and (
                row.get("share_status") not in TERMINAL_STATUSES
                or not row.get("share_raw_ref")
            )
        )
        needs_dividend = (
            key in dividend_required
            and (
                row.get("dividend_status") not in TERMINAL_STATUSES
                or not row.get("dividend_raw_ref")
            )
        )
        if needs_detail or needs_share or needs_dividend:
            pending.append(row)
    pending.sort(key=lambda row: (row.get("ticker"), row.get("fiscal_year")))
    print(
        f"[DART DETAILS] eligible {len(eligible):,} | pending {len(pending):,} | "
        f"years {start_year}-{end_year} | request budget {args.max_requests:,}",
        flush=True,
    )

    request_count = 0
    processed = 0
    errors: list[dict[str, Any]] = []
    consecutive_errors = 0
    budget_reached = False
    started_at = time.monotonic()
    session = create_session()
    raw_accumulator = ApiRawAccumulator(Path(args.raw_root))

    def checkpoint() -> None:
        raw_accumulator.flush()
        rebuild_screening_features(
            panel,
            market_lookup=market_lookup,
            market_data_as_of=market_data_as_of,
        )
        update_detail_summary(
            panel,
            request_count=request_count,
            errors=errors,
            eligible_rows=eligible,
            budget_reached=budget_reached,
        )
        save_financial_panel(panel_path, panel, split_by_year=True)

    def reserve_request() -> None:
        nonlocal request_count
        if (
            args.max_runtime_minutes > 0
            and time.monotonic() - started_at
            >= args.max_runtime_minutes * 60
        ):
            raise RequestBudgetReached(
                "runtime safety limit reached; saving a resumable checkpoint."
            )
        if request_count >= args.max_requests:
            raise RequestBudgetReached(
                "request budget reached; saving a resumable checkpoint."
            )
        request_count += 1

    try:
        for index, row in enumerate(pending, start=1):
            try:
                corp_code = str(row.get("corp_code") or "")
                fiscal_year = int(row.get("fiscal_year") or 0)
                row_key = (str(row.get("ticker") or ""), fiscal_year)

                if (
                    not args.supplements_only
                    and row.get("detail_status") not in TERMINAL_STATUSES
                ):
                    selected_basis = ""
                    selected_rows: list[dict[str, Any]] = []
                    for basis in ("CFS", "OFS"):
                        reserve_request()
                        status, payload_rows, _ = fetch_full_statement(
                            session,
                            api_key,
                            corp_code,
                            fiscal_year,
                            basis,
                        )
                        raw_reference = raw_accumulator.add(
                            year=fiscal_year,
                            dataset="financial_statement",
                            ticker=row_key[0],
                            corp_code=corp_code,
                            basis=basis,
                            endpoint=DART_FULL_ACCOUNT_URL,
                            request_parameters={
                                "corp_code": corp_code,
                                "bsns_year": str(fiscal_year),
                                "reprt_code": ANNUAL_REPORT_CODE,
                                "fs_div": basis,
                            },
                            response_status=status,
                            rows=payload_rows,
                        )
                        row.setdefault("detail_api_raw_refs", {})[basis] = (
                            raw_reference
                        )
                        if status == "000" and payload_rows:
                            selected_basis = basis
                            selected_rows = payload_rows
                            break
                        if args.delay > 0:
                            time.sleep(args.delay)

                    if selected_rows:
                        previous_values = dict(row.get("detail_accounts") or {})
                        previous_source = str(row.get("detail_source") or "")
                        values, matches = standardize_accounts(selected_rows)
                        row["detail_status"] = "complete"
                        row["detail_basis"] = selected_basis
                        row["detail_source"] = (
                            "api_gap_fallback"
                            if str(row.get("detail_source") or "").startswith(
                                "bulk_zip"
                            )
                            else "api"
                        )
                        row["detail_accounts"] = values
                        if previous_values:
                            overlap = sorted(set(previous_values) & set(values))
                            mismatches = {
                                key: {
                                    "previous_value": previous_values.get(key),
                                    "api_value": values.get(key),
                                }
                                for key in overlap
                                if previous_values.get(key) != values.get(key)
                            }
                            row["detail_validation"] = {
                                "previous_source": previous_source,
                                "overlap_count": len(overlap),
                                "mismatch_count": len(mismatches),
                                "mismatches": mismatches,
                                "selection": "api_value_used_for_bulk_gap",
                            }
                        row["detail_basis_selection"] = {
                            "selected": selected_basis,
                            "rule": "API CFS first, OFS only when CFS has no rows",
                            "cross_basis_field_mixing": False,
                        }
                        row.pop("detail_account_matches", None)
                        row["detail_match_summary"] = dict(
                            sorted(
                                Counter(
                                    match.get("match") or "unknown"
                                    for match in matches.values()
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
                        row["detail_updated_at_utc"] = utc_now_iso()
                        derive_row_metrics(row)
                    else:
                        row["detail_status"] = "no_data"
                        row["detail_basis"] = None
                        row["detail_source"] = "api_no_data"
                        row["detail_updated_at_utc"] = utc_now_iso()

                if (
                    row_key in share_required
                    and (
                        row.get("share_status") not in TERMINAL_STATUSES
                        or not row.get("share_raw_ref")
                    )
                ):
                    reserve_request()
                    share_status, share_rows = fetch_annual_report_api(
                        session,
                        api_key,
                        DART_STOCK_TOTAL_URL,
                        corp_code,
                        fiscal_year,
                    )
                    row["share_raw_ref"] = raw_accumulator.add(
                        year=fiscal_year,
                        dataset="stock_total",
                        ticker=row_key[0],
                        corp_code=corp_code,
                        endpoint=DART_STOCK_TOTAL_URL,
                        request_parameters={
                            "corp_code": corp_code,
                            "bsns_year": str(fiscal_year),
                            "reprt_code": ANNUAL_REPORT_CODE,
                        },
                        response_status=share_status,
                        rows=share_rows,
                    )
                    if share_status == "000" and share_rows:
                        row["share_status"] = "complete"
                        row["share_data"] = parse_stock_total(share_rows)
                    else:
                        row["share_status"] = "no_data"
                        row.pop("share_data", None)
                    row["share_updated_at_utc"] = utc_now_iso()

                if (
                    row_key in dividend_required
                    and (
                        row.get("dividend_status") not in TERMINAL_STATUSES
                        or not row.get("dividend_raw_ref")
                    )
                ):
                    reserve_request()
                    dividend_status, dividend_rows = fetch_annual_report_api(
                        session,
                        api_key,
                        DART_DIVIDEND_URL,
                        corp_code,
                        fiscal_year,
                    )
                    row["dividend_raw_ref"] = raw_accumulator.add(
                        year=fiscal_year,
                        dataset="dividend_matter",
                        ticker=row_key[0],
                        corp_code=corp_code,
                        endpoint=DART_DIVIDEND_URL,
                        request_parameters={
                            "corp_code": corp_code,
                            "bsns_year": str(fiscal_year),
                            "reprt_code": ANNUAL_REPORT_CODE,
                        },
                        response_status=dividend_status,
                        rows=dividend_rows,
                    )
                    if dividend_status == "000" and dividend_rows:
                        row["dividend_status"] = "complete"
                        row["dividend_data"] = parse_dividend_report(
                            dividend_rows
                        )
                    else:
                        row["dividend_status"] = "no_data"
                        row.pop("dividend_data", None)
                    row["dividend_updated_at_utc"] = utc_now_iso()

                processed += 1
                consecutive_errors = 0
            except (RequestBudgetReached, DartRateLimitError):
                raise
            except Exception as exc:
                consecutive_errors += 1
                errors.append(
                    {
                        "ticker": row.get("ticker"),
                        "fiscal_year": row.get("fiscal_year"),
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
                print(
                    f"[DART DETAILS] FAIL {index:,}/{len(pending):,} "
                    f"{row.get('ticker')} {row.get('fiscal_year')} -> "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                if consecutive_errors >= args.max_consecutive_errors:
                    checkpoint()
                    raise RuntimeError(
                        f"Aborting after {consecutive_errors} consecutive errors."
                    ) from exc
                if args.delay > 0:
                    time.sleep(args.delay)

            if (
                processed == 1
                or processed % max(1, args.checkpoint_every) == 0
                or request_count % max(1, args.checkpoint_every) == 0
                or index == len(pending)
            ):
                elapsed = int(time.monotonic() - started_at)
                print(
                    f"[DART DETAILS] {index:,}/{len(pending):,} pending rows | "
                    f"requests {request_count:,}/{args.max_requests:,} | "
                    f"elapsed {elapsed}s | "
                    f"{row.get('ticker')} {row.get('fiscal_year')} "
                    f"financial={row.get('detail_status') or 'pending'} "
                    f"shares={row.get('share_status') or 'pending'} "
                    f"dividend={row.get('dividend_status') or 'pending'}",
                    flush=True,
                )
                checkpoint()
            if args.delay > 0:
                time.sleep(args.delay)
    except RequestBudgetReached as exc:
        budget_reached = True
        print(
            f"[DART DETAILS] {exc}",
            flush=True,
        )
    except DartRateLimitError as exc:
        budget_reached = True
        errors.append({"type": "rate_limit", "message": str(exc)})
        print(f"[DART DETAILS] {exc}", flush=True)
    finally:
        checkpoint()

    detail = panel.get("detail_enrichment") or {}
    print(
        f"[DART DETAILS] saved {panel_path} | completed rows "
        f"{detail.get('completed_observation_count', 0):,} | pending rows "
        f"{detail.get('pending_observation_count', 0):,} | "
        f"all done={detail.get('complete')}",
        flush=True,
    )
    if budget_reached:
        print(
            "[DART DETAILS] Run the same Action again with mode=resume to continue.",
            flush=True,
        )


if __name__ == "__main__":
    main()
