from __future__ import annotations

import argparse
import csv
import json
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import Any

import requests


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT_DIR / "data" / "us_finra_short_volume.json"
PARTITIONS_URL = (
    "https://api.finra.org/partitions/group/OTCMarket/name/regShoDaily"
)
DATA_URL = "https://api.finra.org/data/group/OTCMarket/name/regShoDaily"
SOURCE_PAGE = "https://www.finra.org/finra-data/daily-short-sale-volume-transaction-data"
REQUEST_TIMEOUT = 45
PAGE_SIZE = 5_000
USER_AGENT = "stock-dashboard/1.0 (+https://github.com/renderer86/stock)"


class FinraCrawlerError(RuntimeError):
    pass


def decimal_value(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except InvalidOperation:
        return Decimal(0)


def integer_value(value: Decimal) -> int:
    return int(value.quantize(Decimal("1")))


def latest_trade_date(session: requests.Session) -> str:
    response = session.get(PARTITIONS_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    dates = [
        str(item["partitions"][0])
        for item in payload.get("availablePartitions", [])
        if item.get("partitions")
    ]
    if not dates:
        raise FinraCrawlerError("FINRA 최신 거래일 파티션을 찾지 못했습니다.")
    return max(dates)


def fetch_trade_rows(
    session: requests.Session,
    trade_date: str,
    *,
    max_pages: int,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for page in range(max_pages):
        body = {
            "limit": PAGE_SIZE,
            "compareFilters": [
                {
                    "compareType": "equal",
                    "fieldName": "tradeReportDate",
                    "fieldValue": trade_date,
                }
            ],
        }
        if page > 0:
            body["offset"] = page * PAGE_SIZE
        response = session.post(
            DATA_URL,
            json=body,
            timeout=REQUEST_TIMEOUT,
        )
        if not response.ok:
            detail = response.text.strip()
            raise FinraCrawlerError(
                f"FINRA HTTP {response.status_code}: {detail[:500]}"
            )
        batch = list(csv.DictReader(StringIO(response.text)))
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows

    raise FinraCrawlerError(
        f"FINRA 응답이 {max_pages * PAGE_SIZE:,}행을 초과했습니다. "
        "--max-pages 값을 늘리세요."
    )


def aggregate_symbols(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "short_volume": Decimal(0),
            "short_exempt_volume": Decimal(0),
            "total_volume": Decimal(0),
            "market_codes": set(),
            "reporting_facilities": set(),
        }
    )

    for row in rows:
        symbol = str(
            row.get("securitiesInformationProcessorSymbolIdentifier", "")
        ).strip().upper()
        if not symbol:
            continue
        item = totals[symbol]
        item["short_volume"] += decimal_value(row.get("shortParQuantity"))
        item["short_exempt_volume"] += decimal_value(
            row.get("shortExemptParQuantity")
        )
        item["total_volume"] += decimal_value(row.get("totalParQuantity"))
        if row.get("marketCode"):
            item["market_codes"].add(str(row["marketCode"]))
        if row.get("reportingFacilityCode"):
            item["reporting_facilities"].add(str(row["reportingFacilityCode"]))

    result: list[dict[str, Any]] = []
    for symbol, item in totals.items():
        short_volume = integer_value(item["short_volume"])
        total_volume = integer_value(item["total_volume"])
        result.append(
            {
                "symbol": symbol,
                "short_volume": short_volume,
                "short_exempt_volume": integer_value(
                    item["short_exempt_volume"]
                ),
                "total_volume": total_volume,
                "short_volume_ratio": (
                    round(short_volume / total_volume * 100, 2)
                    if total_volume > 0
                    else None
                ),
                "market_codes": sorted(item["market_codes"]),
                "reporting_facilities": sorted(item["reporting_facilities"]),
            }
        )

    return sorted(
        result,
        key=lambda item: (item["short_volume"], item["total_volume"]),
        reverse=True,
    )


def write_json_atomic(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temp_file:
        json.dump(payload, temp_file, ensure_ascii=False, indent=2)
        temp_file.write("\n")
        temp_path = Path(temp_file.name)
    temp_path.replace(output_path)


def crawl(output_path: Path, *, max_pages: int) -> dict[str, Any]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    trade_date = latest_trade_date(session)
    raw_rows = fetch_trade_rows(session, trade_date, max_pages=max_pages)
    symbols = aggregate_symbols(raw_rows)
    payload = {
        "schema_version": 1,
        "source": "FINRA Reg SHO Daily Short Sale Volume",
        "source_url": SOURCE_PAGE,
        "api_url": DATA_URL,
        "trade_date": trade_date,
        "crawled_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_row_count": len(raw_rows),
        "symbol_count": len(symbols),
        "notice": (
            "FINRA 장외 보고 거래량이며 전체 거래소 공매도 잔고와 동일하지 않습니다."
        ),
        "symbols": symbols,
    }
    write_json_atomic(output_path, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FINRA 공개 API에서 최신 미국 일일 공매도 거래량을 수집합니다."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="FINRA 5,000행 페이지의 최대 요청 수",
    )
    args = parser.parse_args()
    output_path = args.output
    if not output_path.is_absolute():
        output_path = ROOT_DIR / output_path

    try:
        payload = crawl(output_path, max_pages=args.max_pages)
    except (requests.RequestException, FinraCrawlerError) as error:
        raise SystemExit(f"[FAIL] FINRA 공매도 거래량 수집: {error}") from None

    print(
        "[DONE] FINRA 공매도 거래량 "
        f"({payload['trade_date']} · {payload['symbol_count']:,}종목 · "
        f"{payload['raw_row_count']:,}행)"
    )
    print(f"[SAVE] {output_path}")


if __name__ == "__main__":
    main()
