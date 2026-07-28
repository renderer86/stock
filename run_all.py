from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from env_loader import load_env_file


ROOT_DIR = Path(__file__).resolve().parent


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
    result = subprocess.run(command, cwd=ROOT_DIR, check=False)
    elapsed = time.monotonic() - started_at

    if result.returncode != 0:
        if optional:
            print(
                f"[WARN] {name} failed and was skipped "
                f"(exit code: {result.returncode}, {elapsed:.1f}s)",
                flush=True,
            )
            return False
        raise SystemExit(
            f"\n[FAIL] {name} (exit code: {result.returncode}, {elapsed:.1f}s)"
        )
    print(f"[DONE] {name} ({elapsed:.1f}s)", flush=True)
    return True


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
        help="Skip official KRX Open API EOD datasets.",
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
        parser.error(
            "ECOS_API_KEY is not set. Set it before running, or pass --skip-rates."
        )

    if not args.skip_dart and not os.environ.get("DART_API_KEY", "").strip():
        parser.error(
            "DART_API_KEY is not set. Set it before running, or pass --skip-dart."
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
            print("[SKIP] FINNHUB_API_KEY is not set.", flush=True)

    if not args.skip_krx:
        if os.environ.get("KRX_API_KEY", "").strip():
            run_step(
                "KRX Open API market datasets",
                "crawler_krx_openapi.py",
                [],
                optional=True,
            )
        else:
            print("[SKIP] KRX_API_KEY is not set.", flush=True)

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
            optional=True,
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
            print("[SKIP] NAVER_CLIENT_ID/NAVER_CLIENT_SECRET are not set.", flush=True)

    if not args.skip_ai_briefing:
        if os.environ.get("GEMINI_API_KEY", "").strip():
            run_step(
                "Gemini market briefing",
                "crawler_gemini_briefing.py",
                [],
                optional=True,
            )
        else:
            print("[SKIP] GEMINI_API_KEY is not set.", flush=True)

    run_step(
        "Build data manifest",
        "build_data_manifest.py",
        [],
    )

    elapsed = time.monotonic() - total_started_at
    print(f"\nAll requested crawlers completed successfully ({elapsed:.1f}s).")


if __name__ == "__main__":
    main()
