from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DashboardPendingDetailTests(unittest.TestCase):
    def test_pending_badges_open_an_accessible_detail_dialog(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("<h2>버핏 스타일</h2>", html)
        self.assertIn('id="buffett-pending-badge"', html)
        self.assertIn('id="quality-pending-badge"', html)
        self.assertIn('aria-controls="screen-pending-modal"', html)
        self.assertIn('id="screen-pending-modal"', html)
        self.assertIn('role="dialog"', html)

    def test_every_current_missing_condition_has_a_visible_reason(self) -> None:
        script = (ROOT / "script.js").read_text(encoding="utf-8")
        payload = json.loads(
            (ROOT / "data/investment_screens.json").read_text(encoding="utf-8")
        )
        missing_conditions = {
            condition
            for result in (payload.get("results") or {}).values()
            for screen in (result.get("buffett") or {}, result.get("quality") or {})
            for condition in ((screen.get("coverage") or {}).get("missing") or [])
        }

        for condition in missing_conditions:
            self.assertRegex(script, rf"\b{re.escape(condition)}\s*:")

    def test_pending_detail_assets_share_the_same_cache_version(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        style_version = re.search(r"style\.css\?v=([^\"']+)", html)
        script_version = re.search(r"script\.js\?v=([^\"']+)", html)

        self.assertIsNotNone(style_version)
        self.assertIsNotNone(script_version)
        self.assertEqual(style_version.group(1), script_version.group(1))

    def test_buffett_watchlist_explains_gate_and_renders_strength_tags(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "script.js").read_text(encoding="utf-8")
        payload = json.loads(
            (ROOT / "data/investment_screens.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn("최근 3개 연속 사업연도", html)
        self.assertIn("buffett_watchlist", script)
        self.assertIn("buffett-strength-tags", script)
        self.assertIn("정상 FCF 수익률", html)
        self.assertIn("최신 ROIC", script)
        self.assertGreater(payload["summary"]["buffett_watchlist_count"], 2)
        for ranking in payload["rankings"]["buffett_watchlist"]:
            buffett = payload["results"][ranking["ticker"]]["buffett"]
            self.assertEqual(buffett["minimum_persistence_status"], "pass")
            self.assertEqual(buffett["excess_cash_status"], "pass")
            self.assertGreaterEqual(buffett["supporting_condition_count"], 1)
            self.assertTrue(buffett["strength_tags"])
            self.assertIn(
                buffett["valuation"]["normalized_fcf_basis"],
                ("10y_average", "3y_average_fallback", None),
            )

        korea_info = payload["results"]["025770"]["buffett"]
        self.assertEqual(korea_info["watchlist_status"], "fail")
        self.assertFalse(
            korea_info["valuation"][
                "cash_to_market_cap_le_50pct_or_financial"
            ]
        )
        self.assertIsNone(korea_info["incremental_roic_5y_pct"])

    def test_buffett_watchlist_has_a_mobile_card_layout(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "script.js").read_text(encoding="utf-8")
        style = (ROOT / "style.css").read_text(encoding="utf-8")

        self.assertIn('class="buffett-watchlist-table"', html)
        self.assertIn('class="buffett-identity-cell"', script)
        self.assertIn('class="buffett-return-cell"', script)
        self.assertIn(".buffett-watchlist-table tbody tr", style)
        self.assertIn("grid-column: 1 / -1", style)

    def test_valuation_uses_duration_labels_and_discloses_fallback_method(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "script.js").read_text(encoding="utf-8")

        self.assertIn("고ROE 지속기간 N", html)
        self.assertIn("시장 내재 N", html)
        self.assertNotIn("재무제표 추정 N", html)
        self.assertNotIn("재무제표 추정 N", script)
        self.assertIn("function nEstimateMethodLabel", script)
        self.assertIn('return "임시 점수표";', script)
        self.assertIn("아직 실증 지속기간 데이터가 없는 종목", script)

    def test_selected_stock_shows_ten_year_matrix_inside_summary_hero(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "script.js").read_text(encoding="utf-8")
        style = (ROOT / "style.css").read_text(encoding="utf-8")
        payload = json.loads(
            (ROOT / "data/investment_screens.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn("10년 연도별 재무·밸류에이션", html)
        self.assertIn('class="annual-matrix-scroll"', script)
        self.assertIn('["PBR", "pbr"', script)
        self.assertIn(".annual-matrix th:first-child", style)
        samsung = payload["results"]["005930"]["long_term_financials"]
        self.assertEqual(len(samsung["annual"]), 10)
        self.assertTrue(all(row["pbr"] for row in samsung["annual"]))
        self.assertGreater(samsung["annual"][0]["pbr"], 0.5)

    def test_buffett_candidate_can_open_outside_default_valuation_filters(
        self,
    ) -> None:
        script = (ROOT / "script.js").read_text(encoding="utf-8")
        market = json.loads(
            (ROOT / "data/market_sum.json").read_text(encoding="utf-8")
        )
        screens = json.loads(
            (ROOT / "data/investment_screens.json").read_text(
                encoding="utf-8"
            )
        )
        first = screens["rankings"]["buffett_watchlist"][0]
        stock = next(
            row for row in market["stocks"] if row["code"] == first["ticker"]
        )

        self.assertEqual(first["ticker"], "030000")
        self.assertLess(stock["roa"], 7)
        self.assertIn("rawStockByCode: new Map()", script)
        self.assertIn("const rawStock = state.rawStockByCode.get(code);", script)
        self.assertIn(
            "selectedRawStock ? enrichStock(selectedRawStock) : null",
            script,
        )


if __name__ == "__main__":
    unittest.main()
