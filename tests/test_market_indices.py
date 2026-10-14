import unittest
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import crawler_market_indices as crawler
from crawler_market_indices import merge_history, parse_naver_index_history


class MarketIndicesTest(unittest.TestCase):
    def test_regional_refresh_preserves_other_regions_and_failed_charts(self):
        for scope in ("korea", "us"):
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "indices.json"
                previous = [{"id": asset["id"], "current": 1, "marker": "old"} for asset in crawler.ASSETS]
                output.write_text(json.dumps({"assets": previous}), encoding="utf-8")
                called = []

                def fetch(asset, range_value):
                    called.append(asset["id"])
                    if asset["id"] in ("kosdaq", "nasdaq"):
                        raise RuntimeError("test failure")
                    return {"id": asset["id"], "current": 2, "change_pct": 0, "marker": "new"}

                with (
                    patch.object(sys, "argv", ["crawler", "--output", str(output), "--market-scope", scope]),
                    patch.object(crawler, "fetch_asset", side_effect=fetch),
                    redirect_stdout(io.StringIO()),
                ):
                    crawler.main()
                rows = {row["id"]: row for row in json.loads(output.read_text())["assets"]}
                selected = {asset["id"] for asset in crawler.ASSETS if (asset["group"] == "Korea") == (scope == "korea")}
                self.assertEqual(set(called), selected)
                self.assertEqual(len(rows), len(previous))
                for asset in crawler.ASSETS:
                    refreshed = asset["id"] in selected and asset["id"] not in ("kosdaq", "nasdaq")
                    self.assertEqual(rows[asset["id"]]["marker"], "new" if refreshed else "old")

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
