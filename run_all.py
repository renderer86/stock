from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent


def run_step(name: str, script: str, arguments: list[str]) -> None:
    command = [sys.executable, str(ROOT_DIR / script), *arguments]
    print(f"\n{'=' * 60}", flush=True)
    print(f"[START] {name}", flush=True)
    print(f"{'=' * 60}", flush=True)

    started_at = time.monotonic()
    result = subprocess.run(command, cwd=ROOT_DIR, check=False)
    elapsed = time.monotonic() - started_at

    if result.returncode != 0:
        raise SystemExit(
            f"\n[FAIL] {name} (exit code: {result.returncode}, {elapsed:.1f}s)"
        )
    print(f"[DONE] {name} ({elapsed:.1f}s)", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Naver, FnGuide, and OpenDART crawlers in order."
    )
    parser.add_argument(
        "--skip-dart",
        action="store_true",
        help="Run only the Naver and FnGuide crawlers.",
    )
    parser.add_argument(
        "--naver-delay",
        type=float,
        default=0.2,
        help="Delay between Naver requests in seconds.",
    )
    parser.add_argument(
        "--fnguide-delay",
        type=float,
        default=0.25,
        help="Delay between FnGuide requests in seconds.",
    )
    parser.add_argument(
        "--fnguide-min-roe",
        type=float,
        default=10.0,
        help="Minimum current ROE for FnGuide targets. Use a negative value for all.",
    )
    parser.add_argument(
        "--fnguide-limit",
        type=int,
        default=0,
        help="Optional maximum number of FnGuide targets.",
    )
    parser.add_argument(
        "--dart-delay",
        type=float,
        default=0.2,
        help="Delay between OpenDART requests in seconds.",
    )
    parser.add_argument(
        "--dart-scope",
        choices=["roe", "priority", "all"],
        default="roe",
        help="OpenDART target scope.",
    )
    parser.add_argument(
        "--dart-limit",
        type=int,
        default=0,
        help="Optional maximum number of OpenDART targets.",
    )
    args = parser.parse_args()

    if not args.skip_dart and not os.environ.get("DART_API_KEY", "").strip():
        parser.error(
            "DART_API_KEY is not set. Set it before running, or pass --skip-dart."
        )

    total_started_at = time.monotonic()
    run_step(
        "Naver market data",
        "crawler_naver_market_sum.py",
        ["--delay", str(args.naver_delay)],
    )
    run_step(
        "FnGuide ROE history",
        "crawler_fnguide_roe_history.py",
        [
            "--delay",
            str(args.fnguide_delay),
            "--min-roe",
            str(args.fnguide_min_roe),
            "--limit",
            str(args.fnguide_limit),
        ],
    )

    if not args.skip_dart:
        run_step(
            "OpenDART major holders",
            "crawler_dart_major_holders.py",
            [
                "--delay",
                str(args.dart_delay),
                "--scope",
                args.dart_scope,
                "--min-roe",
                str(args.fnguide_min_roe),
                "--limit",
                str(args.dart_limit),
            ],
        )

    elapsed = time.monotonic() - total_started_at
    print(f"\nAll requested crawlers completed successfully ({elapsed:.1f}s).")


if __name__ == "__main__":
    main()
