from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from env_loader import load_env_file


ROOT_DIR = Path(__file__).resolve().parent
HEARTBEAT_SECONDS = 30
STEP_RESULTS: list[dict[str, object]] = []


def record_skipped_step(name: str, reason: str) -> None:
    STEP_RESULTS.append(
        {
            "name": name,
            "status": "skipped",
            "reason": reason,
            "elapsed": 0.0,
        }
    )
    print(f"[SKIP] {name}: {reason}", flush=True)


def run_step(
    name: str,
    script: str,
    arguments: list[str],
    *,
    optional: bool = False,
) -> bool:
    command = [sys.executable, str(ROOT_DIR / script), *arguments]
    print(f"\n{'=' * 60}", flush=True)
    print(f"[START] {name}", flush=True)
    print(f"{'=' * 60}", flush=True)

    started_at = time.monotonic()
    print(
        f"[COMMAND] {Path(command[1]).name} {' '.join(arguments)}".rstrip(),
        flush=True,
    )
    try:
        process = subprocess.Popen(command, cwd=ROOT_DIR)
    except OSError as exc:
        elapsed = time.monotonic() - started_at
        STEP_RESULTS.append(
            {
                "name": name,
                "status": "failed",
                "reason": f"launch error: {exc}",
                "elapsed": elapsed,
            }
        )
        print(
            f"[FAILED] {name} could not start: {exc}\n"
            "[CONTINUE] The remaining collectors will still run.",
            flush=True,
        )
        return False

    while True:
        try:
            return_code = process.wait(timeout=HEARTBEAT_SECONDS)
            break
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started_at
            print(f"[RUNNING] {name} ({elapsed:.0f}s elapsed)", flush=True)
        except KeyboardInterrupt:
            process.terminate()
            process.wait()
            raise
    elapsed = time.monotonic() - started_at

    if return_code != 0:
        STEP_RESULTS.append(
            {
                "name": name,
                "status": "failed",
                "reason": f"exit code {return_code}",
                "elapsed": elapsed,
                "optional": optional,
            }
        )
        print(
            f"[FAILED] {name} (exit code: {return_code}, {elapsed:.1f}s)\n"
            "[CONTINUE] The remaining collectors will still run. "
            "The previous JSON for this dataset is preserved.",
            flush=True,
        )
        return False

    STEP_RESULTS.append(
        {
            "name": name,
            "status": "success",
            "reason": "",
            "elapsed": elapsed,
            "optional": optional,
        }
    )
    print(f"[DONE] {name} ({elapsed:.1f}s)", flush=True)
    return True


def print_pipeline_summary(total_elapsed: float) -> bool:
    succeeded = [row for row in STEP_RESULTS if row["status"] == "success"]
    failed = [row for row in STEP_RESULTS if row["status"] == "failed"]
    skipped = [row for row in STEP_RESULTS if row["status"] == "skipped"]

    print(f"\n{'=' * 60}", flush=True)
    print("[PIPELINE SUMMARY]", flush=True)
    print(f"{'=' * 60}", flush=True)
    print(
        f"Success: {len(succeeded)} | Failed: {len(failed)} | "
        f"Skipped: {len(skipped)} | Elapsed: {total_elapsed:.1f}s",
        flush=True,
    )
    for row in failed:
        print(
            f"  [FAILED] {row['name']} - {row['reason']} "
            f"({float(row['elapsed']):.1f}s)",
            flush=True,
        )
    for row in skipped:
        print(
            f"  [SKIPPED] {row['name']} - {row['reason']}",
            flush=True,
        )
    if failed:
        print(
            "[PARTIAL SUCCESS] Successful datasets can be committed. "
            "Failed datasets keep their previously committed JSON.",
            flush=True,
        )
    else:
        print("[SUCCESS] All executed collectors completed.", flush=True)
    return bool(failed)


