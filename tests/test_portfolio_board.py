from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PortfolioBoardTests(unittest.TestCase):
    def test_public_portfolio_contains_the_six_requested_holdings(self) -> None:
        payload = json.loads(
            (ROOT / "data/portfolio.json").read_text(encoding="utf-8")
        )
        holdings = payload["holdings"]

        self.assertEqual(
            {holding["code"] for holding in holdings},
            {"042700", "138040", "214450", "383220", "005930", "000660"},
        )
        self.assertAlmostEqual(
            sum(float(holding["weight_pct"]) for holding in holdings),
            100.0,
            places=2,
        )
        self.assertTrue(all(0 < holding["x_pct"] < 100 for holding in holdings))
        self.assertTrue(all(0 < holding["y_pct"] < 100 for holding in holdings))

    def test_portfolio_board_is_above_market_heatmap_and_is_interactive(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "script.js").read_text(encoding="utf-8")
        style = (ROOT / "style.css").read_text(encoding="utf-8")

        self.assertLess(html.index('id="portfolio-board"'), html.index('id="market-map-board"'))
        self.assertIn("function renderPortfolioBoard", script)
        self.assertIn("function portfolioScenarioReturn", script)
        self.assertIn("data-portfolio-code", script)
        self.assertIn("renderMarketMapDetail(stock)", script)
        self.assertIn(".portfolio-pitch", style)
        self.assertIn(".portfolio-player", style)

    def test_portfolio_assets_share_the_same_cache_version(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        style_version = re.search(r"style\.css\?v=([^\"']+)", html)
        script_version = re.search(r"script\.js\?v=([^\"']+)", html)

        self.assertIsNotNone(style_version)
        self.assertIsNotNone(script_version)
        self.assertEqual(style_version.group(1), script_version.group(1))


if __name__ == "__main__":
    unittest.main()
