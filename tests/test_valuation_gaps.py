from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from crawler_valuation_gaps import CAPITAL, INCOME, collect
from dart_financial_raw_storage import read_gzip_json


class ValuationGapTests(unittest.TestCase):
    def test_compared_income_does_not_replace_missing_prior_period_capital(self):
        complete = {field: 100 for field in CAPITAL | INCOME}
        metric = {"financial_ticker": "000001", "fiscal_month": 12, "quality_reasons": ["missing_income"]}
        panel = {"observations": [{"ticker": "000001", "fiscal_year": 2025,
                                  "corp_code": "00000001", "statement_basis": "CFS"}]}

        def saved(store, year, code, *args):
            if (year, code) == (2026, "11014"):
                return {"current": complete, "previous": complete}
            if code == "11011":
                return {"current": complete}
            return {"current": {f: 100 for f in INCOME}}

        rows = [{"corp_code": "00000001", "bsns_year": "2025", "reprt_code": "11014",
                 "currency": "KRW", "sj_div": "BS", "account_id": "ifrs-full_Assets",
                 "account_nm": "자산총계", "thstrm_amount": "200"}]
        response = Mock()
        response.json.return_value = {"status": "000", "list": rows}
        session = Mock()
        session.headers = {}
        session.get.return_value = response
        with tempfile.TemporaryDirectory() as directory, \
                patch("crawler_valuation_gaps.load_financial_panel", return_value=panel), \
                patch("crawler_valuation_gaps.build_metrics", return_value={"metrics": {"000001": metric}}), \
                patch("crawler_valuation_gaps.get_report", side_effect=saved), \
                patch("crawler_valuation_gaps.requests.Session", return_value=session), \
                patch("crawler_valuation_gaps.time.sleep"):
            result = collect(Path(directory), date(2026, 11, 29), "test-secret", max_requests=1)
            session.get.assert_called_once()
            self.assertEqual(session.get.call_args.kwargs["params"]["bsns_year"], "2025")
            self.assertEqual(result["last_run"]["requests"], 1)
            record = result["reports"]["000001:2025:11014:CFS"]
            raw = read_gzip_json(Path(directory) / record["raw_ref"])
            self.assertNotIn("crtfc_key", raw["records_by_ticker"]["000001"]["request_parameters"])
            self.assertEqual(raw["records_by_ticker"]["000001"]["rows"], rows)


if __name__ == "__main__":
    unittest.main()
