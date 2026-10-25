"""Reparse committed DART sources locally after parser/calculation changes."""
from __future__ import annotations

from collections import defaultdict
import argparse
from pathlib import Path

from crawler_dart_financial_bulk import calculation_rows_from_raw_groups, merge_bulk_year
from crawler_dart_financial_details import SCREEN_METRICS_VERSION, load_market_lookup, rebuild_screening_features, update_detail_summary
from dart_financial_raw_storage import read_gzip_json
from dart_financial_storage import load_financial_panel, save_financial_panel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    panel_path = Path("data/dart_financial_panel.json")
    panel = load_financial_panel(panel_path)
    if not args.force and panel.get("screen_metrics_version") == SCREEN_METRICS_VERSION:
        print("[REBUILD] Parser and screening metrics are current.", flush=True)
        return
    observations = panel.get("observations") or []
    if not observations:
        raise SystemExit("Financial panel has no observations.")
    for year in sorted({r["fiscal_year"] for r in observations}):
        combined = defaultdict(list)
        filenames = []
        for statement in ("BS", "PL", "CF"):
            for path in sorted((Path("data/dart_financial_raw") / str(year) / "bulk").glob(f"{statement}_*.json.gz")):
                raw = read_gzip_json(path)
                parsed, _ = calculation_rows_from_raw_groups({(raw["basis"], raw["ticker_bucket"]): raw}, statement)
                for key, rows in parsed.items():
                    combined[key].extend(rows)
                if raw.get("source_file") not in filenames:
                    filenames.append(raw.get("source_file"))
        if not combined:
            raise SystemExit(f"Missing committed bulk sources for {year}; panel was not saved.")
        result = merge_bulk_year(observations, year, combined, filenames)
        print(f"[REBUILD] {year}: {result}", flush=True)
    market, as_of = load_market_lookup(Path("data/market_sum.json"))
    rebuild_screening_features(panel, market, as_of)
    update_detail_summary(panel, request_count=0, errors=[], eligible_rows=observations, budget_reached=False)
    panel["screen_metrics_version"] = SCREEN_METRICS_VERSION
    save_financial_panel(panel_path, panel, split_by_year=True)
    print("[REBUILD] Repaired panel and screening features saved.", flush=True)


if __name__ == "__main__":
    main()
