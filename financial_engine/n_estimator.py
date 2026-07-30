from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from .config import ENGINE_VERSION, METHODOLOGY_VERSION, NEngineConfig
from .statistics import (
    clamp,
    equivalent_n_from_r,
    extract_high_roe_spells,
    finite_number,
    kaplan_meier_survival,
    median,
    percentile_rank,
    population_std,
    restricted_mean_residual_life,
    slope_through_origin,
    trailing_streak,
)
from .taxonomy import classify_sector


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FinancialNEstimator:
    """Estimate the future persistence horizon of excess profitability.

    The estimator has intentionally separate layers:
    sector prior -> empirical sector fade -> survival evidence -> company
    modifiers. Each layer is returned with provenance so later research can
    replace one layer without rewriting the rest of the pipeline.
    """

    def __init__(self, config: NEngineConfig | None = None) -> None:
        self.config = config or NEngineConfig()

    def estimate(self, panel: dict[str, Any]) -> dict[str, Any]:
        parameter_payload = self.config.to_dict()
        config_signature = hashlib.sha256(
            json.dumps(
                parameter_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        observations = self._normalized_observations(panel)
        by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in observations:
            by_ticker[row["ticker"]].append(row)
        for rows in by_ticker.values():
            rows.sort(key=lambda item: item["fiscal_year"])

        sector_models = self._build_sector_models(observations, by_ticker)
        gpa_population = self._latest_gpa_population(by_ticker)
        estimates = {
            ticker: self._estimate_company(
                rows,
                sector_models[rows[-1]["sector_group"]],
                gpa_population.get(rows[-1]["sector_group"], []),
            )
            for ticker, rows in sorted(by_ticker.items())
        }

        confidence_counts = Counter(
            item["confidence"]["label"] for item in estimates.values()
        )
        status_counts = Counter(item["status"] for item in estimates.values())
        return {
            "schema_version": 1,
            "engine_version": ENGINE_VERSION,
            "methodology_version": METHODOLOGY_VERSION,
            "config_signature": config_signature,
            "generated_at_utc": _utc_now_iso(),
            "source_panel": {
                "schema_version": panel.get("schema_version"),
                "crawled_at_utc": panel.get("crawled_at_utc"),
                "period": panel.get("period"),
                "complete": panel.get("complete"),
                "detail_complete": (
                    panel.get("detail_enrichment") or {}
                ).get("complete"),
            },
            "complete": bool(estimates) and all(
                item["status"] in {"estimated", "robust"}
                for item in estimates.values()
            ),
            "parameters": parameter_payload,
            "methodology": {
                "target": (
                    "Expected future years of elevated ROE persistence; this is "
                    "the N consumed by the valuation model."
                ),
                "sector_fade": (
                    "Four-year regression of sector-year demeaned ROE(t+4) on "
                    "demeaned ROE(t), shrunk toward a documented sector prior. "
                    "Equivalent N = -lag / ln(r)."
                ),
                "survival": (
                    "Two-year-confirmed high-ROE spells, Kaplan-Meier survival "
                    "and restricted mean residual life capped at max_n_years."
                ),
                "company_modifiers": (
                    "ROE volatility, confirmed streak, reinvestment intensity, "
                    "GP/A percentile/stability and extreme-ROE mean reversion."
                ),
                "guardrails": (
                    "No missing criterion is silently treated as pass. Priors and "
                    "partial histories remain available but are labeled provisional."
                ),
            },
            "summary": {
                "observation_count": len(observations),
                "company_count": len(estimates),
                "sector_group_count": len(sector_models),
                "status_counts": dict(sorted(status_counts.items())),
                "confidence_counts": dict(sorted(confidence_counts.items())),
            },
            "sector_models": sector_models,
            "estimates": estimates,
        }

    def _normalized_observations(
        self,
        panel: dict[str, Any],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for source in panel.get("observations") or []:
            ticker = str(source.get("ticker") or "").strip().zfill(6)
            year = int(source.get("fiscal_year") or 0)
            metrics = source.get("metrics") or {}
            roe = finite_number(metrics.get("roe_for_model_pct"))
            if roe is None:
                roe = finite_number(metrics.get("roe_pct"))
            if not ticker or not year or roe is None:
                continue
            detail = source.get("detail_metrics") or {}
            normalized = {
                "ticker": ticker,
                "company": source.get("company"),
                "fiscal_year": year,
                "roe_pct": clamp(roe, -50.0, 50.0),
                "sector": source.get("sector"),
                "industry": source.get("industry"),
                "is_financial": bool(source.get("is_financial")),
                "detail_complete": source.get("detail_status") == "complete",
                "invested_capital": finite_number(
                    detail.get("invested_capital")
                ),
                "nopat": finite_number(detail.get("nopat")),
                "gpa_pct": finite_number(
                    detail.get("gross_profit_to_assets_pct")
                ),
            }
            normalized["sector_group"] = classify_sector(
                {**source, **normalized}
            )
            result.append(normalized)
        return result

    def _build_sector_models(
        self,
        observations: list[dict[str, Any]],
        by_ticker: dict[str, list[dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        cfg = self.config
        median_by_group_year: dict[tuple[str, int], float] = {}
        values_by_group_year: dict[tuple[str, int], list[float]] = defaultdict(
            list
        )
        for row in observations:
            values_by_group_year[
                (row["sector_group"], row["fiscal_year"])
            ].append(row["roe_pct"])
        for key, values in values_by_group_year.items():
            group_median = median(values)
            if group_median is not None:
                median_by_group_year[key] = group_median

        pairs_by_group: dict[str, list[tuple[float, float]]] = defaultdict(list)
        company_counts: dict[str, set[str]] = defaultdict(set)
        for ticker, rows in by_ticker.items():
            row_by_year = {row["fiscal_year"]: row for row in rows}
            for row in rows:
                later = row_by_year.get(row["fiscal_year"] + cfg.lag_years)
                if not later or later["sector_group"] != row["sector_group"]:
                    continue
                group = row["sector_group"]
                start_median = median_by_group_year.get(
                    (group, row["fiscal_year"])
                )
                end_median = median_by_group_year.get(
                    (group, later["fiscal_year"])
                )
                if start_median is None or end_median is None:
                    continue
                pairs_by_group[group].append(
                    (
                        row["roe_pct"] - start_median,
                        later["roe_pct"] - end_median,
                    )
                )
                company_counts[group].add(ticker)

        spells_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for rows in by_ticker.values():
            latest = rows[-1]
            threshold = (
                cfg.financial_high_roe_pct
                if latest["is_financial"]
                else cfg.fixed_high_roe_pct
            )
            series = [
                (row["fiscal_year"], row["roe_pct"]) for row in rows
            ]
            spells_by_group[latest["sector_group"]].extend(
                extract_high_roe_spells(series, threshold)
            )

        groups = sorted({row["sector_group"] for row in observations})
        models: dict[str, dict[str, Any]] = {}
        for group in groups:
            pairs = pairs_by_group.get(group, [])
            raw_r = slope_through_origin(pairs)
            prior_r = cfg.prior_r_by_group.get(
                group, cfg.default_prior_r
            )
            empirical_pair_count = len(pairs)
            empirical_usable = (
                raw_r is not None and raw_r > 0 and empirical_pair_count > 0
            )
            shrinkage_weight = (
                empirical_pair_count
                / (empirical_pair_count + cfg.shrinkage_prior_strength)
                if empirical_usable
                else 0.0
            )
            shrunk_r = (
                shrinkage_weight * clamp(raw_r, 0.01, 0.999)
                + (1 - shrinkage_weight) * prior_r
                if empirical_usable
                else prior_r
            )
            n_years = equivalent_n_from_r(
                shrunk_r,
                cfg.lag_years,
                cfg.min_n_years,
                cfg.max_n_years,
            )
            spells = spells_by_group.get(group, [])
            event_count = sum(
                bool(spell.get("event_observed")) for spell in spells
            )
            survival = kaplan_meier_survival(
                spells, int(math.ceil(cfg.max_n_years))
            )
            models[group] = {
                "group": group,
                "prior_r": round(prior_r, 4),
                "raw_r": round(raw_r, 4) if raw_r is not None else None,
                "shrunk_r": round(shrunk_r, 4),
                "shrinkage_weight": round(shrinkage_weight, 4),
                "equivalent_n_years": n_years,
                "pair_count": empirical_pair_count,
                "company_pair_count": len(company_counts.get(group, set())),
                "empirical_ready": (
                    empirical_usable
                    and empirical_pair_count >= cfg.min_sector_pairs
                    and len(company_counts.get(group, set()))
                    >= cfg.min_sector_companies
                ),
                "spell_count": len(spells),
                "event_count": event_count,
                "survival_ready": (
                    len(spells) >= cfg.survival_min_spells
                    and event_count >= cfg.survival_min_events
                ),
                "survival": {
                    str(year): round(probability, 6)
                    for year, probability in survival.items()
                },
            }
        return models

    def _latest_gpa_population(
        self,
        by_ticker: dict[str, list[dict[str, Any]]],
    ) -> dict[str, list[float]]:
        population: dict[str, list[float]] = defaultdict(list)
        for rows in by_ticker.values():
            latest_gpa = next(
                (
                    row["gpa_pct"]
                    for row in reversed(rows)
                    if row["gpa_pct"] is not None
                ),
                None,
            )
            if latest_gpa is not None:
                population[rows[-1]["sector_group"]].append(latest_gpa)
        return population

    def _estimate_company(
        self,
        rows: list[dict[str, Any]],
        sector_model: dict[str, Any],
        sector_gpa_population: list[float],
    ) -> dict[str, Any]:
        cfg = self.config
        latest = rows[-1]
        roe_series = [
            (row["fiscal_year"], row["roe_pct"]) for row in rows
        ]
        roe_values = [value for _, value in roe_series]
        threshold = (
            cfg.financial_high_roe_pct
            if latest["is_financial"]
            else cfg.fixed_high_roe_pct
        )
        streak = trailing_streak(roe_series, threshold)
        base_n = float(sector_model["equivalent_n_years"])
        sources = [
            {
                "layer": "sector_prior",
                "value_years": base_n,
                "sector_group": latest["sector_group"],
            }
        ]
        if sector_model["pair_count"] > 0:
            sources.append(
                {
                    "layer": "sector_autocorrelation",
                    "raw_r": sector_model["raw_r"],
                    "shrunk_r": sector_model["shrunk_r"],
                    "pair_count": sector_model["pair_count"],
                    "weight": sector_model["shrinkage_weight"],
                }
            )

        survival_remaining = None
        if streak["confirmed"] and sector_model["survival_ready"]:
            survival = {
                int(year): value
                for year, value in sector_model["survival"].items()
            }
            survival_remaining = restricted_mean_residual_life(
                survival,
                min(streak["years"], int(cfg.max_n_years)),
                int(cfg.max_n_years),
            )
            if survival_remaining is not None:
                base_n = (
                    (1 - cfg.survival_weight) * base_n
                    + cfg.survival_weight * survival_remaining
                )
                sources.append(
                    {
                        "layer": "survival_mrl",
                        "current_streak_years": streak["years"],
                        "remaining_years": survival_remaining,
                        "spell_count": sector_model["spell_count"],
                        "weight": cfg.survival_weight,
                    }
                )

        modifiers = self._company_modifiers(
            rows, streak, sector_gpa_population
        )
        modifier_total = sum(item["n_years"] for item in modifiers)
        estimate = clamp(
            base_n + modifier_total,
            cfg.min_n_years,
            cfg.max_n_years,
        )
        confidence = self._confidence(rows, sector_model)
        margin = {
            "low": cfg.scenario_margin_low_confidence,
            "medium": cfg.scenario_margin_medium_confidence,
            "high": cfg.scenario_margin_high_confidence,
        }[confidence["label"]]
        scenarios = {
            "conservative_years": round(
                clamp(estimate - margin, cfg.min_n_years, cfg.max_n_years),
                1,
            ),
            "base_years": round(estimate, 1),
            "optimistic_years": round(
                clamp(
                    estimate + margin,
                    cfg.min_n_years,
                    cfg.max_n_years,
                ),
                1,
            ),
        }
        observation_count = len(rows)
        empirical_ready = sector_model["empirical_ready"]
        if observation_count < cfg.min_company_observations:
            status = "prior_only"
        elif observation_count < cfg.full_company_observations or not empirical_ready:
            status = "provisional"
        elif confidence["label"] == "high":
            status = "robust"
        else:
            status = "estimated"

        return {
            "ticker": latest["ticker"],
            "company": latest["company"],
            "sector_group": latest["sector_group"],
            "is_financial": latest["is_financial"],
            "status": status,
            "as_of_fiscal_year": latest["fiscal_year"],
            "observed_year_count": observation_count,
            "observed_years": [row["fiscal_year"] for row in rows],
            "threshold_roe_pct": threshold,
            "roe": {
                "latest_pct": round(roe_values[-1], 4),
                "mean_pct": round(statistics.mean(roe_values), 4),
                "volatility_pct_points": (
                    round(population_std(roe_values), 4)
                    if len(roe_values) >= 2
                    else None
                ),
                "trailing_high_roe_streak": streak,
            },
            "estimate": scenarios,
            "sector_base_n_years": round(
                float(sector_model["equivalent_n_years"]), 3
            ),
            "survival_remaining_years": survival_remaining,
            "modifier_total_years": round(modifier_total, 3),
            "modifiers": modifiers,
            "confidence": confidence,
            "sources": sources,
            "warnings": self._warnings(rows, sector_model),
        }

    def _company_modifiers(
        self,
        rows: list[dict[str, Any]],
        streak: dict[str, Any],
        sector_gpa_population: list[float],
    ) -> list[dict[str, Any]]:
        cfg = self.config
        modifiers: list[dict[str, Any]] = []
        roe_values = [row["roe_pct"] for row in rows]
        volatility = population_std(roe_values)
        if volatility is not None:
            if volatility <= cfg.volatility_low_pct_points:
                modifiers.append(
                    {
                        "factor": "low_roe_volatility",
                        "n_years": 1.0,
                        "observed": round(volatility, 4),
                    }
                )
            elif volatility >= cfg.volatility_high_pct_points:
                modifiers.append(
                    {
                        "factor": "high_roe_volatility",
                        "n_years": -1.5,
                        "observed": round(volatility, 4),
                    }
                )

        if streak["confirmed"] and streak["years"] >= 5:
            modifiers.append(
                {
                    "factor": "confirmed_long_streak",
                    "n_years": 0.75,
                    "observed": streak["years"],
                }
            )

        latest_roe = rows[-1]["roe_pct"]
        if latest_roe >= cfg.extreme_roe_pct:
            modifiers.append(
                {
                    "factor": "extreme_roe_mean_reversion",
                    "n_years": -1.0,
                    "observed": latest_roe,
                }
            )

        reinvestment_rates: list[float] = []
        for previous, current in zip(rows, rows[1:]):
            capital_before = previous["invested_capital"]
            capital_after = current["invested_capital"]
            nopat = current["nopat"]
            if (
                capital_before is not None
                and capital_after is not None
                and nopat is not None
                and nopat > 0
            ):
                rate = (capital_after - capital_before) / nopat
                if math.isfinite(rate):
                    reinvestment_rates.append(rate)
        if reinvestment_rates:
            recent_rate = statistics.median(reinvestment_rates[-3:])
            if recent_rate >= cfg.high_reinvestment_rate:
                modifiers.append(
                    {
                        "factor": "high_reinvestment_fade",
                        "n_years": -0.75,
                        "observed": round(recent_rate, 4),
                    }
                )

        gpa_values = [
            row["gpa_pct"] for row in rows if row["gpa_pct"] is not None
        ]
        if gpa_values and sector_gpa_population:
            rank = percentile_rank(gpa_values[-1], sector_gpa_population)
            gpa_volatility = population_std(gpa_values)
            if (
                rank is not None
                and rank >= cfg.gpa_high_percentile
                and (
                    gpa_volatility is None
                    or gpa_volatility <= cfg.volatility_low_pct_points
                )
            ):
                modifiers.append(
                    {
                        "factor": "high_stable_gpa",
                        "n_years": 0.75,
                        "observed": {
                            "sector_percentile": round(rank, 4),
                            "volatility_pct_points": (
                                round(gpa_volatility, 4)
                                if gpa_volatility is not None
                                else None
                            ),
                        },
                    }
                )
        return modifiers

    def _confidence(
        self,
        rows: list[dict[str, Any]],
        sector_model: dict[str, Any],
    ) -> dict[str, Any]:
        cfg = self.config
        observation_score = min(35.0, len(rows) / 10 * 35.0)
        pair_score = (
            min(
                sector_model["pair_count"]
                / max(1, cfg.high_confidence_sector_pairs),
                sector_model["company_pair_count"]
                / max(1, cfg.high_confidence_sector_companies),
                1.0,
            )
            * 40.0
            if sector_model["raw_r"] is not None
            else 0.0
        )
        detail_score = (
            sum(row["detail_complete"] for row in rows) / len(rows) * 15.0
        )
        survival_score = 10.0 if sector_model["survival_ready"] else 0.0
        score = round(
            observation_score + pair_score + detail_score + survival_score,
            1,
        )
        label = "high" if score >= 75 else "medium" if score >= 45 else "low"
        return {
            "label": label,
            "score_0_to_100": score,
            "components": {
                "company_history": round(observation_score, 1),
                "sector_pairs": round(pair_score, 1),
                "detail_coverage": round(detail_score, 1),
                "survival_sample": round(survival_score, 1),
            },
        }

    def _warnings(
        self,
        rows: list[dict[str, Any]],
        sector_model: dict[str, Any],
    ) -> list[str]:
        cfg = self.config
        warnings: list[str] = []
        if len(rows) < cfg.full_company_observations:
            warnings.append("company_history_incomplete")
        if not sector_model["empirical_ready"]:
            warnings.append("sector_pair_sample_below_minimum")
        if sector_model["company_pair_count"] < cfg.min_sector_companies:
            warnings.append("sector_company_sample_below_minimum")
        if not sector_model["survival_ready"]:
            warnings.append("survival_sample_below_minimum")
        if sum(row["detail_complete"] for row in rows) < len(rows):
            warnings.append("detail_financials_incomplete")
        if rows[0]["fiscal_year"] > 2015:
            warnings.append("left_truncated_listing_history")
        return warnings
