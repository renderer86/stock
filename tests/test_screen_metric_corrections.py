import unittest
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from collector_common import atomic_write_json

from crawler_dart_financial_bulk import calculation_rows_from_raw_groups, validate_bulk_accounts
from crawler_dart_financial_details import company_screening_features, derive_company_metrics, standardize_accounts
from crawler_dart_financial_interim import latest_due_period, parse_interim
from financial_engine import InvestmentScreenBuilder
from financial_engine.interim import ttm_cashflow
from stock_codes import normalize_stock_code


class ScreenMetricCorrectionTests(unittest.TestCase):
    def test_atomic_json_retries_transient_windows_file_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text('{"old":true}', encoding="utf-8")
            locked = PermissionError("file temporarily in use")
            locked.winerror = 32
            replace = os.replace
            attempts = []
            def replace_once(source, destination):
                attempts.append(1)
                if len(attempts) == 1:
                    raise locked
                replace(source, destination)
            with patch("collector_common.os.replace", side_effect=replace_once), patch("collector_common.time.sleep"):
                atomic_write_json(path, {"new": True})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"new": True})
            self.assertEqual(len(attempts), 2)

    def test_failed_atomic_write_preserves_existing_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text('{"old":true}', encoding="utf-8")
            with patch("collector_common.os.replace", side_effect=PermissionError("denied")):
                with self.assertRaises(PermissionError):
                    atomic_write_json(path, {"new": True})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"old": True})
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_alphanumeric_spac_never_collides_with_insurer(self):
        self.assertEqual(normalize_stock_code("[0054V0]"), "0054V0")
        self.assertEqual(normalize_stock_code("[000540]"), "000540")
        self.assertEqual(normalize_stock_code("540"), "000540")
        self.assertEqual(normalize_stock_code("1234567"), "")
        self.assertEqual(normalize_stock_code("name 000540"), "")
        header = [""] * 12 + ["당기"]
        rows = []
        for code, company, amount in (("[0054V0]", "SPAC", "12938305010"), ("[000540]", "Insurer", "12502141000000")):
            rows.append(["별도", code, company] + [""] * 7 + ["ifrs-full_Assets", "자산총계", amount])
        grouped, _ = calculation_rows_from_raw_groups({("OFS", "0"): {"header": header, "rows": rows}}, "BS")
        self.assertEqual(standardize_accounts(grouped[("000540", "OFS")])[0]["assets"], 12502141000000)
        self.assertEqual(standardize_accounts(grouped[("0054V0", "OFS")])[0]["assets"], 12938305010)

    def test_large_api_disagreement_blocks_calculation_on_same_basis(self):
        row = {"ticker": "000540", "detail_source": "api", "detail_basis": "OFS", "detail_accounts": {"assets": 12502141000000}}
        result = validate_bulk_accounts(row, "OFS", {"assets": 12938305010})
        self.assertTrue(result["calculation_blocked"])
        self.assertIn("assets", result["material_mismatch_fields"])
        self.assertIsNone(validate_bulk_accounts(row, "CFS", {"assets": 100}))

    def test_cash_retained_average_capital_does_not_explode(self):
        rows = []
        for year, equity in ((2024, 90), (2025, 100)):
            rows.append({"fiscal_year": year, "detail_accounts": {"equity": equity, "short_term_borrowings": 10, "cash": equity + 9, "operating_income": 20, "pretax_income": 20, "income_tax_expense": 0}})
        derive_company_metrics(rows)
        self.assertIsNone(rows[0]["detail_metrics"]["screening_roic_pct"])
        self.assertEqual(rows[-1]["detail_metrics"]["roic_pct"], 2000)
        self.assertAlmostEqual(rows[-1]["detail_metrics"]["screening_roic_pct"], 20 / 105 * 100, places=4)
        rows[0]["fiscal_year"] = 2023
        derive_company_metrics(rows)
        self.assertIsNone(rows[-1]["detail_metrics"]["screening_roic_pct"])

    def test_nine_observed_successes_satisfy_nine_of_ten_without_imputing_unknown(self):
        rows = [{"ticker": "000001", "fiscal_year": y, "detail_status": "complete", "detail_metrics": {"screening_roic_pct": None if y == 2016 else 20}} for y in range(2016, 2026)]
        result = company_screening_features(rows)["buffett"]
        self.assertEqual(result["persistence_pass_years"], 9)
        self.assertTrue(result["conditions"]["persistence_9_of_10"])
        rows[-1]["detail_metrics"]["screening_roic_pct"] = 5
        self.assertIsNone(company_screening_features(rows)["buffett"]["conditions"]["persistence_9_of_10"])

    def test_real_lease_tax_and_capex_ids_are_included(self):
        raw = []
        for statement, account, name, amount in (
            ("BS", "ifrs-full_Equity", "자본총계", 100),
            ("BS", "ifrs-full_CurrentLeaseLiabilities", "리스부채", 7),
            ("BS", "ifrs-full_NoncurrentLeaseLiabilities", "장기리스부채", 3),
            ("IS", "dart_OperatingIncomeLoss", "영업이익", 50),
            ("IS", "ifrs-full_ProfitLossBeforeTax", "세전이익", 100),
            ("IS", "ifrs-full_IncomeTaxExpense", "법인세비용", 60),
            ("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름", 100),
            ("CF", "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "유형자산의 취득", 10),
            ("CF", "ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities", "무형자산의 취득", 5),
            ("CF", "dart_PaymentsOfFinanceLeaseLiabilitiesClassifiedAsFinancingActivities", "리스부채의 상환", 20),
        ):
            raw.append({"sj_div": statement, "account_id": account, "account_nm": name, "thstrm_amount": str(amount)})
        accounts, _ = standardize_accounts(raw)
        row = {"fiscal_year": 2025, "detail_accounts": accounts}
        derive_company_metrics([row])
        self.assertEqual(row["detail_metrics"]["interest_bearing_debt"], 10)
        self.assertEqual(row["detail_metrics"]["nopat"], 20)
        self.assertEqual(row["detail_metrics"]["free_cash_flow"], 85)
        self.assertEqual(row["detail_metrics"]["free_cash_flow_after_leases"], 65)

    def test_financial_fcf_is_unavailable_even_with_legacy_cached_values(self):
        rows = [{"ticker": "000540", "fiscal_year": y, "is_financial": True, "metrics": {"roe_pct": 15}, "detail_status": "complete", "detail_metrics": {"free_cash_flow": 1e12, "free_cash_flow_after_leases": 1e12, "net_income": 1e10}, "detail_accounts": {}} for y in (2023, 2024, 2025)]
        feature = company_screening_features(rows, {"market_cap_krw": 1e11})
        self.assertIsNone(feature["buffett"]["valuation"]["fcf_yield_pct"])
        self.assertIsNone(feature["buffett"]["conditions"]["fcf_conversion_ge_0_8"])
        feature["buffett"]["valuation"].update({"normalized_annual_fcf": 1e12, "valuation_fcf": 1e12, "fcf_yield_pct": 1000})
        result = InvestmentScreenBuilder().build({"observations": rows, "screening_features": {"000540": feature}}, {"estimates": {}}, {"stocks": [{"code": "000540", "market_cap_krw_100m": 1000}]})
        buffett = result["results"]["000540"]["buffett"]
        self.assertIsNone(buffett["valuation"]["fcf_yield_pct"])
        self.assertNotIn("탁월한 FCF 전환", buffett["strength_tags"])
        self.assertNotIn("순현금·높은 FCF 수익률", buffett["strength_tags"])

    def test_mismatched_sources_cannot_pass_either_screen(self):
        rows = [{"ticker": "000001", "fiscal_year": y, "detail_metrics": {"screening_roic_pct": 20}, "detail_validation": {"calculation_blocked": y == 2025}} for y in (2023, 2024, 2025)]
        feature = {"buffett": {"conditions": {"positive_net_income_all_10y": True}, "valuation": {"fcf_yield_ge_5pct": True, "cash_to_market_cap_le_50pct_or_financial": True}}, "quality": {"conditions": {"a": True}}}
        result = InvestmentScreenBuilder().build({"observations": rows, "screening_features": {"000001": feature}}, {"estimates": {}})
        self.assertEqual(result["results"]["000001"]["buffett"]["watchlist_status"], "pending")
        self.assertFalse(result["results"]["000001"]["buffett"]["candidate"])
        self.assertFalse(result["results"]["000001"]["quality"]["eligible_for_basket"])

    def test_golfzon_ttm_uses_half_year_comparatives_and_lease_payments(self):
        annual = {"corp_code": "01067516", "fiscal_year": 2025, "detail_basis": "CFS", "detail_accounts": {"operating_cash_flow": 95437197990, "capex_ppe": 26331593754, "capex_intangibles": 5167666635, "lease_principal_paid": 16171157054}}
        current = {"operating_cash_flow": 28409824706, "capex_ppe": 4329407756, "capex_intangibles": 1749240193, "lease_principal_paid": 7176148305}
        previous = {"operating_cash_flow": 51558084585, "capex_ppe": 10786440150, "capex_intangibles": 2617131253, "lease_principal_paid": 8360520468}
        interim = {"corp_code": "01067516", "fiscal_year": 2026, "basis": "CFS", "status": "ok", "current": current, "previous": previous, "period_end": "2026-06-30"}
        result = ttm_cashflow(annual, interim)
        self.assertEqual(result["valuation_fcf"], 33127816285)
        self.assertEqual(result["ttm_fcf_before_leases"], 48114601176)
        self.assertIsNone(ttm_cashflow(annual, {**interim, "basis": "OFS"}))
        self.assertIsNone(ttm_cashflow(annual, {**interim, "fiscal_year": 2025}))
        self.assertIsNone(ttm_cashflow(annual, {**interim, "previous": {}}))

    def test_interim_uses_cumulative_income_instead_of_single_quarter(self):
        rows = [{"corp_code": "01067516", "currency": "KRW", "bsns_year": "2026", "reprt_code": "11012", "rcept_no": "20260814003624", "sj_div": "CIS", "account_id": "dart_OperatingIncomeLoss", "account_nm": "영업이익", "thstrm_amount": "66", "thstrm_add_amount": "207", "frmtrm_q_amount": "198", "frmtrm_add_amount": "465"}]
        result = parse_interim(rows, ticker="215000", corp_code="01067516", year=2026, report_code="11012", basis="CFS", period_end="2026-06-30")
        self.assertAlmostEqual(result["operating_income_yoy_pct"], (207 / 465 - 1) * 100, places=4)
        self.assertEqual(latest_due_period(date(2026, 10, 25)), (2026, "11012", "2026-06-30"))


if __name__ == "__main__":
    unittest.main()
