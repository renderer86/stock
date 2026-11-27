from __future__ import annotations

from datetime import date
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from build_valuation_metrics import RawReports, build_metrics, parse_report, standardized
from financial_engine.valuation import evaluate_returns, trailing_income


ROOT = Path(__file__).resolve().parents[1]


def accounts(**overrides):
    return {"assets": 2000, "equity": 1000, "owners_equity": 900, "capital_stock": 100,
            "net_income": 120, "owners_net_income": 100,
            "continuing_net_income": 120, "discontinued_net_income": 0, **overrides}


def report(end, **overrides):
    return {"period_end": end, "basis": "CFS", "current": accounts(),
            "previous": accounts(), "sources": [], **overrides}


class MemoryReports:
    def __init__(self, reports):
        self.reports = reports

    def bulk(self, year, code):
        return self.reports.get((year, code), {})

    def api(self, *args):
        return None


class ValuationMetricTests(unittest.TestCase):
    def evaluate(self, start=None, end=None, income=None, **kwargs):
        return evaluate_returns(start or accounts(), end or accounts(), income or accounts(),
                                period_end="2026-09-30", basis="CFS", method="ttm", **kwargs)

    def test_ttm_uses_annual_plus_ytd_less_comparative_ytd(self):
        income = trailing_income(accounts(owners_net_income=100), accounts(owners_net_income=90), accounts(owners_net_income=60))
        result = self.evaluate(end=accounts(owners_equity=1100), income=income)
        self.assertEqual(result["roe_pct"], 13)
        self.assertEqual(result["period_start"], "2025-10-01")
        self.assertEqual(result["balance_start"], "2025-09-30")
        self.assertTrue(result["eligible"])

    def test_quarterly_income_uses_cumulative_columns_only(self):
        rows = [{"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "account_nm": "분기순이익",
                 "thstrm_amount": "10", "thstrm_add_amount": "90", "frmtrm_q_amount": "20", "frmtrm_add_amount": "60"}]
        parsed = parse_report(rows, "OFS", "2026-09-30", [])
        self.assertEqual(parsed["current"]["net_income"], 90)
        self.assertEqual(parsed["previous"]["net_income"], 60)
        rows[0]["thstrm_add_amount"] = None
        self.assertNotIn("net_income", parse_report(rows, "OFS", "2026-09-30", [])["current"])
        self.assertEqual(parse_report(rows, "OFS", "2026-03-31", [])["current"]["net_income"], 10)

    def test_consolidated_profit_and_equity_do_not_replace_parent_amounts(self):
        rows = [{"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "thstrm_amount": "120"}]
        self.assertNotIn("owners_net_income", standardized(rows, "CFS"))
        self.assertEqual(standardized(rows, "OFS")["owners_net_income"], 120)

    def test_missing_discontinued_amount_is_not_assumed_zero(self):
        rows = [{"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "thstrm_amount": "120"},
                {"sj_div": "IS", "account_id": "ifrs-full_ProfitLossFromDiscontinuedOperations", "thstrm_amount": ""}]
        self.assertNotIn("discontinued_net_income", standardized(rows, "CFS"))
        self.assertEqual(standardized(rows[:1], "CFS")["discontinued_net_income"], 0)

    def test_material_discontinued_profit_and_continuing_loss_are_excluded(self):
        for income in (accounts(discontinued_net_income=12, continuing_net_income=108),
                       accounts(discontinued_net_income=150, continuing_net_income=-30)):
            result = self.evaluate(income=income)
            self.assertFalse(result["eligible"])
            self.assertIn("material_discontinued_profit", result["quality_reasons"])
        self.assertTrue(self.evaluate(income=accounts(discontinued_net_income=1, continuing_net_income=119))["eligible"])

    def test_nonpositive_endpoint_is_rejected_even_when_average_is_positive(self):
        result = self.evaluate(start=accounts(owners_equity=-100))
        self.assertIn("nonpositive_equity", result["quality_reasons"])
        self.assertIsNone(result["roe_pct"])

    def test_partial_impairment_thin_equity_and_recent_history(self):
        for a, reason in ((accounts(owners_equity=50), "capital_impairment"),
                          (accounts(owners_equity=99, capital_stock=1), "thin_equity")):
            result = self.evaluate(start=a)
            self.assertFalse(result["eligible"])
            self.assertIn(reason, result["quality_reasons"])
        self.assertIn("recent_capital_impairment", self.evaluate(capital_history=[accounts(equity=-1)])["quality_reasons"])

    def build(self, store, interim=None, panel=None, as_of=date(2026, 11, 28)):
        panel = panel or {"observations": [{"ticker": "000001", "fiscal_year": y,
            "corp_code": "00000001", "statement_basis": "CFS"} for y in (2023, 2024, 2025)]}
        return build_metrics(panel, {"stocks": [{"code": "000001", "listed_shares_exact": 100}]},
                             interim or {}, store, as_of)["metrics"]["000001"]

    def test_latest_report_required_without_vendor_fallback(self):
        store = MemoryReports({(2025, "11011"): {("000001", "CFS"): report("2025-12-31")}})
        result = self.build(store)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["quality_reasons"], ["stale_report"])
        self.assertIsNone(result["roe_pct"])

    def test_complete_quarterly_bs_is_works_without_cf_collection_success(self):
        store = MemoryReports({(2025, "11011"): {("000001", "CFS"): report("2025-12-31")},
            (2025, "11014"): {("000001", "CFS"): report("2025-09-30")},
            (2026, "11014"): {("000001", "CFS"): report("2026-09-30", previous={})}})
        result = self.build(store)
        self.assertTrue(result["eligible"])
        self.assertAlmostEqual(result["roe_pct"], 100 / 900 * 100, places=4)
        self.assertEqual(result["share_count_basis"], "exact")

    def test_incompatible_api_basis_and_entity_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api.json.gz"
            path.write_bytes(gzip.compress(json.dumps({"records_by_ticker": {"000001": {
                "response_status": "000", "request_parameters": {"fs_div": "OFS", "corp_code": "00000001",
                    "bsns_year": "2026", "reprt_code": "11014"}, "rows": []}}}).encode()))
            self.assertIsNone(RawReports(directory).api("api.json.gz", "000001", "CFS", "2026-09-30", "00000001"))

    def test_hyosung_real_data_regression(self):
        payload = json.loads((ROOT / "data/valuation_metrics.json").read_text(encoding="utf-8"))
        result = payload["metrics"]["298000"]
        self.assertFalse(result["eligible"])
        self.assertAlmostEqual(result["roe_pct"], -2.3264, places=4)
        self.assertEqual(result["period_start"], "2025-10-01")
        self.assertEqual(result["period_end"], "2026-09-30")
        self.assertIn("recent_capital_impairment", result["quality_reasons"])
        self.assertIn("continuing_loss", result["quality_reasons"])


if __name__ == "__main__":
    unittest.main()
