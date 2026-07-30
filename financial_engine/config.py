from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


ENGINE_VERSION = "0.1.0"
METHODOLOGY_VERSION = "n-persistence-2026-07-v1"


@dataclass(frozen=True)
class NEngineConfig:
    """Versioned knobs for the N engine.

    Keep empirical methodology parameters here instead of scattering magic
    numbers through estimators. A future methodology can be introduced as a
    second config/version without rewriting the data adapters or dashboard.
    """

    lag_years: int = 4
    min_n_years: float = 1.0
    max_n_years: float = 15.0
    min_company_observations: int = 3
    full_company_observations: int = 8
    min_sector_pairs: int = 30
    high_confidence_sector_pairs: int = 100
    min_sector_companies: int = 20
    high_confidence_sector_companies: int = 50
    shrinkage_prior_strength: float = 50.0
    default_prior_r: float = 0.50
    fixed_high_roe_pct: float = 12.0
    financial_high_roe_pct: float = 10.0
    survival_min_spells: int = 30
    survival_min_events: int = 10
    survival_weight: float = 0.35
    volatility_low_pct_points: float = 3.0
    volatility_high_pct_points: float = 8.0
    extreme_roe_pct: float = 30.0
    high_reinvestment_rate: float = 0.75
    gpa_high_percentile: float = 0.70
    scenario_margin_low_confidence: float = 2.5
    scenario_margin_medium_confidence: float = 1.5
    scenario_margin_high_confidence: float = 1.0
    prior_r_by_group: dict[str, float] = field(
        default_factory=lambda: {
            "consumer_staples": 0.78,
            "consumer_discretionary": 0.67,
            "healthcare": 0.64,
            "industrials": 0.62,
            "information_technology": 0.50,
            "financials": 0.43,
            "materials": 0.41,
            "energy": 0.35,
            "communication_services": 0.50,
            "utilities": 0.55,
            "real_estate": 0.50,
            "other": 0.50,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
