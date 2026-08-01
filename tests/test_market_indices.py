import unittest

from crawler_market_indices import merge_history, parse_naver_index_history


class MarketIndicesTest(unittest.TestCase):
    def test_naver_history_parses_latest_kospi_session(self) -> None:
        history = parse_naver_index_history(
            """
            [['날짜', '시가', '고가', '저가', '종가', '거래량', '외국인소진율'],
             ['20260730', 5681.77, 5976.82, 5547.41, 5593.56, 378859, 0.0],
             ['20260731', 5657.79, 6630.77, 5629.76, 6595.45, 434445, 0.0]]
            """
        )
        self.assertEqual(history[-1]["date"], "2026-07-31")
        self.assertEqual(history[-1]["close"], 6595.45)

    def test_naver_rows_replace_stale_yahoo_date_and_append_latest(self) -> None:
        merged = merge_history(
            [
                {"date": "2026-07-29", "close": 5663.24},
                {"date": "2026-07-30", "close": 5593.56, "volume": 1},
            ],
            [
                {"date": "2026-07-30", "close": 5593.56, "volume": 378859},
                {"date": "2026-07-31", "close": 6595.45, "volume": 434445},
            ],
        )
        self.assertEqual([row["date"] for row in merged], [
            "2026-07-29",
            "2026-07-30",
            "2026-07-31",
        ])
        self.assertEqual(merged[-2]["volume"], 378859)
        self.assertEqual(merged[-1]["close"], 6595.45)


if __name__ == "__main__":
    unittest.main()
