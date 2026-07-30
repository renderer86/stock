import math
import unittest

from financial_engine import (
    FinancialNEstimator,
    InvestmentScreenBuilder,
    NEngineConfig,
)
from financial_engine.statistics import (
    equivalent_n_from_r,
    extract_high_roe_spells,
    restricted_mean_residual_life,
)


def synthetic_panel() -> dict:
    observations = []
    deviations = {
        "000001": -4,
        "000002": -2,
        "000003": 0,
        "000004": 2,
        "000005": 4,
    }
    for ticker, initial_deviation in deviations.items():
        for year in range(2016, 2026):
            deviation = initial_deviation * (
                0.5 ** ((year - 2016) / 4)
            )
            observations.append(
                {
                    "ticker": ticker,
                    "company": f"테스트{ticker}",
                    "market": "KOSPI",
                    "sector": "반도체",
                    "industry": "반도체",
                    "is_financial": False,
                    "fiscal_year": year,
                    "metrics": {
                        "roe_pct": 16 + deviation,
                        "roe_for_model_pct": 16 + deviation,
                    },
                    "detail_status": "complete",
                    "detail_metrics": {
                        "invested_capital": 1000 + (year - 2016) * 20,
                        "nopat": 100,
                        "gross_profit_to_assets_pct": 20
                        + initial_deviation / 10,
                    },
                }
            )
    return {
        "schema_version": 1,
        "complete": True,
        "period": {"start_year": 2016, "end_year": 2025},
        "detail_enrichment": {"complete": True},
        "observations": observations,
    }


class FinancialNEngineTest(unittest.TestCase):
    def test_equivalent_n_and_spell_survival_helpers(self) -> None:
        self.assertAlmostEqual(
            equivalent_n_from_r(0.5, 4, 1, 15),
            -4 / math.log(0.5),
            places=3,
        )
        spells = extract_high_roe_spells(
            [
                (2018, 13),
                (2019, 14),
                (2020, 15),
                (2021, 8),
                (2022, 7),
                (2023, 13),
                (2024, 14),
            ],
            12,
        )
        self.assertEqual(len(spells), 2)
        self.assertTrue(spells[0]["event_observed"])
        self.assertEqual(spells[0]["duration"], 3)
        self.assertFalse(spells[1]["event_observed"])
        self.assertEqual(
            restricted_mean_residual_life(
                {0: 1, 1: 0.8, 2: 0.6, 3: 0.4},
                1,
                3,
            ),
            1.25,
        )

    def test_sector_autocorrelation_drives_versioned_n_estimate(self) -> None:
        config = NEngineConfig(
            min_sector_pairs=5,
            high_confidence_sector_pairs=10,
            min_sector_companies=3,
            high_confidence_sector_companies=5,
            shrinkage_prior_strength=0,
            survival_min_spells=999,
        )
        payload = FinancialNEstimator(config).estimate(synthetic_panel())
        sector = payload["sector_models"]["information_technology"]
        self.assertAlmostEqual(sector["raw_r"], 0.5, places=3)
        self.assertAlmostEqual(
            sector["equivalent_n_years"],
            -4 / math.log(0.5),
            places=3,
        )
        estimate = payload["estimates"]["000003"]
        self.assertEqual(estimate["status"], "robust")
        self.assertEqual(estimate["confidence"]["label"], "high")
        self.assertTrue(
            any(
                source["layer"] == "sector_autocorrelation"
                for source in estimate["sources"]
            )
        )

    def test_partial_history_remains_prior_only_not_false_precision(self) -> None:
        panel = {
            "observations": [
                {
                    "ticker": "009999",
                    "company": "신규상장",
                    "sector": "화학",
                    "industry": "화학",
                    "fiscal_year": year,
                    "metrics": {
                        "roe_pct": 14,
                        "roe_for_model_pct": 14,
                    },
                }
                for year in (2024, 2025)
            ]
        }
        payload = FinancialNEstimator().estimate(panel)
        estimate = payload["estimates"]["009999"]
        self.assertEqual(estimate["status"], "prior_only")
        self.assertEqual(estimate["confidence"]["label"], "low")
        self.assertIn(
            "sector_pair_sample_below_minimum",
            estimate["warnings"],
        )

    def test_buffett_and_quality_screens_join_n_without_missing_passes(self) -> None:
        panel = {
            "observations": [
                {
                    "ticker": "000001",
                    "company": "후보",
                    "market": "KOSPI",
                    "sector": "식품",
                    "industry": "식품",
                    "fiscal_year": 2025,
                },
                {
                    "ticker": "000002",
                    "company": "미완성",
                    "market": "KOSPI",
                    "sector": "식품",
                    "industry": "식품",
                    "fiscal_year": 2025,
                },
            ],
            "screening_features": {
                "000001": {
                    "company": "후보",
                    "buffett": {
                        "conditions": {"a": True, "b": True},
                        "valuation": {
                            "fcf_yield_pct": 6,
                            "fcf_yield_ge_5pct": True,
                        },
                    },
                    "quality": {
                        "conditions": {"a": True, "b": True},
                        "latest_gross_profit_to_assets_pct": 30,
                    },
                },
                "000002": {
                    "company": "미완성",
                    "buffett": {
                        "conditions": {"a": True, "b": None},
                        "valuation": {
                            "fcf_yield_pct": None,
                            "fcf_yield_ge_5pct": None,
                        },
                    },
                    "quality": {
                        "conditions": {"a": True, "b": None},
                        "latest_gross_profit_to_assets_pct": 20,
                    },
                },
            },
        }
        n_payload = {
            "estimates": {
                ticker: {
                    "status": "estimated",
                    "estimate": {
                        "base_years": 6,
                        "conservative_years": 5,
                        "optimistic_years": 7,
                    },
                    "confidence": {"label": "medium"},
                    "warnings": [],
                }
                for ticker in ("000001", "000002")
            }
        }
        result = InvestmentScreenBuilder(quality_basket_size=25).build(
            panel,
            n_payload,
            {"stocks": []},
        )
        self.assertTrue(result["results"]["000001"]["buffett"]["candidate"])
        self.assertTrue(
            result["results"]["000001"]["quality"]["selected_for_basket"]
        )
        self.assertEqual(
            result["results"]["000002"]["buffett"][
                "business_quality_status"
            ],
            "pending",
        )
        self.assertEqual(
            result["results"]["000002"]["quality"]["status"],
            "pending",
        )


if __name__ == "__main__":
    unittest.main()
