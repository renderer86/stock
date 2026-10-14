import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import crawler_market_heatmap as crawler


class RegionalHeatmapTests(unittest.TestCase):
    def test_us_refresh_preserves_korea_without_sector_network_requests(self):
        previous = {
            "markets": {"KR": {"count": 1, "stocks": [{"marker": "keep"}]}},
            "sector_catalog_count": 5, "sector_mapping_count": 20, "errors": [],
        }
        generated = {
            "markets": {"KR": {"count": 0}, "US": {"count": 2}},
            "count": 2, "sector_catalog_count": 0, "sector_mapping_count": 0, "errors": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "heatmap.json"
            output.write_text(json.dumps(previous), encoding="utf-8")
            with (
                patch.object(sys, "argv", ["crawler", "--output", str(output), "--market-scope", "us"]),
                patch.object(crawler, "crawl_korea_sector_map") as sectors,
                patch.object(crawler, "build_payload", return_value=generated),
                redirect_stdout(io.StringIO()),
            ):
                crawler.main()
            sectors.assert_not_called()
            actual = json.loads(output.read_text())
            self.assertEqual(actual["markets"]["KR"], previous["markets"]["KR"])
            self.assertEqual(actual["count"], 3)
            self.assertEqual(actual["sector_mapping_count"], 20)

    def test_korea_refresh_preserves_us(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "heatmap.json"
            us = {"count": 2, "stocks": [{"marker": "keep"}]}
            output.write_text(json.dumps({"markets": {"US": us}}), encoding="utf-8")
            generated = {"markets": {"KR": {"count": 3}, "US": {"count": 0}}, "count": 3}
            with (
                patch.object(sys, "argv", ["crawler", "--output", str(output), "--market-scope", "korea"]),
                patch.object(crawler, "crawl_korea_sector_map", return_value=({}, [], 0)) as sectors,
                patch.object(crawler, "build_payload", return_value=generated),
                redirect_stdout(io.StringIO()),
            ):
                crawler.main()
            sectors.assert_called_once()
            actual = json.loads(output.read_text())
            self.assertEqual(actual["markets"]["US"], us)
            self.assertEqual(actual["count"], 5)


if __name__ == "__main__":
    unittest.main()
