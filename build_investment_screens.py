from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from collector_common import atomic_write_json
from dart_financial_storage import load_financial_panel
from financial_engine import InvestmentScreenBuilder


DEFAULT_PANEL = Path("data/dart_financial_panel.json")
DEFAULT_N = Path("data/financial_n_estimates.json")
DEFAULT_MARKET = Path("data/market_sum.json")
DEFAULT_OUTPUT = Path("data/investment_screens.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build Buffett and statistical-quality screens from local JSON. "
            "No external API calls are made."
        )
    )
    parser.add_argument("--panel", default=str(DEFAULT_PANEL))
    parser.add_argument("--n-estimates", default=str(DEFAULT_N))
    parser.add_argument("--market-sum", default=str(DEFAULT_MARKET))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quality-basket-size", type=int, default=25)
    return parser.parse_args()


def load_json(path: Path, *, required: bool = True) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            raise SystemExit(f"Input file does not exist: {path}") from None
        return {}
    except ValueError as exc:
        raise SystemExit(f"Invalid JSON: {path}: {exc}") from None
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a JSON object: {path}")
    return payload


def main() -> None:
    args = parse_args()
    panel = load_financial_panel(Path(args.panel))
    n_estimates = load_json(Path(args.n_estimates))
    market_sum = load_json(Path(args.market_sum), required=False)
    output_path = Path(args.output)
    payload = InvestmentScreenBuilder(
        quality_basket_size=args.quality_basket_size
    ).build(panel, n_estimates, market_sum)
    atomic_write_json(output_path, payload, compact=True)
    summary = payload["summary"]
    print(
        f"[SCREENS] output={output_path} | "
        f"companies={summary['company_count']:,} | "
        f"Buffett={summary['buffett_candidate_count']:,} | "
        f"quality basket={summary['quality_basket_count']:,}",
        flush=True,
    )


if __name__ == "__main__":
    main()
