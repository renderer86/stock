import io
import unittest
import zipfile
from unittest.mock import patch

import requests

from crawler_dart_financial_panel import (
    corp_code_map_from_existing_panel,
    fetch_corp_code_map,
)


class _ZipResponse:
    status_code = 200

    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _RetrySession:
    def __init__(self, response: _ZipResponse) -> None:
        self.response = response
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls < 3:
            raise requests.ConnectionError("temporary failure")
        return self.response


def _corp_code_zip() -> bytes:
    xml = (
        "<result><list><corp_code>00126380</corp_code>"
        "<corp_name>삼성전자</corp_name><stock_code>005930</stock_code>"
        "<modify_date>20260101</modify_date></list></result>"
    ).encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("CORPCODE.xml", xml)
    return output.getvalue()


class DartFinancialPanelTest(unittest.TestCase):
    def test_corp_code_download_retries_transient_network_errors(self) -> None:
        session = _RetrySession(_ZipResponse(_corp_code_zip()))
        with patch("crawler_dart_financial_panel.time.sleep"):
            mapping = fetch_corp_code_map(session, "hidden-key")
        self.assertEqual(session.calls, 3)
        self.assertEqual(mapping["005930"]["corp_code"], "00126380")

    def test_existing_panel_recovers_corp_code_mapping(self) -> None:
        mapping = corp_code_map_from_existing_panel(
            {
                "observations": [
                    {
                        "ticker": "005930",
                        "company": "삼성전자",
                        "corp_code": "00126380",
                        "fiscal_year": 2025,
                    },
                    {
                        "ticker": "005930",
                        "company": "삼성전자",
                        "corp_code": "00126380",
                        "fiscal_year": 2024,
                    },
                    {"ticker": "ETF", "corp_code": ""},
                ]
            }
        )
        self.assertEqual(list(mapping), ["005930"])
        self.assertEqual(mapping["005930"]["corp_name"], "삼성전자")


if __name__ == "__main__":
    unittest.main()
