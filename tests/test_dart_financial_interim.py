import copy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crawler_dart_financial_bulk import parse_bulk_listing
from crawler_dart_financial_interim import (
    BatchStopped, BudgetSession, apply_bulk_reports, apply_report,
    collect_batch, collect_targets, main, parse_args, plan_queue, recover_foreign_currency_reports,
)
from dart_financial_quarterly_bulk import bulk_gap_reasons, quarterly_calculation_rows
from dart_financial_raw_storage import ApiRawAccumulator, read_gzip_json


NOW = datetime.now(timezone.utc)
END = "2026-09-30"


def targets(*codes):
    return {t: {"ticker": t, "corp_code": t.zfill(8), "company": t, "preferred_basis": "CFS", "is_financial": False} for t in codes}


def rows(ticker="000001"):
    result = []
    for statement, account, amount in [
        ("BS", "ifrs-full_Assets", "1000"),
        ("BS", "ifrs-full_Equity", "500"),
        ("IS", "ifrs-full_ProfitLoss", "100"),
        ("IS", "dart_OperatingIncomeLoss", "150"),
        ("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "300"),
        ("CF", "ifrs-full_PurchaseOfPropertyPlantAndEquipment", "50"),
        ("CF", "ifrs-full_PurchaseOfIntangibleAssets", "20"),
        ("CF", "ifrs-full_PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities", "10"),
    ]:
        result.append({"sj_div": statement, "account_id": account, "account_nm": account, "thstrm_amount": amount, "thstrm_add_amount": amount, "frmtrm_q_amount": amount, "frmtrm_add_amount": "100", "corp_code": ticker.zfill(8), "currency": "KRW", "bsns_year": "2026", "reprt_code": "11014", "rcept_no": "20261113000001"})
    return result


class Response:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class Session:
    def __init__(self, replies=None):
        self.calls = []
        self.replies = list(replies or [])

    def get(self, url, **kwargs):
        self.calls.append(kwargs)
        if self.replies:
            reply = self.replies.pop(0)
            if isinstance(reply, BaseException):
                raise reply
            return Response(reply)
        ticker = kwargs["params"]["corp_code"][-6:]
        return Response({"status": "000", "list": rows(ticker)})


def options(*extra):
    args = parse_args(["--year", "2026", "--quarter", "3", "--delay", "0", *extra])
    args.api_key = "secret-never-store"
    return args


class QuarterlyParsingTests(unittest.TestCase):
    def test_comprehensive_income_statement_is_valid_income_coverage(self):
        report = {"available_statements": ["BS", "CIS", "CF"], "accounts": {"assets": 1, "equity": 1, "net_income": 1}}
        self.assertEqual(bulk_gap_reasons(report, is_financial=True), [])

    def test_listing_selects_requested_quarter_and_preserves_annual_default(self):
        html = " ".join(f"download_ext002('2026','{period}', 'BS', '{period}.zip')" for period in ("FY", "FQ", "HY", "TQ"))
        self.assertEqual(parse_bulk_listing(html), {(2026, "BS"): "FY.zip"})
        self.assertEqual(parse_bulk_listing(html, "TQ"), {(2026, "BS"): "TQ.zip"})

    def test_quarterly_headers_distinguish_three_month_income_and_cumulative(self):
        header = ["x"] * 12 + ["당기 3분기 3개월 ", "당기 3분기 누적 ", "전기 3분기 3개월 ", "전기 3분기 누적 ", "전기", "전전기"]
        values = ["손익계산서 - 연결", "[000001]", "name", "market", "1", "industry", "12", END, "3분기보고서", "KRW", "dart_OperatingIncomeLoss", "영업이익", "60", "210", "50", "150", "999", "888"]
        group = {("CFS", "0"): {"tables": [{"header": header, "rows": [values]}]}}
        parsed = quarterly_calculation_rows(group, "PL", year=2026, report_code="11014", period_end=END)
        row = parsed[("000001", "CFS")][0]
        self.assertEqual((row["thstrm_amount"], row["thstrm_add_amount"], row["frmtrm_add_amount"]), ("60", "210", "150"))
        values[9] = "USD"
        self.assertEqual(quarterly_calculation_rows(group, "PL", year=2026, report_code="11014", period_end=END), {})
        values[9], values[7] = "KRW", "2026-06-30"
        self.assertEqual(quarterly_calculation_rows(group, "PL", year=2026, report_code="11014", period_end=END), {})

    def test_cashflow_comparative_is_same_quarter_not_previous_full_year(self):
        header = ["x"] * 12 + ["당기3분기", "전기3분기", "전기", "전전기"]
        values = ["현금흐름표 - 연결", "[000001]", "name", "market", "1", "industry", "12", END, "3분기보고서", "KRW", "account", "name", "300", "200", "900", "800"]
        group = {("CFS", "0"): {"tables": [{"header": header, "rows": [values]}]}}
        row = quarterly_calculation_rows(group, "CF", year=2026, report_code="11014", period_end=END)[("000001", "CFS")][0]
        self.assertEqual(row["frmtrm_q_amount"], "200")
        header[13] = "전기말"
        row = quarterly_calculation_rows(group, "CF", year=2026, report_code="11014", period_end=END)[("000001", "CFS")][0]
        self.assertIsNone(row["frmtrm_q_amount"])

    def test_bulk_complete_reports_are_excluded_from_api_and_partial_reports_are_queued(self):
        ts = targets("000001", "000002")
        state, payload = {}, {"companies": {}}
        grouped = {("000001", "CFS"): rows(), ("000002", "CFS"): rows("000002")[:2]}
        result = apply_bulk_reports(ts, state, payload, grouped, {}, {"CF": "current.zip"}, year=2026, report_code="11014", end=END)
        self.assertEqual(result, {"imported": 1, "partial": 1})
        self.assertEqual(state["000001"]["current"]["operating_cash_flow"], 300)
        self.assertEqual(state["000001"]["previous"]["operating_cash_flow"], 300)
        self.assertEqual(plan_queue(ts, state, payload, END, NOW, options("--force")), ["000002"])
        self.assertNotIn("000002", payload["companies"])

    def test_same_zip_does_not_overwrite_api_supplement_or_its_failure_cooldown(self):
        ts = targets("000001", "000002")
        state = {"000001": {"status": "ok", "source": "api", "bulk_fingerprint": "current.zip"}, "000002": {**ts["000002"], "status": "no_data", "attempted_at_utc": NOW.isoformat(), "bulk_fingerprint": "current.zip"}}
        before = copy.deepcopy(state)
        apply_bulk_reports(ts, state, {}, {("000001", "CFS"): rows(), ("000002", "CFS"): rows("000002")[:2]}, {}, {"CF": "current.zip"}, year=2026, report_code="11014", end=END)
        self.assertEqual(state, before)


class ResumableBatchTests(unittest.TestCase):
    def run_batch(self, ts, state, payload, args, transport, root):
        raw = ApiRawAccumulator(root / "raw")
        session = BudgetSession(transport, args)
        queue = plan_queue(ts, state, payload, END, NOW, args)
        snapshots = []

        def checkpoint():
            raw.flush()
            snapshots.append(copy.deepcopy(state))

        result = collect_batch(ts, queue, state, payload, year=2026, report_code="11014", end=END, args=args, session=session, raw=raw, checkpoint=checkpoint)
        return result, snapshots

    def test_company_budget_resumes_without_refetching_success_and_preserves_raw(self):
        ts, state, payload = targets("000001", "000002", "000003"), {}, {"companies": {}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = Session()
            result, checkpoints = self.run_batch(ts, state, payload, options("--max-companies", "2"), first, root)
            self.assertEqual(result["stop_reason"], "company_budget")
            self.assertEqual(len(checkpoints[-1]), 2)
            second = Session()
            self.run_batch(ts, state, payload, options("--max-companies", "2"), second, root)
            self.assertEqual(len(second.calls), 1)
            self.assertEqual(len(payload["companies"]), 3)
            raw_path = root / state["000001"]["raw_ref"]
            record = read_gzip_json(raw_path)["records_by_ticker"]["000001"]
            self.assertEqual(record["rows"], rows())
            self.assertNotIn("secret-never-store", json.dumps(record))

    def test_request_cap_resumes_at_fallback_basis(self):
        ts, state, payload = targets("000001"), {}, {"companies": {}}
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self.run_batch(ts, state, payload, options("--max-requests", "1"), Session([{"status": "013"}]), Path(directory))
            self.assertEqual(result["request_count"], 1)
            self.assertEqual(result["stop_reason"], "request_budget")
            self.assertEqual(state["000001"]["next_basis"], "OFS")
            second = Session()
            self.run_batch(ts, state, payload, options(), second, Path(directory))
            self.assertEqual(second.calls[0]["params"]["fs_div"], "OFS")
            self.assertEqual(payload["companies"]["000001"]["basis"], "OFS")

    def test_quota_stop_keeps_prior_report_and_checkpoints(self):
        ts, state = targets("000001", "000002"), {}
        payload = {"companies": {"000001": {"period_end": "2026-06-30"}}}
        with tempfile.TemporaryDirectory() as directory:
            result, saved = self.run_batch(ts, state, payload, options(), Session([{"status": "020"}]), Path(directory))
        self.assertEqual(result["stop_reason"], "dart_020")
        self.assertEqual(result["request_count"], 1)
        self.assertEqual(saved[-1]["000001"]["status"], "error")
        self.assertEqual(payload["companies"]["000001"]["period_end"], "2026-06-30")

    def test_foreign_currency_raw_is_preserved_without_krw_calculation(self):
        ts, state, payload = targets("000001"), {}, {"companies": {}}
        foreign_rows = [{**row, "currency": "USD"} for row in rows()]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_batch(ts, state, payload, options(), Session([{"status": "000", "list": foreign_rows}]), root)
            self.assertEqual(state["000001"]["status"], "unsupported_currency")
            self.assertEqual(state["000001"]["currencies"], ["USD"])
            record = read_gzip_json(root / state["000001"]["raw_ref"])["records_by_ticker"]["000001"]
            self.assertEqual(record["rows"], foreign_rows)
            state["000001"].update(status="error", error_type="ValueError")
            recover_foreign_currency_reports(state, root / "raw", 2026, "11014")
            self.assertEqual(state["000001"]["status"], "unsupported_currency")
        self.assertNotIn("000001", payload["companies"])
        self.assertEqual(plan_queue(ts, state, payload, END, datetime.now(timezone.utc), options()), [])

    def test_pending_targets_precede_due_errors_and_stale_successes(self):
        ts = targets("000001", "000002", "000003", "000004")
        state = {"000001": {**ts["000001"], "status": "ok", "fetched_at_utc": (NOW - timedelta(days=10)).isoformat()}, "000002": {**ts["000002"], "status": "error", "attempted_at_utc": (NOW - timedelta(days=2)).isoformat()}, "000004": {**ts["000004"], "status": "no_data", "attempted_at_utc": NOW.isoformat()}}
        self.assertEqual(plan_queue(ts, state, {}, END, NOW, options()), ["000003", "000002", "000001"])

    def test_runtime_limit_prevents_http_and_older_period_does_not_replace_newer(self):
        transport = Session()
        session = BudgetSession(transport, options())
        session.deadline = 0
        with self.assertRaisesRegex(BatchStopped, "runtime_budget"):
            session.get("https://example.test")
        self.assertEqual(transport.calls, [])
        payload = {"companies": {"000001": {"period_end": END}}}
        apply_report(payload, {"ticker": "000001", "period_end": "2026-06-30"})
        self.assertEqual(payload["companies"]["000001"]["period_end"], END)

    def test_all_scope_includes_financials_without_annual_details(self):
        panel = {"observations": [{"ticker": "000001", "corp_code": "00000001", "fiscal_year": 2024, "is_financial": True}]}
        ts, unmapped = collect_targets(panel, {"stocks": [{"code": "000001"}, {"code": "000002"}]}, {}, {}, {"000001": {"corp_code": "00000001"}}, options())
        self.assertTrue(ts["000001"]["is_financial"])
        self.assertEqual(unmapped, ["000002"])

    def test_bulk_only_main_writes_bulk_results_without_authenticated_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panel = root / "panel.json"
            panel.write_text(json.dumps({"observations": [{"ticker": "000001", "corp_code": "00000001", "fiscal_year": 2025}]}), encoding="utf-8")
            args = ["--year", "2026", "--quarter", "3", "--bulk-only", "--panel", str(panel), "--market", str(root / "absent.json"), "--output", str(root / "output.json"), "--progress-dir", str(root / "progress"), "--raw-root", str(root / "raw"), "--corp-codes", str(root / "codes.json")]
            with patch("crawler_dart_financial_interim.load_env_file"), patch.dict("os.environ", {"DART_API_KEY": ""}), patch("crawler_dart_financial_interim.create_session") as factory, patch("crawler_dart_financial_interim.load_quarterly_bulk", return_value=({("000001", "CFS"): rows()}, {}, {"CF": "file.zip"})):
                main(args)
                factory.return_value.get.assert_not_called()
            saved = json.loads((root / "output.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["companies"]["000001"]["source"], "bulk_zip")
            self.assertEqual(saved["coverage"]["ok"], 1)


if __name__ == "__main__":
    unittest.main()
