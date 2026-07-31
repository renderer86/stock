from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from collector_common import atomic_write_json
from dart_financial_storage import load_financial_panel
from financial_engine import FinancialNEstimator, NEngineConfig


DEFAULT_PANEL = Path("data/dart_financial_panel.json")
DEFAULT_OUTPUT = Path("data/financial_n_estimates.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Estimate empirical high-ROE persistence N from the DART panel. "
            "No external API calls are made."
        )
    )
    parser.add_argument("--panel", default=str(DEFAULT_PANEL))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--config",
        default="",
        help="Optional JSON file containing NEngineConfig field overrides.",
    )
    parser.add_argument("--min-sector-pairs", type=int, default=0)
    parser.add_argument("--max-n", type=float, default=0)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Input file does not exist: {path}") from None
    except ValueError as exc:
        raise SystemExit(f"Invalid JSON: {path}: {exc}") from None
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a JSON object: {path}")
    return payload


def build_config(args: argparse.Namespace) -> NEngineConfig:
    config = NEngineConfig()
    overrides: dict[str, Any] = {}
    if args.config:
        overrides.update(load_json(Path(args.config)))
    if args.min_sector_pairs > 0:
        overrides["min_sector_pairs"] = args.min_sector_pairs
    if args.max_n > 0:
        overrides["max_n_years"] = args.max_n
    allowed = set(config.to_dict())
    unknown = sorted(set(overrides) - allowed)
    if unknown:
        raise SystemExit(f"Unknown N config fields: {', '.join(unknown)}")
    return replace(config, **overrides)


def main() -> None:
    args = parse_args()
    panel_path = Path(args.panel)
    output_path = Path(args.output)
    panel = load_financial_panel(panel_path)
    print(
        f"[N ENGINE] panel={panel_path} | "
        f"observations={len(panel.get('observations') or []):,}",
        flush=True,
    )
    payload = FinancialNEstimator(build_config(args)).estimate(panel)
    atomic_write_json(output_path, payload, compact=True)
    summary = payload["summary"]
    print(
        f"[N ENGINE] output={output_path} | "
        f"companies={summary['company_count']:,} | "
        f"sectors={summary['sector_group_count']:,} | "
        f"status={summary['status_counts']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
