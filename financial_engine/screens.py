from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import math
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


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _buffett_watchlist_profile(
    rows: list[dict[str, Any]],
    conditions: dict[str, Any],
    valuation: dict[str, Any],
) -> dict[str, Any]:
    """Apply the current-return gate and describe observable strengths."""
    rows = sorted(rows, key=lambda row: int(row.get("fiscal_year") or 0))
    latest_year = max(
        (int(row.get("fiscal_year") or 0) for row in rows),
        default=0,
    )
    is_financial = bool(rows[-1].get("is_financial")) if rows else False
    metric = "ROE" if is_financial else "ROIC"
    hurdle = 10 if is_financial else 12
    by_year = {
        int(row.get("fiscal_year") or 0): row
        for row in rows
        if row.get("fiscal_year")
    }
    recent_years = list(range(latest_year - 2, latest_year + 1))
    recent_values: list[float | None] = []
    for year in recent_years:
        row = by_year.get(year) or {}
        value = (
            (row.get("metrics") or {}).get("roe_pct")
            if is_financial
            else (row.get("detail_metrics") or {}).get("roic_pct")
        )
        recent_values.append(_number(value))

    if any(value is not None and value < hurdle for value in recent_values):
        minimum_status = "fail"
    elif len(recent_values) == 3 and all(
        value is not None and value >= hurdle for value in recent_values
    ):
        minimum_status = "pass"
    else:
        minimum_status = "pending"

    eps_years = list(range(latest_year - 4, latest_year + 1))
    eps_values = [
        _number(
            ((by_year.get(year) or {}).get("detail_metrics") or {}).get(
                "basic_eps"
            )
        )
        for year in eps_years
    ]
    eps_cagr = None
    if (
        len(eps_values) == 5
        and all(value is not None and value > 0 for value in eps_values)
    ):
        eps_cagr = (
            (float(eps_values[-1]) / float(eps_values[0])) ** (1 / 4) - 1
        ) * 100

    latest_row = by_year.get(latest_year) or {}
    latest_metrics = latest_row.get("detail_metrics") or {}
    latest_net_debt = _number(latest_metrics.get("net_debt"))
    fcf_yield = _number(valuation.get("fcf_yield_pct"))
    supporting_count = sum(value is True for value in conditions.values())
    unknown_support = any(value is None for value in conditions.values())

    if minimum_status == "fail":
        watchlist_status = "fail"
    elif minimum_status == "pending":
        watchlist_status = "pending"
    elif supporting_count:
        watchlist_status = "pass"
    elif unknown_support:
        watchlist_status = "pending"
    else:
        watchlist_status = "fail"

    tags: list[str] = []
    if conditions.get("persistence_9_of_10") is True:
        tags.append(f"매우 높은 장기 {metric}")
    if eps_cagr is not None and eps_cagr >= 8:
        tags.append("강한 주당 이익 성장")
    if conditions.get("positive_net_income_all_10y") is True:
        tags.append("10년 연속 흑자")
    if conditions.get("gross_margin_sigma_le_5pp") is True:
        tags.append("안정적인 마진")
    if conditions.get("fcf_conversion_ge_0_8") is True:
        tags.append("탁월한 FCF 전환")
    if latest_net_debt is not None and latest_net_debt <= 0 and (
        fcf_yield is not None and fcf_yield >= 5
    ):
        tags.append("순현금·높은 FCF 수익률")
    elif conditions.get("net_debt_to_ebitda_le_2_or_net_cash") is True:
        tags.append("튼튼한 재무")
    if conditions.get("shares_not_increased_10y") is True:
        tags.append("주식수 희석 없음")
    if conditions.get("incremental_roic_ge_15_or_payout_ge_50") is True:
        tags.append("뛰어난 자본배분")

    missing_reasons: list[str] = []
    if minimum_status == "pending":
        missing_reasons.append("recent_3y_persistence")
    if minimum_status == "pass" and not supporting_count and unknown_support:
        missing_reasons.append("supporting_buffett_condition")

    known_recent = [value for value in recent_values if value is not None]
    return {
        "watchlist_status": watchlist_status,
        "watchlist_eligible": watchlist_status == "pass",
        "minimum_persistence_status": minimum_status,
        "minimum_persistence_metric": metric,
        "minimum_persistence_hurdle_pct": hurdle,
        "minimum_persistence_years": recent_years,
        "minimum_persistence_values_pct": recent_values,
        "minimum_persistence_average_pct": (
            round(sum(known_recent) / len(known_recent), 4)
            if len(known_recent) == 3
            else None
        ),
        "supporting_condition_count": supporting_count,
        "strength_tags": tags,
        "eps_cagr_5y_pct": round(eps_cagr, 4)
        if eps_cagr is not None
        else None,
        "missing_reasons": missing_reasons,
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
        observations_by_ticker: dict[str, list[dict[str, Any]]] = {}
        for observation in panel.get("observations") or []:
            observation_ticker = str(
                observation.get("ticker") or ""
            ).strip().zfill(6)
            observations_by_ticker.setdefault(observation_ticker, []).append(
                observation
            )
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
            watchlist = _buffett_watchlist_profile(
                observations_by_ticker.get(ticker) or [],
                buffett_conditions,
                valuation,
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
                    **watchlist,
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
        buffett_watchlist = sorted(
            (
                row
                for row in results.values()
                if row["buffett"]["watchlist_eligible"]
            ),
            key=lambda row: (
                -int(row["buffett"]["supporting_condition_count"]),
                -float(
                    row["buffett"].get(
                        "minimum_persistence_average_pct"
                    )
                    or -999
                ),
                -float(row["buffett"].get("eps_cagr_5y_pct") or -999),
                -float(
                    (row["buffett"].get("valuation") or {}).get(
                        "fcf_yield_pct"
                    )
                    or -999
                ),
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
        buffett_watchlist_status_counts = Counter(
            row["buffett"]["watchlist_status"]
            for row in results.values()
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
                    "The interest watchlist requires ROIC >=12% for the latest "
                    "three consecutive fiscal years (ROE >=10% for financials) "
                    "and at least one true condition from the original seven. "
                    "The legacy strict candidate still requires all seven plus "
                    "FCF yield >=5%."
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
                "buffett_watchlist_count": len(buffett_watchlist),
                "quality_eligible_count": len(quality_candidates),
                "quality_basket_count": len(selected_quality),
                "buffett_status_counts": dict(
                    sorted(buffett_status_counts.items())
                ),
                "buffett_watchlist_status_counts": dict(
                    sorted(buffett_watchlist_status_counts.items())
                ),
                "quality_status_counts": dict(
                    sorted(quality_status_counts.items())
                ),
            },
            "rankings": {
                "buffett_watchlist": [
                    {
                        "rank": rank,
                        "ticker": row["ticker"],
                        "company": row["company"],
                        "supporting_condition_count": row["buffett"][
                            "supporting_condition_count"
                        ],
                        "recent_return_average_pct": row["buffett"].get(
                            "minimum_persistence_average_pct"
                        ),
                        "strength_tags": row["buffett"].get(
                            "strength_tags"
                        ),
                        "strict_candidate": row["buffett"]["candidate"],
                    }
                    for rank, row in enumerate(buffett_watchlist, start=1)
                ],
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