def main() -> None:
    load_env_file(ROOT_DIR / ".env")

    parser = argparse.ArgumentParser(
        description=(
            "Run the treasury yield, ETF ticker, Naver, FnGuide, and OpenDART "
            "crawlers plus public U.S. market datasets in order."
        )
    )
    parser.add_argument(
        "--skip-rates",
        action="store_true",
        help="Skip the ECOS and FRED treasury yield crawler.",
    )
    parser.add_argument(
        "--rates-lookback-days",
        type=int,
        default=21,
        help="Lookback window for the latest valid treasury yield observations.",
    )
    parser.add_argument(
        "--skip-etf-tickers",
        action="store_true",
        help="Skip the Naver ETF brand ticker crawler.",
    )
    parser.add_argument(
        "--etf-brands",
        nargs="+",
        default=["KoAct", "TIME"],
        help="ETF name prefixes to collect for the ticker.",
    )
    parser.add_argument(
        "--skip-market-indices",
        action="store_true",
        help="Skip major market index and cryptocurrency charts.",
    )
    parser.add_argument(
        "--skip-market-heatmap",
        action="store_true",
        help="Skip the Korea/U.S. stock heatmap dataset.",
    )
    parser.add_argument(
        "--skip-dart",
        action="store_true",
        help="Skip the OpenDART crawler.",
    )
    parser.add_argument(
        "--skip-finra",
        action="store_true",
        help="Skip the public FINRA short-sale-volume crawler.",
    )
    parser.add_argument(
        "--skip-krx",
        action="store_true",
        help="Skip KRX Open API and login-based investor/short datasets.",
    )
    parser.add_argument(
        "--skip-us-market",
        action="store_true",
        help="Skip the Nasdaq/Yahoo U.S. market snapshot.",
    )
    parser.add_argument(
        "--us-history-limit",
        type=int,
        default=200,
        help="Number of top U.S. stocks for which Yahoo daily history is collected.",
    )
    parser.add_argument(
        "--skip-sec",
        action="store_true",
        help="Skip SEC insider, 13D/G, 8-K, and IPO filing metadata.",
    )
    parser.add_argument(
        "--sec-limit",
        type=int,
        default=200,
        help="Number of top U.S. stocks checked in SEC EDGAR.",
    )
    parser.add_argument(
        "--skip-finnhub",
        action="store_true",
        help="Skip Finnhub U.S. metrics and analyst data.",
    )
    parser.add_argument(
        "--finnhub-limit",
        type=int,
        default=100,
        help="Number of top U.S. stocks enriched with Finnhub.",
    )
    parser.add_argument(
        "--skip-news",
        action="store_true",
        help="Skip NAVER Search API news.",
    )
    parser.add_argument(
        "--skip-ai-briefing",
        action="store_true",
        help="Skip the Gemini briefing.",
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
        "--min-roa",
        type=float,
        default=7.0,
        help="Minimum current ROA for FnGuide and OpenDART targets. Use a negative value to disable.",
    )
    parser.add_argument(
        "--no-financial-roa-exempt",
        action="store_true",
        help="Apply the ROA filter to bank, securities, insurance, REIT, and SPAC-like names too.",
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

    if not args.skip_rates and not os.environ.get("ECOS_API_KEY", "").strip():
        args.skip_rates = True
        record_skipped_step(
            "Korea and US treasury yields",
            "ECOS_API_KEY is not set",
        )

    if not args.skip_dart and not os.environ.get("DART_API_KEY", "").strip():
        args.skip_dart = True
        record_skipped_step(
            "OpenDART collectors",
            "DART_API_KEY is not set",
        )

    total_started_at = time.monotonic()
    if not args.skip_rates:
        run_step(
            "Korea and US treasury yields",
            "crawler_treasury_yields.py",
            ["--lookback-days", str(args.rates_lookback_days)],
        )

    if not args.skip_etf_tickers:
        run_step(
            "Naver ETF brand tickers",
            "crawler_naver_etf_brands.py",
            args.etf_brands,
        )

    if not args.skip_market_indices:
        run_step(
            "Global market indices and crypto charts",
            "crawler_market_indices.py",
            [],
            optional=True,
        )

    if not args.skip_finra:
        run_step(
            "FINRA U.S. short sale volume",
            "crawler_finra_short_volume.py",
            [],
            optional=True,
        )
        run_step(
            "FINRA U.S. consolidated short interest",
            "crawler_finra_short_interest.py",
            [],
            optional=True,
        )

    if not args.skip_us_market:
        run_step(
            "Nasdaq and Yahoo U.S. market snapshot",
            "crawler_us_market.py",
            ["--history-limit", str(args.us_history_limit)],
            optional=True,
        )

    if not args.skip_sec:
        run_step(
            "SEC insider, ownership, material event, and IPO filings",
            "crawler_sec_filings.py",
            ["--limit", str(args.sec_limit)],
            optional=True,
        )

    if not args.skip_finnhub:
        if os.environ.get("FINNHUB_API_KEY", "").strip():
            run_step(
                "Finnhub U.S. metrics and analyst data",
                "crawler_finnhub_us.py",
                ["--limit", str(args.finnhub_limit)],
                optional=True,
            )
        else:
            record_skipped_step(
                "Finnhub U.S. metrics and analyst data",
                "FINNHUB_API_KEY is not set",
            )

    if not args.skip_krx:
        if os.environ.get("KRX_API_KEY", "").strip():
            run_step(
                "KRX Open API market datasets",
                "crawler_krx_openapi.py",
                [],
                optional=True,
            )
        else:
            record_skipped_step(
                "KRX Open API market datasets",
                "KRX_API_KEY is not set",
            )
        if (
            os.environ.get("KRX_ID", "").strip()
            and os.environ.get("KRX_PW", "").strip()
        ):
            run_step(
                "KRX investor flow and short selling",
                "crawler_krx_flow_short.py",
                [],
            )
        else:
            record_skipped_step(
                "KRX investor flow and short selling",
                "KRX_ID/KRX_PW are not set",
            )

    remaining_after_naver = []
    if not args.skip_market_heatmap:
        remaining_after_naver.append("Korea and U.S. market heatmap")
    remaining_after_naver.append("FnGuide ROE history")
    if not args.skip_dart:
        remaining_after_naver.extend(
            [
                "OpenDART major holders",
                "OpenDART recent disclosures",
                "OpenDART event details and insider ownership changes",
            ]
        )
    if (
        not args.skip_news
        and os.environ.get("NAVER_CLIENT_ID", "").strip()
        and os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    ):
        remaining_after_naver.append("NAVER categorized market news")
    if not args.skip_ai_briefing and os.environ.get("GEMINI_API_KEY", "").strip():
        remaining_after_naver.append("Gemini market briefing")
    remaining_after_naver.append("Build data manifest")
    print(
        "[PIPELINE] Naver market data is not the final step. "
        f"After it: {' -> '.join(remaining_after_naver)}",
        flush=True,
    )
    run_step(
        "Naver market data",
        "crawler_naver_market_sum.py",
        ["--delay", str(args.naver_delay)],
    )
    if not args.skip_market_heatmap:
        run_step(
            "Korea and U.S. market heatmap",
            "crawler_market_heatmap.py",
            [],
            optional=True,
        )
    run_step(
        "FnGuide ROE history",
        "crawler_fnguide_roe_history.py",
        [
            "--delay",
            str(args.fnguide_delay),
            "--min-roe",
            str(args.fnguide_min_roe),
            "--min-roa",
            str(args.min_roa),
            "--limit",
            str(args.fnguide_limit),
            *(["--no-financial-roa-exempt"] if args.no_financial_roa_exempt else []),
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
                "--min-roa",
                str(args.min_roa),
                "--limit",
                str(args.dart_limit),
                *(["--no-financial-roa-exempt"] if args.no_financial_roa_exempt else []),
            ],
        )
        run_step(
            "OpenDART recent disclosures",
            "crawler_dart_disclosures.py",
            [],
        )
        run_step(
            "OpenDART event details and insider ownership changes",
            "crawler_dart_event_details.py",
            [],
        )

    if not args.skip_news:
        if (
            os.environ.get("NAVER_CLIENT_ID", "").strip()
            and os.environ.get("NAVER_CLIENT_SECRET", "").strip()
        ):
            run_step(
                "NAVER categorized market news",
                "crawler_naver_news.py",
                [],
                optional=True,
            )
        else:
            record_skipped_step(
                "NAVER categorized market news",
                "NAVER_CLIENT_ID/NAVER_CLIENT_SECRET are not set",
            )

    if not args.skip_ai_briefing:
        if os.environ.get("GEMINI_API_KEY", "").strip():
            run_step(
                "Gemini market briefing",
                "crawler_gemini_briefing.py",
                [],
                optional=True,
            )
        else:
            record_skipped_step(
                "Gemini market briefing",
                "GEMINI_API_KEY is not set",
            )

    run_step(
        "Build data manifest",
        "build_data_manifest.py",
        [],
    )

    elapsed = time.monotonic() - total_started_at
    if print_pipeline_summary(elapsed):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
