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


if __name__ == "__main__":
    unittest.main()
