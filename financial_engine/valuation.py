"""Period-matched ROE/ROA and conservative valuation eligibility checks."""
from __future__ import annotations

from datetime import date, timedelta
import math


THIN_EQUITY_RATIO = 0.05
DISCONTINUED_PROFIT_SHARE = 0.10


def number(value):
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None


def capital_reasons(accounts: dict) -> list[str]:
    equity = number(accounts.get("owners_equity"))
    total = number(accounts.get("equity"))
    assets = number(accounts.get("assets"))
    capital = number(accounts.get("capital_stock"))
    reasons = []
    if equity is None or total is None or assets is None:
        return ["missing_capital"]
    if equity <= 0 or total <= 0:
        reasons.append("nonpositive_equity")
    elif capital is not None and (equity < capital or total < capital):
        reasons.append("capital_impairment")
    if assets <= 0:
        reasons.append("invalid_assets")
    elif equity > 0 and equity / assets < THIN_EQUITY_RATIO:
        reasons.append("thin_equity")
    return reasons


def evaluate_returns(start: dict, end: dict, income: dict, *, period_end: str,
                     basis: str, method: str, capital_history=()) -> dict:
    end_date = date.fromisoformat(period_end)
    balance_start = end_date.replace(year=end_date.year - 1)
    result = {"method": method, "basis": basis, "period_end": period_end,
              "period_start": (balance_start + timedelta(days=1)).isoformat(),
              "balance_start": balance_start.isoformat(), "balance_end": period_end,
              "roe_pct": None, "roa_pct": None, "quality_reasons": []}
    reasons = result["quality_reasons"]
    for accounts in (start, end):
        reasons.extend(capital_reasons(accounts))
    if any(set(capital_reasons(a)) & {"nonpositive_equity", "capital_impairment", "thin_equity"}
           for a in capital_history):
        reasons.append("recent_capital_impairment")
    owners_income = number(income.get("owners_net_income"))
    net_income = number(income.get("net_income"))
    continuing = number(income.get("continuing_net_income"))
    discontinued = number(income.get("discontinued_net_income"))
    if owners_income is None or net_income is None:
        reasons.append("missing_income")
    if continuing is None or discontinued is None:
        reasons.append("unverified_discontinued_operations")
    elif discontinued > 0 and (continuing <= 0 or net_income <= 0
                               or discontinued >= abs(net_income) * DISCONTINUED_PROFIT_SHARE):
        reasons.append("material_discontinued_profit")
    if continuing is not None and continuing <= 0:
        reasons.append("continuing_loss")
    if owners_income is not None and owners_income <= 0:
        reasons.append("owners_loss")
    if not capital_reasons(start) and not capital_reasons(end):
        mean_equity = (start["owners_equity"] + end["owners_equity"]) / 2
        mean_assets = (start["assets"] + end["assets"]) / 2
        if owners_income is not None:
            result["roe_pct"] = round(owners_income / mean_equity * 100, 4)
        if net_income is not None:
            result["roa_pct"] = round(net_income / mean_assets * 100, 4)
    result.update({"owners_net_income": owners_income, "net_income": net_income,
                   "continuing_net_income": continuing, "discontinued_net_income": discontinued,
                   "owners_equity": end.get("owners_equity")})
    result["quality_reasons"] = list(dict.fromkeys(reasons))
    result["eligible"] = not result["quality_reasons"]
    return result


def trailing_income(annual: dict, current: dict, previous: dict) -> dict:
    """Use comparable YTD flows; never annualize an isolated quarter."""
    keys = ("net_income", "owners_net_income", "continuing_net_income", "discontinued_net_income")
    return {key: annual[key] + current[key] - previous[key]
            for key in keys if all(number(source.get(key)) is not None
                                   for source in (annual, current, previous))}
