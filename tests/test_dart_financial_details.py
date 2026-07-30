import unittest

from crawler_dart_financial_details import (
    company_screening_features,
    derive_row_metrics,
    parse_dividend_report,
    parse_stock_total,
    standardize_accounts,
)


class DartFinancialDetailsTest(unittest.TestCase):
    def test_standardizes_accounts_and_calculates_roic_fcf(self) -> None:
        raw = [
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
            {
                "sj_div": "BS",
                "account_id": "ifrs-full_CashAndCashEquivalents",
                "account_nm": "현금및현금성자산",
                "thstrm_amount": "50",
            },
            {
                "sj_div": "BS",
                "account_id": "dart_ShortTermBorrowings",
                "account_nm": "단기차입금",
                "thstrm_amount": "100",
            },
            {
                "sj_div": "IS",
                "account_id": "ifrs-full_Revenue",
                "account_nm": "매출액",
                "thstrm_amount": "1,000",
            },
            {
                "sj_div": "IS",
                "account_id": "ifrs-full_CostOfSales",
                "account_nm": "매출원가",
                "thstrm_amount": "600",
            },
            {
                "sj_div": "IS",
                "account_id": "dart_OperatingIncomeLoss",
                "account_nm": "영업이익",
                "thstrm_amount": "200",
            },
            {
                "sj_div": "IS",
                "account_id": "ifrs-full_ProfitLoss",
                "account_nm": "당기순이익",
                "thstrm_amount": "150",
            },
            {
                "sj_div": "IS",
                "account_id": "ifrs-full_ProfitLossBeforeTax",
                "account_nm": "법인세비용차감전순이익",
                "thstrm_amount": "250",
            },
            {
                "sj_div": "IS",
                "account_id": "ifrs-full_IncomeTaxExpense",
                "account_nm": "법인세비용",
                "thstrm_amount": "50",
            },
            {
                "sj_div": "CF",
                "account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities",
                "account_nm": "영업활동현금흐름",
                "thstrm_amount": "180",
            },
            {
                "sj_div": "CF",
                "account_id": "ifrs-full_PurchaseOfPropertyPlantAndEquipment",
                "account_nm": "유형자산의 취득",
                "thstrm_amount": "-50",
            },
            {
                "sj_div": "CF",
                "account_id": "ifrs-full_PurchaseOfIntangibleAssets",
                "account_nm": "무형자산의 취득",
                "thstrm_amount": "-10",
            },
        ]
        values, matches = standardize_accounts(raw)
        self.assertEqual(values["gross_profit"], 400)
        self.assertEqual(matches["gross_profit"]["match"], "derived")

        row = {"detail_accounts": values}
        derive_row_metrics(row)
        metrics = row["detail_metrics"]
        self.assertEqual(metrics["nopat"], 160)
        self.assertEqual(metrics["invested_capital"], 550)
        self.assertAlmostEqual(metrics["roic_pct"], 29.0909, places=4)
        self.assertEqual(metrics["free_cash_flow"], 120)
        self.assertEqual(metrics["gross_profit_to_assets_pct"], 40)

    def test_share_dividend_parsing_and_complete_screen(self) -> None:
        shares = parse_stock_total(
            [
                {
                    "se": "보통주",
                    "istc_totqy": "900",
                    "tesstk_co": "10",
                    "distb_stock_co": "890",
                    "stlm_dt": "2025-12-31",
                },
                {
                    "se": "우선주",
                    "istc_totqy": "100",
                    "tesstk_co": "0",
                    "distb_stock_co": "100",
                    "stlm_dt": "2025-12-31",
                },
                {
                    "se": "합계",
                    "istc_totqy": "1,000",
                    "tesstk_co": "10",
                    "distb_stock_co": "990",
                    "stlm_dt": "2025-12-31",
                },
            ]
        )
        self.assertEqual(shares["issued_shares"], 1000)
        self.assertEqual(shares["distributed_shares"], 990)

        dividend = parse_dividend_report(
            [
                {
                    "se": "현금배당금총액(백만원)",
                    "stock_knd": "-",
                    "thstrm": "500",
                },
                {
                    "se": "주당 현금배당금(원)",
                    "stock_knd": "보통주",
                    "thstrm": "100",
                },
            ]
        )
        self.assertTrue(dividend["has_cash_dividend"])
        self.assertEqual(dividend["cash_dividend_total_reported"], 500)

        rows = []
        for index, year in enumerate(range(2016, 2026)):
            rows.append(
                {
                    "ticker": "000001",
                    "company": "테스트",
                    "fiscal_year": year,
                    "is_financial": False,
                    "detail_status": "complete",
                    "metrics": {"roe_pct": 15, "roa_pct": 5 + index},
                    "detail_metrics": {
                        "roic_pct": 15,
                        "net_income": 100,
                        "gross_margin_pct": 40 + index * 0.1,
                        "free_cash_flow": 100,
                        "net_debt": -10,
                        "net_debt_to_ebitda": -0.1,
                        "nopat": 100 + index * 4,
                        "invested_capital": 500 + index * 20,
                        "dividends_paid": 50,
                        "treasury_stock_purchases": 0,
                        "gross_profit_to_assets_pct": 20,
                        "roa_pct": 5 + index,
                        "basic_eps": 10 + index,
                        "debt_to_equity_pct": 50,
                        "operating_cash_flow": 120,
                        "long_term_debt_to_assets": 0.20 - index * 0.01,
                        "current_ratio": 1 + index * 0.1,
                        "asset_turnover": 1 + index * 0.1,
                    },
                    "share_data": {"issued_shares": 1000 - index},
                    "dividend_data": {"has_cash_dividend": True},
                }
            )

        features = company_screening_features(rows)
        self.assertTrue(features["buffett"]["pass"])
        self.assertEqual(
            features["quality"]["piotroski"]["score_partial"],
            9,
        )
        self.assertTrue(
            features["quality"]["piotroski"]["score_complete"]
        )


if __name__ == "__main__":
    unittest.main()
