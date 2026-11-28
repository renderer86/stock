from __future__ import annotations

from datetime import date
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from build_valuation_metrics import RawReports, build_metrics, company_due_period, parse_report, report_period_end, standardized
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

    def test_sce_parent_aggregate_uses_ytd_and_excludes_retained_earnings(self):
        rows = [
            {"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "thstrm_amount": "40", "thstrm_add_amount": "120", "frmtrm_add_amount": "90"},
            {"sj_div": "SCE", "account_id": "ifrs-full_ProfitLoss", "account_detail": "연결재무제표 [member]", "thstrm_amount": "40", "frmtrm_q_amount": "30"},
            {"sj_div": "SCE", "account_id": "ifrs-full_ProfitLoss", "account_detail": "자본 [구성요소]|지배기업의 소유주에게 귀속되는 지분 [구성요소]|이익잉여금 [구성요소]", "thstrm_amount": "99", "frmtrm_q_amount": "69"},
            {"sj_div": "SCE", "account_id": "ifrs-full_ProfitLoss", "account_detail": "자본 [구성요소]|지배기업의 소유주에게 귀속되는 지분 [구성요소]", "thstrm_amount": "100", "frmtrm_q_amount": "70"},
        ]
        parsed = parse_report(rows, "CFS", "2026-09-30", [])
        self.assertEqual(parsed["current"]["net_income"], 120)
        self.assertEqual(parsed["current"]["owners_net_income"], 100)
        self.assertEqual(parsed["previous"]["owners_net_income"], 70)
        self.assertNotIn("owners_net_income", parse_report(rows[:3], "CFS", "2026-09-30", [])["current"])

    def test_sce_owner_components_require_exact_reconciliation(self):
        rows = [
            {"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "thstrm_amount": "120"},
            {"sj_div": "SCE", "account_id": "ifrs-full_ProfitLoss", "account_detail": "자본|이익잉여금", "thstrm_amount": "100"},
            {"sj_div": "SCE", "account_id": "ifrs-full_ProfitLoss", "account_detail": "자본|비지배지분", "thstrm_amount": "20"},
        ]
        self.assertEqual(standardized(rows, "CFS")["owners_net_income"], 100)
        owner_only = [rows[0], {**rows[1], "thstrm_amount": "120"}]
        self.assertEqual(standardized(owner_only, "CFS")["owners_net_income"], 120)
        self.assertNotIn("owners_net_income", standardized([rows[0], {**rows[1], "thstrm_amount": "119"}], "CFS"))
        unknown = {"sj_div": "SCE", "account_id": "ifrs-full_ProfitLoss", "account_detail": "자본|미확인항목", "thstrm_amount": "5"}
        self.assertNotIn("owners_net_income", standardized([*owner_only, unknown], "CFS"))

    def test_cf_total_profit_repairs_blank_is_total_without_using_operating_cash(self):
        rows = [{"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "thstrm_add_amount": ""},
                {"sj_div": "CF", "account_id": "ifrs-full_ProfitLoss", "account_detail": "-", "thstrm_amount": "120", "frmtrm_q_amount": "90"},
                {"sj_div": "CF", "account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities", "thstrm_amount": "999"}]
        parsed = parse_report(rows, "CFS", "2026-09-30", [])
        self.assertEqual(parsed["current"]["net_income"], 120)
        self.assertEqual(parsed["previous"]["net_income"], 90)

    def test_non_december_calendar_and_ttm_use_actual_fiscal_end(self):
        self.assertEqual(company_due_period(date(2026, 11, 29), 11), (2026, "11014", "2026-08-31"))
        self.assertEqual(company_due_period(date(2026, 11, 29), 6), (2026, "11013", "2026-09-30"))
        self.assertEqual(report_period_end(2026, "11013", 6), "2026-09-30")
        panel = {"observations": [{"ticker": "000001", "fiscal_year": 2025, "corp_code": "00000001",
                  "statement_basis": "CFS", "share_data": {"settlement_date": "2025-11-30"}}]}
        store = MemoryReports({
            (2025, "11011"): {("000001", "CFS"): report("2025-11-30", report_code="11011", fiscal_year=2025)},
            (2025, "11014"): {("000001", "CFS"): report("2025-08-31", report_code="11014", fiscal_year=2025)},
            (2026, "11014"): {("000001", "CFS"): report("2026-08-31", report_code="11014", fiscal_year=2026)},
        })
        result = self.build(store, panel=panel)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["period_end"], "2026-08-31")
        self.assertEqual(result["period_start"], "2025-09-01")
        self.assertEqual(result["required_period_end"], "2026-08-31")
        self.assertAlmostEqual(result["roe_pct"], 100 / 900 * 100, places=4)

    def test_consolidated_profit_and_equity_do_not_replace_parent_amounts(self):
        rows = [{"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "thstrm_amount": "120"}]
        self.assertNotIn("owners_net_income", standardized(rows, "CFS"))
        self.assertEqual(standardized(rows, "OFS")["owners_net_income"], 120)

    def test_reported_minority_profit_reconciles_missing_parent_or_total(self):
        total = {"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "thstrm_amount": "120"}
        parent = {"sj_div": "IS", "account_id": "ifrs-full_ProfitLossAttributableToOwnersOfParent", "thstrm_amount": "100"}
        minority = {"sj_div": "IS", "account_id": "ifrs-full_ProfitLossAttributableToNoncontrollingInterests", "thstrm_amount": "20"}
        self.assertEqual(standardized([total, minority], "CFS")["owners_net_income"], 100)
        result = standardized([parent, minority], "CFS")
        self.assertEqual(result["net_income"], 120)
        self.assertEqual(result["continuing_net_income"], 120)
        self.assertEqual(standardized([total, {**minority, "thstrm_amount": "0"}], "CFS")["owners_net_income"], 120)
        self.assertNotIn("owners_net_income", standardized([total, {**minority, "thstrm_amount": ""}], "CFS"))

    def test_issuer_parent_profit_tag_does_not_select_comprehensive_income(self):
        rows = [
            {"sj_div": "IS", "account_id": "entity00102618_AttributableToOwnersOfParentOfComprehensiveIncome", "thstrm_amount": "99"},
            {"sj_div": "IS", "account_id": "entity00102618_ProfitLossAttributableToOwnersOfParentOfProfitLoss", "thstrm_amount": "100"},
        ]
        self.assertEqual(standardized(rows, "CFS")["owners_net_income"], 100)
        self.assertNotIn("owners_net_income", standardized(rows[:1], "CFS"))

    def test_opaque_issuer_labels_require_explicit_profit_loss_context(self):
        rows = [
            {"sj_div": "IS", "account_id": "entity00761059_udf_IS_202022794045355_ComprehensiveIncome", "account_nm": "지배기업소유주지분", "thstrm_amount": "99"},
            {"sj_div": "IS", "account_id": "entity00761059_udf_IS_202022794045355_ProfitLoss", "account_nm": "지배기업소유주지분", "thstrm_amount": "100"},
            {"sj_div": "IS", "account_id": "entity00761059_udf_IS_20202279404873_ProfitLoss", "account_nm": "비지배지분", "thstrm_amount": "20"},
        ]
        result = standardized(rows, "CFS")
        self.assertEqual(result["owners_net_income"], 100)
        self.assertEqual(result["net_income"], 120)
        self.assertNotIn("owners_net_income", standardized(rows[:1], "CFS"))

    def test_bulk_reader_retains_extension_and_minority_income_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dart_financial_raw/2025/bulk/PL_CFS_0.json.gz"
            path.parent.mkdir(parents=True)
            prefix = ["손익계산서", "[000001]", "테스트", "코스닥", "1", "업종", "12", "2025-12-31", "사업보고서", "KRW"]
            raw = {"basis": "CFS", "tables": [{"header": [*map(str, range(12)), "당기"], "rows": [
                [*prefix, "entity00000001_ProfitLossAttributableToOwnersOfParentOfProfitLoss", "소유주지분", "80"],
                [*prefix, "ifrs-full_ProfitLossAttributableToNoncontrollingInterests", "비지배지분", "20"],
            ]}]}
            path.write_bytes(gzip.compress(json.dumps(raw).encode()))
            result = RawReports(directory).bulk(2025, "11011")[("000001", "CFS")]["current"]
            self.assertEqual(result["owners_net_income"], 80)
            self.assertEqual(result["net_income"], 100)
            self.assertEqual(result["discontinued_net_income"], 0)

    def test_parent_continuing_income_needs_verified_discontinued_result(self):
        rows = [
            {"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "thstrm_amount": "120"},
            {"sj_div": "IS", "account_id": "ifrs-full_IncomeFromContinuingOperationsAttributableToOwnersOfParent", "thstrm_amount": "100"},
        ]
        self.assertEqual(standardized(rows, "CFS")["owners_net_income"], 100)
        discontinued = {"sj_div": "IS", "account_id": "ifrs-full_ProfitLossFromDiscontinuedOperations", "thstrm_amount": "20"}
        self.assertNotIn("owners_net_income", standardized([*rows, discontinued], "CFS"))
        parent_discontinued = {"sj_div": "IS", "account_id": "ifrs-full_IncomeFromDiscontinuedOperationsAttributableToOwnersOfParent", "thstrm_amount": "15"}
        self.assertEqual(standardized([*rows, discontinued, parent_discontinued], "CFS")["owners_net_income"], 115)

    def test_missing_discontinued_amount_is_not_assumed_zero(self):
        rows = [{"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "thstrm_amount": "120"},
                {"sj_div": "IS", "account_id": "ifrs-full_ProfitLossFromDiscontinuedOperations", "thstrm_amount": ""}]
        self.assertNotIn("discontinued_net_income", standardized(rows, "CFS"))
        self.assertEqual(standardized(rows[:1], "CFS")["discontinued_net_income"], 0)

    def test_reported_continuing_profit_reconciles_blank_discontinued_amount(self):
        rows = [{"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "thstrm_amount": "120"},
                {"sj_div": "IS", "account_id": "ifrs-full_ProfitLossFromContinuingOperations", "thstrm_amount": "110"},
                {"sj_div": "IS", "account_id": "ifrs-full_ProfitLossFromDiscontinuedOperations", "thstrm_amount": ""}]
        self.assertEqual(standardized(rows, "CFS")["discontinued_net_income"], 10)

    def test_pretax_less_tax_repairs_missing_total_only_without_discontinued_line(self):
        rows = [{"sj_div": "IS", "account_id": "ifrs-full_ProfitLossBeforeTax", "thstrm_amount": "120"},
                {"sj_div": "IS", "account_id": "ifrs-full_IncomeTaxExpenseContinuingOperations", "thstrm_amount": "20"}]
        self.assertEqual(standardized(rows, "CFS")["net_income"], 100)
        blank = {"sj_div": "IS", "account_id": "ifrs-full_ProfitLossFromDiscontinuedOperations", "thstrm_amount": ""}
        self.assertNotIn("net_income", standardized([*rows, blank], "CFS"))

    def test_ordinal_loss_alias_and_unstandardized_sce_profit(self):
        rows = [{"sj_div": "CIS", "account_id": "-표준계정코드 미사용-", "account_nm": "Ⅸ.분기순손실", "thstrm_amount": "-120"},
                {"sj_div": "SCE", "account_id": "-표준계정코드 미사용-", "account_nm": "분기순손익",
                 "account_detail": "자본 [구성요소]|지배기업의 소유주에게 귀속되는 지분 [구성요소]", "thstrm_amount": "-100"}]
        values = standardized(rows, "CFS")
        self.assertEqual(values["net_income"], -120)
        self.assertEqual(values["owners_net_income"], -100)

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

    def test_all_market_codes_are_evaluated_without_vendor_roe_prefilter(self):
        store = MemoryReports({(2025, "11011"): {("000001", "CFS"): report("2025-12-31")},
            (2025, "11014"): {("000001", "CFS"): report("2025-09-30")},
            (2026, "11014"): {("000001", "CFS"): report("2026-09-30")}})
        panel = {"observations": [{"ticker": "000001", "fiscal_year": 2025, "corp_code": "00000001", "statement_basis": "CFS"}]}
        market = {"stocks": [{"code": "000001", "roe": 1, "listed_shares_exact": 100},
                             {"code": "000002", "roe": -10}, {"code": "000003", "roe": None}]}
        result = build_metrics(panel, market, {}, store, date(2026, 11, 28))
        self.assertEqual(set(result["metrics"]), {"000001", "000002", "000003"})
        self.assertTrue(result["metrics"]["000001"]["eligible"])
        self.assertGreater(result["metrics"]["000001"]["roe_pct"], 10)
        self.assertFalse(result["metrics"]["000002"]["eligible"])

    def test_auxiliary_financials_use_same_basis_dart_ytd_comparatives(self):
        store = MemoryReports({(2025, "11011"): {("000001", "CFS"): report("2025-12-31")},
            (2025, "11014"): {("000001", "CFS"): report("2025-09-30", current=accounts(revenue=100, operating_income=50))},
            (2026, "11014"): {("000001", "CFS"): report("2026-09-30", current=accounts(revenue=150, operating_income=40, liabilities=800), previous={})}})
        data = self.build(store)["financials"]
        self.assertEqual(data["source"], "OpenDART")
        self.assertEqual(data["assets"], 2000)
        self.assertEqual(data["liabilities"], 800)
        self.assertEqual(data["revenue_yoy_pct"], 50)
        self.assertEqual(data["operating_income_yoy_pct"], -20)

    def test_preferred_share_uses_issuer_reports_and_same_total_share_count(self):
        panel = {"observations": [{"ticker": "000010", "fiscal_year": 2025, "corp_code": "00000001", "statement_basis": "CFS"}]}
        store = MemoryReports({(2025, "11011"): {("000010", "CFS"): report("2025-12-31")},
            (2025, "11014"): {("000010", "CFS"): report("2025-09-30")},
            (2026, "11014"): {("000010", "CFS"): report("2026-09-30")}})
        market = {"stocks": [{"code": "000010", "name": "테스트", "listed_shares_exact": 80},
            {"code": "000015", "name": "테스트우", "listed_shares_exact": 20},
            {"code": "00001A", "name": "다른 회사", "listed_shares_exact": 5}]}
        results = build_metrics(panel, market, {}, store, date(2026, 11, 28))["metrics"]
        self.assertEqual(results["000015"]["financial_ticker"], "000010")
        self.assertTrue(results["000015"]["eligible"])
        self.assertEqual(results["000010"]["bps"], 9)
        self.assertEqual(results["000015"]["bps"], 9)
        self.assertFalse(results["00001A"]["eligible"])

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

    def test_pharmaresearch_annual_zip_repairs_ttm_and_eligibility(self):
        payload = json.loads((ROOT / "data/valuation_metrics.json").read_text(encoding="utf-8"))
        result = payload["metrics"]["214450"]
        self.assertTrue(result["eligible"])
        self.assertEqual(result["quality_reasons"], [])
        self.assertEqual(result["owners_net_income"], 165120956459 + 134099083875 - 132550035527)
        self.assertAlmostEqual(result["roe_pct"], 23.139, places=4)
        self.assertAlmostEqual(result["roa_pct"], 16.331, places=4)
        self.assertEqual(result["basis"], "CFS")
        self.assertIn("dart_financial_raw/2025/bulk/PL_CFS_2.json.gz", result["sources"])

    def test_samsung_card_sce_and_hyundai_pharm_fiscal_calendar_regressions(self):
        payload = json.loads((ROOT / "data/valuation_metrics.json").read_text(encoding="utf-8"))
        card = payload["metrics"]["029780"]
        self.assertTrue(card["eligible"])
        self.assertEqual(card["income_inputs"]["annual"]["owners_net_income"], 645923000000)
        self.assertEqual(card["roe_pct"], 6.7375)
        pharma = payload["metrics"]["004310"]
        self.assertTrue(pharma["eligible"])
        self.assertEqual(pharma["period_end"], "2026-08-31")
        self.assertEqual(pharma["income_inputs"]["annual"]["period_end"], "2025-11-30")


if __name__ == "__main__":
    unittest.main()
