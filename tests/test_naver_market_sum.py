import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from crawler_naver_market_sum import MARKETS, fill_preferred_pbr, fund_row, main, stock_row


class NaverMarketSumTest(unittest.TestCase):
    def test_daily_outputs_keep_low_negative_and_missing_vendor_roe(self) -> None:
        stocks = [{"code": "000001", "roe": 1}, {"code": "000002", "roe": -5},
                  {"code": "000003", "roe": None}]
        with tempfile.TemporaryDirectory() as directory:
            full, sorted_output = Path(directory) / "all.json", Path(directory) / "sorted.json"
            with patch("sys.argv", ["crawler_naver_market_sum.py", "--output", str(full), "--roe-output", str(sorted_output)]), patch("crawler_naver_market_sum.crawl_all", return_value=({"KOSPI": 1, "KOSDAQ": 1}, stocks)):
                main()
            for path in (full, sorted_output):
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(payload["count"], 3)
                self.assertEqual({row["code"] for row in payload["stocks"]}, {"000001", "000002", "000003"})

    def test_preferred_pbr_uses_common_stock_bps(self) -> None:
        stocks = [
            {"code": "005930", "current_price": 276000, "pbr": 3.2},
            {"code": "005935", "current_price": 201000, "pbr": None},
            {"code": "02826K", "current_price": 100000, "pbr": None},
        ]
        self.assertEqual(fill_preferred_pbr(stocks), 1)
        self.assertEqual(stocks[1]["pbr"], 2.33)
        self.assertIsNone(stocks[2]["pbr"])

    def test_stock_row_keeps_legacy_units(self) -> None:
        row = stock_row(
            {
                "itemname": "삼성전자우",
                "itemcode": "005935",
                "type": "ST",
                "tradeStopYn": "N",
                "nowPrice": "201000",
                "prevChangePrice": "-3000",
                "prevChangeRate": "-1.47",
                "marketSum": "165401400000000",
                "listedStockCnt": "822886700",
                "tradeVolume": "1200",
                "propertyTotal": "5669421",
                "eps": "-500.0",
                "per": None,
                "roe": "10.85",
                "frgnHoldRate": "75.1",
            },
            MARKETS[0],
            1,
        )
        self.assertEqual(row["current_price"], 201000)
        self.assertEqual(row["diff"], 3000)
        self.assertEqual(row["diff_rate"], -1.47)
        self.assertEqual(row["market_cap_krw_100m"], 1654014)
        self.assertEqual(row["listed_shares"], 822887)
        self.assertEqual(row["property_total_krw_100m"], 5669421)
        self.assertEqual(row["per"], -402.0)
        self.assertIsNone(row["par_value"])
        self.assertFalse(row["is_suspended"])

    def test_fund_row_is_marked_fund_like(self) -> None:
        row = fund_row(
            {
                "itemCode": "069500",
                "stockName": "KODEX 200",
                "stockEndType": "etf",
                "closePriceRaw": "112060",
                "compareToPreviousClosePriceRaw": "540",
                "fluctuationsRatio": "0.48",
                "marketValue": "258,859",
                "marketValueRaw": "25885860000000",
                "accumulatedTradingVolumeRaw": "24580661",
                "tradeStopType": {"name": "TRADING"},
            },
            MARKETS[0],
            1,
        )
        self.assertEqual(row["par_value"], 0)
        self.assertEqual(row["market_cap_krw_100m"], 258859)
        self.assertEqual(row["listed_shares"], 231000)
        self.assertIsNone(row["roe"])
        self.assertFalse(row["is_suspended"])


if __name__ == "__main__":
    unittest.main()
