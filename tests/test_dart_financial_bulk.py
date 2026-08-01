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
from dart_financial_raw_storage import (
    ApiRawAccumulator,
    load_bulk_raw_statement,
    read_gzip_json,
    write_bulk_raw_shards,
)


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
        grouped, raw_groups, summary = parse_bulk_archive(archive, "BS")
        self.assertEqual(summary["row_count"], 1)
        self.assertEqual(
            grouped[("005930", "CFS")][0]["thstrm_amount"],
            "1,000",
        )
        standardized, _ = standardize_accounts(grouped[("005930", "CFS")])
        self.assertEqual(standardized["assets"], 1000)
        self.assertEqual(
            raw_groups[("CFS", "0")]["tables"][0]["rows"][0][12],
            "1,000",
        )

    def test_archive_keeps_multiple_headers_in_the_same_basis_bucket(self) -> None:
        first = make_bulk_zip(
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
        second_rows = [
            bulk_row(
                "재무상태표, 유동/비유동법-연결재무제표",
                "ifrs_Equity",
                "자본총계",
                "500",
            )
            + ["추가열"]
        ]
        second_header = [
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
            "추가열",
        ]
        combined = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(first)) as first_archive, zipfile.ZipFile(
            combined, "w", zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr(
                "첫번째.txt",
                first_archive.read(first_archive.namelist()[0]),
            )
            archive.writestr(
                "두번째.txt",
                "\n".join(
                    "\t".join(row) for row in [second_header, *second_rows]
                ).encode("cp949"),
            )

        grouped, raw_groups, summary = parse_bulk_archive(combined.getvalue(), "BS")
        self.assertEqual(summary["row_count"], 2)
        self.assertEqual(len(grouped[("005930", "CFS")]), 2)
        self.assertEqual(len(raw_groups[("CFS", "0")]["tables"]), 2)

    def test_bulk_merge_keeps_sources_separate_without_field_fallback(self) -> None:
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
            raw_references={
                "005930": {
                    "CFS": {"BS": "dart_financial_raw/2025/bulk/BS_CFS_0.json.gz"}
                }
            },
        )
        row = observations[0]
        self.assertEqual(result["bulk_partial"], 1)
        self.assertEqual(row["detail_basis"], "CFS")
        self.assertEqual(row["detail_source"], "bulk_zip")
        self.assertEqual(row["detail_accounts"]["assets"], 1000)
        self.assertNotIn("cash", row["detail_accounts"])
        self.assertEqual(row["detail_validation"]["overlap_count"], 0)
        self.assertEqual(
            row["raw_financial_statements"]["CFS"]["BS"],
            "dart_financial_raw/2025/bulk/BS_CFS_0.json.gz",
        )

    def test_raw_bulk_and_api_shards_preserve_source_rows(self) -> None:
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
        _, raw_groups, _ = parse_bulk_archive(archive, "BS")
        with tempfile.TemporaryDirectory() as temporary_directory:
            raw_root = Path(temporary_directory) / "dart_financial_raw"
            entries, references = write_bulk_raw_shards(
                raw_root,
                year=2025,
                statement="BS",
                source_file="2025_BS.zip",
                raw_groups=raw_groups,
            )
            self.assertEqual(len(entries), 1)
            bulk_path = raw_root.parent / references["005930"]["CFS"]["BS"]
            bulk_payload = read_gzip_json(bulk_path)
            self.assertEqual(
                bulk_payload["tables"][0]["rows"][0][12],
                "1,000",
            )
            cached = load_bulk_raw_statement(
                raw_root,
                year=2025,
                statement="BS",
                source_file="2025_BS.zip",
            )
            self.assertIsNotNone(cached)
            cached_groups, cached_references, _ = cached
            self.assertEqual(
                cached_groups[("CFS", "0")]["tables"][0]["rows"][0][12],
                "1,000",
            )
            self.assertEqual(cached_references, references)

            accumulator = ApiRawAccumulator(raw_root)
            api_reference = accumulator.add(
                year=2025,
                dataset="stock_total",
                ticker="005930",
                corp_code="00126380",
                endpoint="https://example.test/stock.json",
                request_parameters={"corp_code": "00126380"},
                response_status="000",
                rows=[{"istc_totqy": "100"}],
            )
            accumulator.flush()
            api_payload = read_gzip_json(raw_root.parent / api_reference)
            self.assertEqual(
                api_payload["records_by_ticker"]["005930"]["rows"][0][
                    "istc_totqy"
                ],
                "100",
            )

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
