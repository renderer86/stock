from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import run_all
import scheduled_update


ROOT = Path(__file__).resolve().parents[1]


class ScheduledProfilesTests(unittest.TestCase):
    def collectors(self, profile: str) -> dict[str, list[str]]:
        command = scheduled_update.PROFILE_COMMANDS[profile]
        self.assertEqual(command[0], "run_all.py")
        collected = {}

        def run(name, script, arguments, **kwargs):
            collected[script] = arguments
            return True

        with (
            patch.object(sys, "argv", command),
            patch.object(run_all, "load_env_file"),
            patch.object(run_all, "run_step", side_effect=run),
            patch.object(run_all, "STEP_RESULTS", []),
            patch.dict(os.environ, {key: "test" for key in (
                "ECOS_API_KEY", "DART_API_KEY", "KRX_API_KEY", "KRX_ID", "KRX_PW",
                "FINNHUB_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "GEMINI_API_KEY",
            )}),
            redirect_stdout(io.StringIO()),
        ):
            run_all.main()
        return collected

    def test_korean_close_runs_domestic_collectors_without_us_collectors(self):
        scripts = self.collectors("market-close")
        for script in (
            "crawler_naver_market_sum.py", "crawler_fnguide_roe_history.py",
            "crawler_dart_disclosures.py", "crawler_krx_flow_short.py",
            "crawler_naver_etf_brands.py", "crawler_dart_event_details.py",
        ):
            self.assertIn(script, scripts)
        for script in (
            "crawler_us_market.py", "crawler_finnhub_us.py", "crawler_sec_filings.py",
            "crawler_finra_short_volume.py", "crawler_finra_short_interest.py",
            "crawler_treasury_yields.py",
        ):
            self.assertNotIn(script, scripts)
        self.assertEqual(scripts["crawler_market_indices.py"], ["--market-scope", "korea"])
        self.assertEqual(scripts["crawler_market_heatmap.py"], ["--market-scope", "korea"])

    def test_us_close_does_not_refresh_korean_stocks_or_disclosures(self):
        scripts = self.collectors("us-open")
        for script in (
            "crawler_us_market.py", "crawler_finnhub_us.py", "crawler_sec_filings.py",
            "crawler_finra_short_volume.py", "crawler_finra_short_interest.py",
        ):
            self.assertIn(script, scripts)
        for script in (
            "crawler_naver_market_sum.py", "crawler_fnguide_roe_history.py",
            "crawler_dart_disclosures.py", "crawler_krx_flow_short.py",
            "crawler_naver_etf_brands.py", "crawler_treasury_yields.py",
        ):
            self.assertNotIn(script, scripts)
        self.assertEqual(scripts["crawler_market_indices.py"], ["--market-scope", "us"])
        self.assertEqual(scripts["crawler_market_heatmap.py"], ["--market-scope", "us"])

    def test_weekday_morning_adds_rates_and_all_preserves_full_collection(self):
        morning = self.collectors("morning")
        self.assertIn("crawler_treasury_yields.py", morning)
        self.assertIn("crawler_us_market.py", morning)
        self.assertNotIn("crawler_naver_market_sum.py", morning)
        full = self.collectors("all")
        for script in ("crawler_us_market.py", "crawler_naver_market_sum.py", "crawler_treasury_yields.py"):
            self.assertIn(script, full)

    def test_workflow_routes_each_schedule_dispatch_and_push(self):
        bash = shutil.which("bash")
        if not bash:
            git_bash = Path("C:/Program Files/Git/bin/bash.exe")
            bash = str(git_bash) if git_bash.exists() else None
        if not bash:
            self.skipTest("Bash unavailable")
        workflow = (ROOT / ".github/workflows/update-market-data.yml").read_text(encoding="utf-8")
        step = workflow.split("- name: Select collection profile", 1)[1].split("- name: Crawl market data", 1)[0]
        shell = textwrap.dedent(step.split("run: |\n", 1)[1])
        cases = (
            ("schedule", "30 7 * * 1-5", "", "market-close"),
            ("schedule", "30 23 * * 0", "", "rates"),
            ("schedule", "30 23 * * 1-4", "", "morning"),
            ("schedule", "30 23 * * 5", "", "us-open"),
            ("workflow_dispatch", "", "us-open", "us-open"),
            ("push", "", "", "all"),
        )
        for event, schedule, manual, expected in cases:
            with self.subTest(event=event, schedule=schedule), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output"
                code = shell.replace("${{ github.event_name }}", event).replace(
                    "${{ github.event.schedule }}", schedule
                ).replace("${{ inputs.profile }}", manual)
                result = subprocess.run(
                    [bash, "-c", code], capture_output=True, text=True,
                    env={**os.environ, "GITHUB_OUTPUT": output.as_posix()}, check=True,
                )
                self.assertEqual(output.read_text().strip(), f"value={expected}", result.stdout)


if __name__ == "__main__":
    unittest.main()
