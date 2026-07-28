from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from collector_common import atomic_write_json, utc_now_iso


DATA_DIR = Path("data")
OUTPUT = DATA_DIR / "data_manifest.json"


def first_value(payload: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in payload:
            return payload[name]
    return None


def main() -> None:
    files: list[dict[str, Any]] = []
    for path in sorted(DATA_DIR.glob("*.json")):
        if path == OUTPUT:
            continue
        item: dict[str, Any] = {
            "file": path.as_posix(),
            "bytes": path.stat().st_size,
        }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                item.update(
                    {
                        "source": payload.get("source"),
                        "count": first_value(
                            payload,
                            ("count", "symbol_count", "company_count"),
                        ),
                        "data_date": first_value(
                            payload,
                            (
                                "settlement_date",
                                "trade_date",
                                "crawled_at_utc",
                                "generated_at_utc",
                            ),
                        ),
                    }
                )
                if path.name == "krx_openapi.json":
                    item["dataset_status"] = {
                        name: dataset.get("status")
                        for name, dataset in (payload.get("datasets") or {}).items()
                    }
        except (OSError, ValueError) as exc:
            item["error"] = str(exc)
        files.append(item)

    manifest = {
        "generated_at_utc": utc_now_iso(),
        "file_count": len(files),
        "files": files,
    }
    atomic_write_json(OUTPUT, manifest)
    print(f"Output: {OUTPUT}")
    print(f"Files: {len(files)}")


if __name__ == "__main__":
    main()
