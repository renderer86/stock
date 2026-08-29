from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PortfolioBoardTests(unittest.TestCase):
    def test_public_portfolio_contains_requested_holdings_and_cash(self) -> None:
        payload = json.loads(
            (ROOT / "data/portfolio.json").read_text(encoding="utf-8")
        )
        holdings = payload["holdings"]
        stocks = [holding for holding in holdings if holding["type"] == "stock"]
        cash = next(holding for holding in holdings if holding["type"] == "cash")

        self.assertEqual(
            {holding["code"] for holding in stocks},
            {"000660", "042700", "078340", "138040", "214450", "383220"},
        )
        self.assertAlmostEqual(
            sum(float(holding["weight_pct"]) for holding in holdings),
            100.0,
            places=2,
        )
        self.assertEqual(cash["code"], "CASH")
        self.assertEqual(cash["position"], "GK")
        self.assertEqual(float(cash["weight_pct"]), 0.06)

        by_code = {holding["code"]: holding for holding in stocks}
        expected = {
            "000660": (13.46, "LW"),
            "042700": (17.55, "FW"),
            "078340": (5.16, "RW"),
            "214450": (39.11, "AM"),
            "383220": (5.7, "DM"),
            "138040": (18.96, "CB"),
        }
        for code, (weight, position) in expected.items():
            self.assertEqual(float(by_code[code]["weight_pct"]), weight)
            self.assertEqual(by_code[code]["position"], position)

    def test_public_portfolio_has_complete_editable_note_drafts(self) -> None:
        payload = json.loads(
            (ROOT / "data/portfolio.json").read_text(encoding="utf-8")
        )
        required = {
            "investment_idea",
            "price_view",
            "key_variables",
            "scenario",
            "catalysts",
        }
        for holding in payload["holdings"]:
            notes = holding["notes"]
            self.assertTrue(required.issubset(notes))
            self.assertTrue(all(str(notes[key]).strip() for key in required))

    def test_portfolio_board_is_above_market_heatmap_and_is_interactive(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "script.js").read_text(encoding="utf-8")
        style = (ROOT / "style.css").read_text(encoding="utf-8")

        self.assertLess(html.index('id="portfolio-board"'), html.index('id="market-map-board"'))
        self.assertIn("function renderPortfolioBoard", script)
        self.assertIn("function portfolioScenarioReturn", script)
        self.assertIn("data-portfolio-code", script)
        self.assertIn("const PORTFOLIO_POSITIONS", script)
        self.assertIn('WF: { x:', script)
        self.assertIn('SW: { x:', script)
        self.assertIn('RL: "RM"', script)
        self.assertIn("localStorage.setItem(PORTFOLIO_STORAGE_KEY", script)
        self.assertIn("data-portfolio-add", script)
        self.assertIn("function renderPortfolioEditor", script)
        self.assertIn('id="portfolio-modal"', html)
        self.assertIn(".portfolio-pitch", style)
        self.assertIn(".portfolio-player", style)
        self.assertIn(".portfolio-detail-panel", style)
        self.assertIn(".portfolio-editor-form", style)

    def test_portfolio_assets_share_the_same_cache_version(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        style_version = re.search(r"style\.css\?v=([^\"']+)", html)
        script_version = re.search(r"script\.js\?v=([^\"']+)", html)

        self.assertIsNotNone(style_version)
        self.assertIsNotNone(script_version)
        self.assertEqual(style_version.group(1), script_version.group(1))


if __name__ == "__main__":
    unittest.main()
