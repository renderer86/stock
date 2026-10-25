"""Pure, basis-consistent trailing cash-flow calculations."""
from __future__ import annotations

from typing import Any


def ttm_cashflow(annual: dict[str, Any], interim: dict[str, Any]) -> dict[str, Any] | None:
    if not interim or annual.get("is_financial") or (annual.get("detail_validation") or {}).get("calculation_blocked"):
        return None
    if interim.get("status") != "ok" or interim.get("fiscal_year") != int(annual.get("fiscal_year") or 0) + 1:
        return None
    if interim.get("basis") != annual.get("detail_basis") or interim.get("corp_code") != annual.get("corp_code"):
        return None
    accounts = annual.get("detail_accounts") or {}
    current, previous = interim.get("current") or {}, interim.get("previous") or {}
    keys = ("operating_cash_flow", "capex_ppe", "capex_intangibles", "lease_principal_paid")
    if any(source.get(key) is None for source in (accounts, current, previous) for key in keys):
        return None
    totals = {key: accounts[key] + current[key] - previous[key] for key in keys}
    if any(totals[key] < 0 for key in keys[1:]):
        return None
    before_leases = totals["operating_cash_flow"] - totals["capex_ppe"] - totals["capex_intangibles"]
    after_leases = before_leases - totals["lease_principal_paid"]
    return {"valuation_fcf": after_leases, "valuation_fcf_basis": "ttm_after_leases",
            "ttm_fcf_before_leases": before_leases, "ttm_fcf_after_leases": after_leases,
            "ttm_lease_principal_paid": totals["lease_principal_paid"],
            "fcf_period_end": interim.get("period_end"), "interim_source_url": interim.get("dart_url"),
            "interim_operating_income_yoy_pct": interim.get("operating_income_yoy_pct")}
