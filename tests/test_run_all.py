from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

import run_all


class PipelineSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_results = run_all.STEP_RESULTS[:]
        run_all.STEP_RESULTS.clear()

    def tearDown(self) -> None:
        run_all.STEP_RESULTS[:] = self.original_results

    def summarize(self) -> tuple[bool, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            failed = run_all.print_pipeline_summary(12.5)
        return failed, output.getvalue()

    def test_optional_collector_failure_is_warning(self) -> None:
        run_all.STEP_RESULTS.extend(
            [
                {
                    "name": "Required collector",
                    "status": "success",
                    "reason": "",
                    "elapsed": 1.0,
                    "optional": False,
                },
                {
                    "name": "SEC filings",
                    "status": "failed",
                    "reason": "exit code 1",
                    "elapsed": 2.0,
                    "optional": True,
                },
            ]
        )

        failed, output = self.summarize()

        self.assertFalse(failed)
        self.assertIn("Failed: 0 | Warnings: 1", output)
        self.assertIn("[WARNING] SEC filings", output)
        self.assertIn("[SUCCESS WITH WARNINGS]", output)

    def test_required_collector_failure_still_fails_pipeline(self) -> None:
        run_all.STEP_RESULTS.append(
            {
                "name": "Required collector",
                "status": "failed",
                "reason": "exit code 1",
                "elapsed": 3.0,
                "optional": False,
            }
        )

        failed, output = self.summarize()

        self.assertTrue(failed)
        self.assertIn("Failed: 1 | Warnings: 0", output)
        self.assertIn("[FAILED] Required collector", output)
        self.assertIn("[PARTIAL SUCCESS]", output)


if __name__ == "__main__":
    unittest.main()
