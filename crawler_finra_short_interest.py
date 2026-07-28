from __future__ import annotations

import argparse
import csv
from io import StringIO
from pathlib import Path
from typing import Any

import requests

from collector_common import USER_AGENT, atomic_write_json, request_json, utc_now_iso


API_URL = (
    "https://api.finra.org/data/group/OTCMarket/name/consolidatedShortInterest"
)
PARTITIONS_URL = (
    "https://api.finra.org/partitions/group/OTCMarket/name/consolidatedShortInterest"
)
DEFAULT_OUTPUT = Path("data/us_finra_short_interest.json")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect the latest FINRA consolidated U.S. short-interest positions."
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit", type=int, default=50000)
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    partitions = request_json(
        session,
        "GET",
        PARTITIONS_URL,
    )
    dates = [
        str(item["partitions"][0])
        for item in partitions.get("availablePartitions", [])
        if item.get("partitions")
    ]
    latest_date = max(dates) if dates else ""
    if not latest_date:
        raise RuntimeError("FINRA short-interest API returned no partitions.")

    rows: list[dict[str, Any]] = []
    page_size = min(5_000, max(1, args.limit))
    while len(rows) < args.limit:
        body: dict[str, Any] = {
            "limit": min(page_size, args.limit - len(rows)),
            "offset": len(rows),
            "dateRangeFilters": [
                {
                    "fieldName": "settlementDate",
                    "startDate": latest_date,
                    "endDate": latest_date,
                }
            ],
        }
        response = session.post(API_URL, json=body, timeout=60)
        response.raise_for_status()
        if response.text.lstrip().startswith("["):
            parsed = response.json()
            batch = parsed if isinstance(parsed, list) else []
        else:
            batch = list(csv.DictReader(StringIO(response.text)))
        if not batch and not rows:
            raise RuntimeError(
                "FINRA returned no data rows: "
                + response.text[:500].replace("\n", " ")
            )
        rows.extend(batch)
        if len(batch) < body["limit"]:
            break

    normalized: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbolCode") or "").strip().upper()
        current = row.get("currentShortPositionQuantity")
        average_volume = row.get("averageDailyVolumeQuantity")
        try:
            short_ratio = (
                round(float(current) / float(average_volume), 2)
                if current is not None and float(average_volume) > 0
                else None
            )
        except (TypeError, ValueError):
            short_ratio = None
        normalized.append(
            {
                **row,
                "symbol": symbol,
                "calculated_days_to_cover": short_ratio,
            }
        )

    normalized.sort(
        key=lambda row: row.get("currentShortPositionQuantity") or 0,
        reverse=True,
    )
    payload = {
        "source": "FINRA Consolidated Short Interest API",
        "settlement_date": latest_date,
        "crawled_at_utc": utc_now_iso(),
        "count": len(normalized),
        "rows": normalized,
    }
    atomic_write_json(Path(args.output), payload, compact=True)
    print(f"Settlement date: {latest_date}")
    print(f"Rows: {len(normalized)}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
