from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .config import ENGINE_VERSION, METHODOLOGY_VERSION


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tri_state(conditions: dict[str, Any]) -> str:
    values = list(conditions.values())
    if any(value is False for value in values):
        return "fail"
    if values and all(value is True for value in values):
        return "pass"
    return "pending"


def _condition_coverage(conditions: dict[str, Any]) -> dict[str, Any]:
    known = sum(value is not None for value in conditions.values())
    return {
        "known": known,
        "required": len(conditions),
        "ratio": round(known / len(conditions), 4) if conditions else 0,
        "missing": [
            name for name, value in conditions.items() if value is None
        ],
    }


class InvestmentScreenBuilder:
    """Build presentation-neutral Buffett and quality screen results."""

    def __init__(self, quality_basket_size: int = 25) -> None:
        self.quality_basket_size = max(1, quality_basket_size)

    def build(
        self,
        panel: dict[str, Any],
        n_estimates: dict[str, Any],
        market_sum: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        panel_features = panel.get("screening_features") or {}
        n_by_ticker = n_estimates.get("estimates") or {}
        market_by_ticker = {
            str(row.get("code") or "").zfill(6): row
            for row in (market_sum or {}).get("stocks") or []
            if row.get("code")
        }
        company_metadata = self._company_metadata(panel)
        tickers = sorted(
            set(company_metadata) | set(panel_features) | set(n_by_ticker)
        )
        results: dict[str, dict[str, Any]] = {}

        for ticker in tickers:
            feature = panel_features.get(ticker) or {}
            buffett = feature.get("buffett") or {}
            quality = feature.get("quality") or {}
            buffett_conditions = dict(buffett.get("conditions") or {})
            quality_conditions = dict(quality.get("conditions") or {})
            valuation = dict(buffett.get("valuation") or {})
            market = market_by_ticker.get(ticker) or {}
            n_row = n_by_ticker.get(ticker)

            business_status = (
                _tri_state(buffett_conditions)
                if buffett_conditions
                else "pending"
            )
            fcf_yield_pass = valuation.get("fcf_yield_ge_5pct")
            valuation_status = (
                "pass"
                if fcf_yield_pass is True
                else "fail"
                if fcf_yield_pass is False
                else "pending"
            )
            quality_status = (
                _tri_state(quality_conditions)
                if quality_conditions
                else "pending"
            )
            metadata = company_metadata.get(ticker) or {}
            results[ticker] = {
                "ticker": ticker,
                "company": feature.get("company")
                or metadata.get("company")
                or market.get("name"),
                "market": metadata.get("market") or market.get("market"),
                "sector": metadata.get("sector"),
                "industry": metadata.get("industry"),
                "as_of_fiscal_year": metadata.get("latest_year"),
                "n": (
                    {
                        "status": n_row.get("status"),
                        "base_years": (
                            n_row.get("estimate") or {}
                        ).get("base_years"),
                        "conservative_years": (
                            n_row.get("estimate") or {}
                        ).get("conservative_years"),
                        "optimistic_years": (
                            n_row.get("estimate") or {}
                        ).get("optimistic_years"),
                        "confidence": n_row.get("confidence"),
                        "warnings": n_row.get("warnings"),
                    }
                    if n_row
                    else {
                        "status": "missing",
                        "base_years": None,
                        "confidence": None,
                        "warnings": ["n_estimate_missing"],
                    }
                ),
                "buffett": {
                    "business_quality_status": business_status,
                    "valuation_status": valuation_status,
                    "candidate": (
                        business_status == "pass"
                        and valuation_status == "pass"
                    ),
                    "conditions": buffett_conditions,
                    "coverage": _condition_coverage(buffett_conditions),
                    "persistence_metric": buffett.get(
                        "persistence_metric"
                    ),
                    "persistence_pass_years": buffett.get(
                        "persistence_pass_years"
                    ),
                    "gross_margin_sigma_pct_points": buffett.get(
                        "gross_margin_sigma_pct_points"
                    ),
                    "fcf_conversion_10y": buffett.get(
                        "fcf_conversion_10y"
                    ),
                    "latest_net_debt_to_ebitda": buffett.get(
                        "latest_net_debt_to_ebitda"
                    ),
                    "incremental_roic_5y_pct": buffett.get(
                        "incremental_roic_5y_pct"
                    ),
                    "payout_ratio_pct": buffett.get(
                        "payout_ratio_observed_years_pct"
                    ),
                    "valuation": valuation,
                },
                "quality": {
                    "status": quality_status,
                    "eligible_for_basket": quality_status == "pass",
                    "selected_for_basket": False,
                    "conditions": quality_conditions,
                    "coverage": _condition_coverage(quality_conditions),
                    "gpa_pct": quality.get(
                        "latest_gross_profit_to_assets_pct"
                    ),
                    "gpa_market_rank": quality.get("gpa_market_rank"),
                    "eps_cv_5y": quality.get("eps_cv_5y"),
                    "piotroski": quality.get("piotroski"),
                },
                "market_snapshot": {
                    "current_price": market.get("current_price"),
                    "market_cap_krw_100m": market.get(
                        "market_cap_krw_100m"
                    ),
                    "pbr": market.get("pbr"),
                    "per": market.get("per"),
                },
            }

        quality_candidates = sorted(
            (
                row
                for row in results.values()
                if row["quality"]["eligible_for_basket"]
                and row["quality"]["gpa_pct"] is not None
            ),
            key=lambda row: (
                -float(row["quality"]["gpa_pct"]),
                row["ticker"],
            ),
        )
        selected_quality = quality_candidates[: self.quality_basket_size]
        for rank, row in enumerate(selected_quality, start=1):
            row["quality"]["selected_for_basket"] = True
            row["quality"]["basket_rank"] = rank

        buffett_candidates = sorted(
            (row for row in results.values() if row["buffett"]["candidate"]),
            key=lambda row: (
                -float(
                    (
                        row["buffett"].get("valuation") or {}
                    ).get("fcf_yield_pct")
                    or -999
                ),
                -float((row["n"] or {}).get("base_years") or 0),
                row["ticker"],
            ),
        )
        buffett_status_counts = Counter(
            row["buffett"]["business_quality_status"]
            for row in results.values()
        )
        quality_status_counts = Counter(
            row["quality"]["status"] for row in results.values()
        )
        return {
            "schema_version": 1,
            "engine_version": ENGINE_VERSION,
            "methodology_version": METHODOLOGY_VERSION,
            "generated_at_utc": _utc_now_iso(),
            "source": {
                "panel_crawled_at_utc": panel.get("crawled_at_utc"),
                "n_generated_at_utc": n_estimates.get("generated_at_utc"),
                "market_crawled_at_utc": (market_sum or {}).get(
                    "crawled_at_utc"
                ),
            },
            "complete": bool(results) and all(
                row["buffett"]["business_quality_status"] != "pending"
                and row["quality"]["status"] != "pending"
                for row in results.values()
            ),
            "methodology": {
                "missing_data": (
                    "Unknown conditions remain pending; they are never counted "
                    "as pass."
                ),
                "buffett": (
                    "Business-quality pass and FCF-yield valuation pass are "
                    "reported separately and must both pass for candidate=true."
                ),
                "quality": (
                    "All quality conditions must pass, then eligible stocks are "
                    f"ranked by GP/A and the top {self.quality_basket_size} are "
                    "selected as an equal-weight basket."
                ),
            },
            "summary": {
                "company_count": len(results),
                "buffett_candidate_count": len(buffett_candidates),
                "quality_eligible_count": len(quality_candidates),
                "quality_basket_count": len(selected_quality),
                "buffett_status_counts": dict(
                    sorted(buffett_status_counts.items())
                ),
                "quality_status_counts": dict(
                    sorted(quality_status_counts.items())
                ),
            },
            "rankings": {
                "buffett_candidates": [
                    {
                        "ticker": row["ticker"],
                        "company": row["company"],
                        "fcf_yield_pct": (
                            row["buffett"].get("valuation") or {}
                        ).get("fcf_yield_pct"),
                        "n_base_years": row["n"].get("base_years"),
                        "n_confidence": (
                            row["n"].get("confidence") or {}
                        ).get("label"),
                    }
                    for row in buffett_candidates
                ],
                "quality_equal_weight_basket": [
                    {
                        "rank": row["quality"]["basket_rank"],
                        "ticker": row["ticker"],
                        "company": row["company"],
                        "gpa_pct": row["quality"]["gpa_pct"],
                        "weight_pct": round(
                            100 / len(selected_quality), 4
                        )
                        if selected_quality
                        else None,
                        "n_base_years": row["n"].get("base_years"),
                    }
                    for row in selected_quality
                ],
            },
            "results": results,
        }

    def _company_metadata(
        self,
        panel: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in panel.get("observations") or []:
            ticker = str(row.get("ticker") or "").strip().zfill(6)
            year = int(row.get("fiscal_year") or 0)
            existing = result.get(ticker)
            if existing and int(existing.get("latest_year") or 0) > year:
                continue
            result[ticker] = {
                "company": row.get("company"),
                "market": row.get("market"),
                "sector": row.get("sector"),
                "industry": row.get("industry"),
                "latest_year": year,
            }
        return result
