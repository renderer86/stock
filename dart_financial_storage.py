from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from collector_common import atomic_write_json


STORAGE_SCHEMA_VERSION = 1


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Failed to read financial panel JSON: {path}: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def financial_shard_directory(panel_path: Path) -> Path:
    return panel_path.with_suffix("")


def load_financial_panel(panel_path: Path) -> dict[str, Any]:
    """Load either the legacy monolith or the year-sharded panel."""

    panel = _read_json(panel_path)
    storage = panel.get("storage") or {}
    if storage.get("mode") != "year_shards":
        return panel

    observations: list[dict[str, Any]] = []
    for shard in storage.get("shards") or []:
        relative_path = str(shard.get("path") or "").strip()
        if not relative_path:
            continue
        shard_payload = _read_json(panel_path.parent / relative_path)
        shard_rows = shard_payload.get("observations") or []
        if not isinstance(shard_rows, list):
            raise RuntimeError(
                f"Expected observations list in financial shard: {relative_path}"
            )
        observations.extend(shard_rows)

    expected = int(storage.get("observation_count") or len(observations))
    if len(observations) != expected:
        raise RuntimeError(
            "Financial panel shard count mismatch: "
            f"expected {expected:,}, loaded {len(observations):,}."
        )
    panel["observations"] = observations
    return panel


def save_financial_panel(
    panel_path: Path,
    panel: dict[str, Any],
    *,
    split_by_year: bool = True,
) -> None:
    """Persist a compact index plus one JSON file per fiscal year."""

    if not split_by_year:
        atomic_write_json(panel_path, panel, compact=True)
        return

    observations = panel.get("observations") or []
    if not isinstance(observations, list):
        raise ValueError("Financial panel observations must be a list.")

    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        year = int(row.get("fiscal_year") or 0)
        if year > 0:
            by_year[year].append(row)

    shard_dir = financial_shard_directory(panel_path)
    shard_dir.mkdir(parents=True, exist_ok=True)
    shards: list[dict[str, Any]] = []
    for year, rows in sorted(by_year.items()):
        rows.sort(key=lambda item: str(item.get("ticker") or ""))
        shard_path = shard_dir / f"{year}.json"
        atomic_write_json(
            shard_path,
            {
                "schema_version": STORAGE_SCHEMA_VERSION,
                "fiscal_year": year,
                "count": len(rows),
                "observations": rows,
            },
            compact=True,
        )
        shards.append(
            {
                "year": year,
                "path": shard_path.relative_to(panel_path.parent).as_posix(),
                "count": len(rows),
            }
        )

    index_payload = {key: value for key, value in panel.items() if key != "observations"}
    index_payload["storage"] = {
        "schema_version": STORAGE_SCHEMA_VERSION,
        "mode": "year_shards",
        "observation_count": len(observations),
        "shards": shards,
        "note": (
            "Annual observations are split by fiscal year to stay below GitHub's "
            "single-file size limit. Use dart_financial_storage.load_financial_panel."
        ),
    }
    atomic_write_json(panel_path, index_payload, compact=True)
