import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from crawler_dart_financial_bulk import (
    merge_bulk_year,
    parse_bulk_archive,
    parse_bulk_listing,
)
from crawler_dart_financial_details import standardize_accounts
from dart_financial_storage import load_financial_panel, save_financial_panel


def make_bulk_zip(*, consolidated: bool, rows: list[list[str]]) -> bytes:
    header = [
        "재무제표종류",
        "종목코드",
        "회사명",
        "시장구분",
        "업종",
        "업종명",
        "결산월",
        "결산기준일",
        "보고서종류",
        "통화",
        "항목코드",
        "항목명",
        "당기",
        "전기",
        "전전기",
    ]
    text = "\n".join("\t".join(row) for row in [header, *rows])
    output = io.BytesIO()
    filename = "재무상태표_연결.txt" if consolidated else "재무상태표.txt"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, text.encode("cp949"))
    return output.getvalue()


def bulk_row(statement_name: str, account_id: str, account_name: str, amount: str):
    return [
        statement_name,
        "[005930]",
        "삼성전자",
        "유가증권시장",
        "1",
        "전자",
        "12",
        "2025-12-31",
        "사업보고서",
        "KRW",
        account_id,
        account_name,
        amount,
        "0",
        "0",
    ]


class DartFinancialBulkTest(unittest.TestCase):
    def test_listing_and_cp949_archive_parser(self) -> None:
        listing = parse_bulk_listing(
            "onclick=\"download_ext002('2025','FY', 'BS', "
            "'2025_4Q_BS_stamp.zip'); return false;\""
        )
        self.assertEqual(listing[(2025, "BS")], "2025_4Q_BS_stamp.zip")

        archive = make_bulk_zip(
            consolidated=True,
            rows=[
                bulk_row(
                    "재무상태표, 유동/비유동법-연결재무제표",
                    "ifrs_Assets",
                    "자산총계",
                    "1,000",
                )
            ],
        )
        grouped, summary = parse_bulk_archive(archive, "BS")
        self.assertEqual(summary["row_count"], 1)
        self.assertEqual(
            grouped[("005930", "CFS")][0]["thstrm_amount"],
            "1,000",
        )
        standardized, _ = standardize_accounts(grouped[("005930", "CFS")])
        self.assertEqual(standardized["assets"], 1000)

    def test_bulk_merge_prefers_consolidated_and_keeps_api_fallback(self) -> None:
        observations = [
            {
                "ticker": "005930",
                "fiscal_year": 2025,
                "detail_status": "complete",
                "detail_accounts": {"cash": 100},
            }
        ]
        grouped = {
            ("005930", "CFS"): [
                {
                    "sj_div": "BS",
                    "account_id": "ifrs-full_Assets",
                    "account_nm": "자산총계",
                    "thstrm_amount": "1,000",
                },
                {
                    "sj_div": "BS",
                    "account_id": "ifrs-full_Equity",
                    "account_nm": "자본총계",
                    "thstrm_amount": "500",
                },
            ],
            ("005930", "OFS"): [
                {
                    "sj_div": "BS",
                    "account_id": "ifrs-full_Assets",
                    "account_nm": "자산총계",
                    "thstrm_amount": "900",
                }
            ],
        }
        result = merge_bulk_year(
            observations,
            2025,
            grouped,
            ["2025_BS.zip"],
        )
        row = observations[0]
        self.assertEqual(result["complete"], 1)
        self.assertEqual(row["detail_basis"], "CFS")
        self.assertEqual(row["detail_source"], "bulk_zip+fallback")
        self.assertEqual(row["detail_accounts"]["assets"], 1000)
        self.assertEqual(row["detail_accounts"]["cash"], 100)
        self.assertEqual(row["detail_crosscheck"]["overlap_count"], 0)

    def test_year_sharded_panel_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            panel_path = Path(temporary_directory) / "panel.json"
            panel = {
                "schema_version": 1,
                "period": {"start_year": 2024, "end_year": 2025},
                "observations": [
                    {"ticker": "000001", "fiscal_year": 2024},
                    {"ticker": "000001", "fiscal_year": 2025},
                ],
            }
            save_financial_panel(panel_path, panel)
            index = panel_path.read_text(encoding="utf-8")
            self.assertIn('"mode":"year_shards"', index)
            self.assertNotIn('"observations"', index)
            loaded = load_financial_panel(panel_path)
            self.assertEqual(len(loaded["observations"]), 2)
            self.assertEqual(
                {row["fiscal_year"] for row in loaded["observations"]},
                {2024, 2025},
            )


if __name__ == "__main__":
    unittest.main()
