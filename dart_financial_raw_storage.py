from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from collector_common import atomic_write_json, utc_now_iso


RAW_SCHEMA_VERSION = 1
DEFAULT_RAW_ROOT = Path("data/dart_financial_raw")


def ticker_bucket(ticker: str) -> str:
    normalized = str(ticker or "").strip().zfill(6)
    return normalized[0] if normalized and normalized[0].isdigit() else "x"


def _relative_reference(raw_root: Path, path: Path) -> str:
    return (Path(raw_root.name) / path.relative_to(raw_root)).as_posix()


def _gzip_json_bytes(payload: Any) -> bytes:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return gzip.compress(serialized, compresslevel=9, mtime=0)


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def read_gzip_json(path: Path) -> dict[str, Any]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Failed to read raw DART shard {path}: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def _write_raw_shard(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    content = _gzip_json_bytes(payload)
    _atomic_write_bytes(path, content)
    return {
        "path": path.as_posix(),
        "compressed_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "row_count": int(payload.get("row_count") or 0),
    }


def _load_index(raw_root: Path) -> dict[str, Any]:
    index_path = raw_root / "index.json"
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def update_raw_index(
    raw_root: Path,
    entries: list[dict[str, Any]],
    *,
    replace_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = _load_index(raw_root)
    by_path = {
        str(entry.get("path") or ""): entry
        for entry in existing.get("shards") or []
        if entry.get("path")
        and not (
            replace_scope
            and all(entry.get(key) == value for key, value in replace_scope.items())
        )
    }
    for entry in entries:
        by_path[str(entry["path"])] = entry
    shards = sorted(
        by_path.values(),
        key=lambda item: (
            int(item.get("year") or 0),
            str(item.get("source_type") or ""),
            str(item.get("dataset") or ""),
            str(item.get("basis") or ""),
            str(item.get("bucket") or ""),
        ),
    )
    payload = {
        "schema_version": RAW_SCHEMA_VERSION,
        "updated_at_utc": utc_now_iso(),
        "root": raw_root.as_posix(),
        "storage": "gzip JSON shards",
        "row_count": sum(int(item.get("row_count") or 0) for item in shards),
        "compressed_bytes": sum(
            int(item.get("compressed_bytes") or 0) for item in shards
        ),
        "shard_count": len(shards),
        "shards": shards,
    }
    atomic_write_json(raw_root / "index.json", payload, compact=True)
    return payload


def write_bulk_raw_shards(
    raw_root: Path,
    *,
    year: int,
    statement: str,
    source_file: str,
    raw_groups: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, dict[str, str]]]]:
    """Write every original TXT row and return manifest entries plus ticker refs."""

    entries: list[dict[str, Any]] = []
    current_paths: set[Path] = set()
    references: dict[str, dict[str, dict[str, str]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for (basis, bucket), table in sorted(raw_groups.items()):
        rows = table.get("rows") or []
        shard_path = (
            raw_root
            / str(year)
            / "bulk"
            / f"{statement}_{basis}_{bucket}.json.gz"
        )
        current_paths.add(shard_path)
        payload = {
            "schema_version": RAW_SCHEMA_VERSION,
            "dataset": "financial_statement",
            "source_type": "bulk_zip",
            "source_url": (
                "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do"
            ),
            "source_file": source_file,
            "source_entry": table.get("source_entry"),
            "source_encoding": table.get("source_encoding"),
            "fiscal_year": year,
            "statement": statement,
            "basis": basis,
            "ticker_bucket": bucket,
            "header": table.get("header") or [],
            "row_count": len(rows),
            "rows": rows,
        }
        metadata = _write_raw_shard(shard_path, payload)
        reference = _relative_reference(raw_root, shard_path)
        entries.append(
            {
                **metadata,
                "path": reference,
                "year": year,
                "dataset": "financial_statement",
                "source_type": "bulk_zip",
                "source_file": source_file,
                "statement": statement,
                "basis": basis,
                "bucket": bucket,
            }
        )
        for ticker in table.get("tickers") or []:
            references[str(ticker)][basis][statement] = reference
    statement_directory = raw_root / str(year) / "bulk"
    for stale_path in statement_directory.glob(f"{statement}_*.json.gz"):
        if stale_path not in current_paths:
            stale_path.unlink()
    update_raw_index(
        raw_root,
        entries,
        replace_scope={
            "year": year,
            "dataset": "financial_statement",
            "source_type": "bulk_zip",
            "statement": statement,
        },
    )
    return entries, {
        ticker: {basis: dict(statements) for basis, statements in bases.items()}
        for ticker, bases in references.items()
    }


class ApiRawAccumulator:
    """Checkpointable, source-preserving storage for OpenDART API responses."""

    def __init__(self, raw_root: Path = DEFAULT_RAW_ROOT) -> None:
        self.raw_root = raw_root
        self._payloads: dict[tuple[int, str, str, str], dict[str, Any]] = {}
        self._dirty: set[tuple[int, str, str, str]] = set()

    def _key(
        self,
        year: int,
        dataset: str,
        basis: str,
        ticker: str,
    ) -> tuple[int, str, str, str]:
        return year, dataset, basis or "NA", ticker_bucket(ticker)

    def _path(self, key: tuple[int, str, str, str]) -> Path:
        year, dataset, basis, bucket = key
        return self.raw_root / str(year) / "api" / f"{dataset}_{basis}_{bucket}.json.gz"

    def _payload(self, key: tuple[int, str, str, str]) -> dict[str, Any]:
        if key not in self._payloads:
            year, dataset, basis, bucket = key
            path = self._path(key)
            payload = read_gzip_json(path)
            if not payload:
                payload = {
                    "schema_version": RAW_SCHEMA_VERSION,
                    "dataset": dataset,
                    "source_type": "opendart_api",
                    "fiscal_year": year,
                    "basis": basis,
                    "ticker_bucket": bucket,
                    "records_by_ticker": {},
                }
            self._payloads[key] = payload
        return self._payloads[key]

    def add(
        self,
        *,
        year: int,
        dataset: str,
        ticker: str,
        corp_code: str,
        basis: str = "NA",
        endpoint: str,
        request_parameters: dict[str, Any],
        response_status: str,
        rows: list[dict[str, Any]],
    ) -> str:
        key = self._key(year, dataset, basis, ticker)
        payload = self._payload(key)
        payload["source_url"] = endpoint
        records = payload.setdefault("records_by_ticker", {})
        records[str(ticker)] = {
            "ticker": str(ticker),
            "corp_code": str(corp_code),
            "request_parameters": request_parameters,
            "response_status": response_status,
            "rows": rows,
        }
        payload["row_count"] = sum(
            len(record.get("rows") or []) for record in records.values()
        )
        self._dirty.add(key)
        return _relative_reference(self.raw_root, self._path(key))

    def flush(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for key in sorted(self._dirty):
            year, dataset, basis, bucket = key
            payload = self._payloads[key]
            path = self._path(key)
            metadata = _write_raw_shard(path, payload)
            entries.append(
                {
                    **metadata,
                    "path": _relative_reference(self.raw_root, path),
                    "year": year,
                    "dataset": dataset,
                    "source_type": "opendart_api",
                    "basis": basis,
                    "bucket": bucket,
                }
            )
        if entries:
            update_raw_index(self.raw_root, entries)
        self._dirty.clear()
        return entries
