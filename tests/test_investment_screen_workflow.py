from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFRESH_WORKFLOW = ROOT / ".github/workflows/refresh-investment-screens.yml"
DART_WORKFLOW = ROOT / ".github/workflows/build-dart-financial-panel.yml"
DEPLOY_WORKFLOW = ROOT / ".github/workflows/deploy-dashboard.yml"


class InvestmentScreenWorkflowTests(unittest.TestCase):
    def test_refresh_workflow_supports_manual_and_upstream_runs(self) -> None:
        text = REFRESH_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", text)
        self.assertIn('"Build DART 10-year financial panel"', text)
        self.assertIn('"Update market data"', text)

    def test_refresh_workflow_builds_and_commits_every_output(self) -> None:
        text = REFRESH_WORKFLOW.read_text(encoding="utf-8")
        commands = (
            "crawler_naver_year_end_prices.py",
            "estimate_financial_n.py",
            "build_investment_screens.py",
            "build_data_manifest.py",
        )

        positions = [text.index(command) for command in commands]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("data/financial_n_estimates.json", text)
        self.assertIn("data/naver_year_end_prices.json", text)
        self.assertIn("data/investment_screens.json", text)
        self.assertIn("data/data_manifest.json", text)

    def test_dart_and_deploy_workflows_do_not_publish_stale_screens(self) -> None:
        dart_text = DART_WORKFLOW.read_text(encoding="utf-8")
        deploy_text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

        self.assertNotIn("estimate_financial_n.py", dart_text)
        self.assertNotIn("build_investment_screens.py", dart_text)
        self.assertNotIn('      - "Build DART 10-year financial panel"', deploy_text)


if __name__ == "__main__":
    unittest.main()
