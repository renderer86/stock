from __future__ import annotations

import argparse
import io
import json
import os
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import requests


CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
MAJOR_STOCK_URL = "https://opendart.fss.or.kr/api/majorstock.json"
DEFAULT_MARKET_PATH = Path("data/market_sum_by_roe.json")
DEFAULT_ROE_PATH = Path("data/fnguide_roe_history.json")
DEFAULT_OUTPUT = Path("data/dart_major_holders.json")
DEFAULT_API_KEY_ENV = "DART_API_KEY"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)


@dataclass
class DartTarget:
    code: str
    name: str
    market: str | None
    market_label: str | None
    recommended_roe_base: float | None
    pbr: float | None
    estimated_n_base: int | None
    market_implied_n: float | None
    current_price: int | None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def standard_deviation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = average(values) or 0.0
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return variance ** 0.5


def clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def market_implied_pbr(roe_percent: float, years: int, discount_rate: float = 0.1) -> float | None:
    roe = roe_percent / 100
    if roe <= 0:
        return None
    if years <= 0:
        return 1.0

    bps = 1.0
    price = 0.0
    for year in range(1, years + 1):
        eps = bps * roe
        price += eps / ((1 + discount_rate) ** year)
        bps += eps

    price += bps / ((1 + discount_rate) ** years)
    return price


def estimate_market_implied_n(stock: dict[str, Any]) -> float | None:
    roe = stock.get("roe")
    pbr = stock.get("pbr")
    if not isinstance(roe, (int, float)) or not isinstance(pbr, (int, float)):
        return None
    if roe <= 0 or pbr <= 0:
        return None
    if pbr <= 1:
        return 0.0

    previous_years = 0
    previous_value = market_implied_pbr(roe, previous_years)
    if previous_value is None:
        return None

    for years in range(1, 51):
        current_value = market_implied_pbr(roe, years)
        if current_value is None:
            return None
        if current_value >= pbr:
            range_value = current_value - previous_value
            if range_value <= 0:
                return float(years)
            ratio = (pbr - previous_value) / range_value
            return round(previous_years + ratio, 1)
        previous_years = years
        previous_value = current_value

    return 50.0


def get_roe_values(history: dict[str, Any] | None, current_roe: float | None) -> list[float]:
    if history:
        full_years = [
            item["roe"]
            for item in history.get("full_years", [])
            if isinstance(item.get("roe"), (int, float))
        ]
        if len(full_years) >= 2:
            return full_years

        roe_values = [value for value in history.get("roe_values", []) if isinstance(value, (int, float))]
        if roe_values:
            return roe_values

    if isinstance(current_roe, (int, float)):
        return [float(current_roe)]
    return []


def infer_roe_base(stock: dict[str, Any], history: dict[str, Any] | None) -> float | None:
    values = get_roe_values(history, stock.get("roe"))
    result = average(values)
    return round(result, 2) if result is not None else None


def estimate_financial_n(stock: dict[str, Any], values: list[float]) -> int:
    avg_roe = average(values)
    roe_std = standard_deviation(values)
    high_roe_years = sum(value >= 15 for value in values)
    under_ten_years = sum(value < 10 for value in values)
    score = 0.0

    if avg_roe is not None:
        if avg_roe >= 20:
            score += 2
        elif avg_roe >= 15:
            score += 1

    if roe_std <= 3:
        score += 2
    elif roe_std <= 6:
        score += 1

    if values and high_roe_years == len(values):
        score += 2
    elif high_roe_years >= max(2, len(values) - 1):
        score += 1

    if under_ten_years == 0 and len(values) >= 3:
        score += 1

    sales_growth = stock.get("sales_increasing_rate")
    if isinstance(sales_growth, (int, float)):
        if sales_growth >= 10:
            score += 1
        elif sales_growth >= 0:
            score += 0.5

    op_growth = stock.get("operating_profit_increasing_rate")
    if isinstance(op_growth, (int, float)):
        if op_growth >= 10:
            score += 1
        elif op_growth >= 0:
            score += 0.5

    roa = stock.get("roa")
    if isinstance(roa, (int, float)):
        if roa >= 8:
            score += 1
        elif roa >= 5:
            score += 0.5

    reserve_ratio = stock.get("reserve_ratio")
    if isinstance(reserve_ratio, (int, float)):
        if reserve_ratio >= 1000:
            score += 1
        elif reserve_ratio >= 300:
            score += 0.5

    debt_total = stock.get("debt_total_krw_100m")
    property_total = stock.get("property_total_krw_100m")
    if (
        isinstance(debt_total, (int, float))
        and isinstance(property_total, (int, float))
        and property_total > 0
    ):
        debt_ratio = debt_total / property_total
        if debt_ratio <= 0.5:
            score += 1
        elif debt_ratio <= 1:
            score += 0.5

    if score >= 9:
        return 10
    if score >= 7:
        return 8
    if score >= 5:
        return 6
    if score >= 3:
        return 4
    return 2


def get_dart_targets(
    market_payload: dict[str, Any],
    roe_payload: dict[str, Any],
    scope: str,
    min_roe: float,
) -> list[DartTarget]:
    roe_map = {item["code"]: item for item in roe_payload.get("stocks", []) if item.get("code")}
    targets: list[DartTarget] = []

    for stock in market_payload.get("stocks", []):
        current_roe = stock.get("roe")
        if not isinstance(current_roe, (int, float)):
            continue
        if scope in {"roe", "priority"} and current_roe < min_roe:
            continue

        history = roe_map.get(stock.get("code"))
        roe_values = get_roe_values(history, current_roe)
        roe_base = infer_roe_base(stock, history)
        pbr = stock.get("pbr")
        estimated_n = estimate_financial_n(stock, roe_values) if roe_values else None
        market_n = estimate_market_implied_n(stock)

        if scope == "priority":
            if roe_base is None or roe_base < 15:
                continue
            if not isinstance(pbr, (int, float)) or pbr > 2:
                continue
            if market_n is None or estimated_n is None or estimated_n <= market_n:
                continue

        targets.append(
            DartTarget(
                code=str(stock["code"]).zfill(6),
                name=stock.get("name", ""),
                market=stock.get("market"),
                market_label=stock.get("market_label"),
                recommended_roe_base=roe_base,
                pbr=float(pbr) if isinstance(pbr, (int, float)) else None,
                estimated_n_base=int(estimated_n) if estimated_n is not None else None,
                market_implied_n=float(market_n) if market_n is not None else None,
                current_price=stock.get("current_price"),
            )
        )

    targets.sort(
        key=lambda item: (
            item.recommended_roe_base is None,
            -(item.recommended_roe_base or 0),
            item.pbr is None,
            item.pbr or 0,
        )
    )
    return targets


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )
    return session


def fetch_corp_code_map(session: requests.Session, api_key: str) -> dict[str, dict[str, str]]:
    response = session.get(CORP_CODE_URL, params={"crtfc_key": api_key}, timeout=30)
    response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        xml_name = archive.namelist()[0]
        with archive.open(xml_name) as xml_file:
            root = ElementTree.fromstring(xml_file.read())

    mapping: dict[str, dict[str, str]] = {}
    for item in root.findall("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        corp_code = (item.findtext("corp_code") or "").strip()
        corp_name = (item.findtext("corp_name") or "").strip()
        if stock_code and corp_code:
            mapping[stock_code] = {
                "corp_code": corp_code,
                "corp_name": corp_name,
            }

    return mapping


def parse_major_holders_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "000":
        return {
            "status": payload.get("status"),
            "message": payload.get("message"),
            "has_major_holders": False,
            "holders": [],
        }

    rows = payload.get("list") or []
    latest_by_reporter: dict[str, dict[str, Any]] = {}
    for row in rows:
        reporter_name = row.get("repror") or row.get("nm") or row.get("report_resn") or row.get("rcept_no")
        ratio_text = row.get("stkrt") or row.get("stkqy_irds_rt") or row.get("trmend_irds_rt")
        ratio = None
        if isinstance(ratio_text, str):
            match = re.search(r"-?\d+(?:\.\d+)?", ratio_text.replace(",", ""))
            if match:
                ratio = float(match.group(0))

        report_date = row.get("rcept_dt") or row.get("report_dt")
        if not reporter_name:
            continue

        holder = {
            "holder_name": reporter_name,
            "report_date": report_date,
            "ratio": ratio,
            "raw": row,
        }

        previous = latest_by_reporter.get(reporter_name)
        previous_date = (previous or {}).get("report_date") or ""
        current_date = report_date or ""
        if previous is None or current_date >= previous_date:
            latest_by_reporter[reporter_name] = holder

    holders = [
        holder
        for holder in latest_by_reporter.values()
        if holder["ratio"] is not None and holder["ratio"] >= 5
    ]

    holders.sort(
        key=lambda item: (
            item["ratio"] is None,
            -(item["ratio"] or 0),
            -(int(str(item["report_date"]).replace("-", "")) if item["report_date"] else 0),
        )
    )

    latest_report_date = max((holder["report_date"] for holder in holders if holder["report_date"]), default=None)
    return {
        "status": "000",
        "message": payload.get("message"),
        "has_major_holders": bool(holders),
        "holders": holders,
        "top_holder_name": holders[0]["holder_name"] if holders else None,
        "top_holder_ratio": holders[0]["ratio"] if holders else None,
        "latest_report_date": latest_report_date,
    }


def fetch_major_holders(session: requests.Session, api_key: str, corp_code: str) -> dict[str, Any]:
    response = session.get(
        MAJOR_STOCK_URL,
        params={
            "crtfc_key": api_key,
            "corp_code": corp_code,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return parse_major_holders_payload(payload)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch OpenDART 5% major holder disclosures for dashboard stocks."
    )
    parser.add_argument("--market-data", default=str(DEFAULT_MARKET_PATH), help="Path to market_sum_by_roe.json")
    parser.add_argument("--roe-history", default=str(DEFAULT_ROE_PATH), help="Path to fnguide_roe_history.json")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Path to output JSON")
    parser.add_argument("--api-key", default="", help="OpenDART API key")
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV, help="Environment variable for OpenDART API key")
    parser.add_argument("--scope", choices=["roe", "priority", "all"], default="roe", help="Target scope: ROE table, priority ideas, or all stocks")
    parser.add_argument("--min-roe", type=float, default=10.0, help="Minimum current ROE for scope=roe")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on number of target stocks")
    parser.add_argument("--delay", type=float, default=0.2, help="Sleep time between OpenDART requests in seconds")
    args = parser.parse_args()

    api_key = args.api_key.strip() or os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(
            f"OpenDART API key is required. Pass --api-key or set {args.api_key_env}."
        )

    market_payload = load_json(Path(args.market_data))
    roe_payload = load_json(Path(args.roe_history))
    candidates = get_dart_targets(market_payload, roe_payload, args.scope, args.min_roe)
    if args.limit > 0:
        candidates = candidates[: args.limit]

    session = create_session()
    corp_map = fetch_corp_code_map(session, api_key)

    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        corp_info = corp_map.get(candidate.code)
        if not corp_info:
            rows.append(
                {
                    "code": candidate.code,
                    "name": candidate.name,
                    "market_label": candidate.market_label,
                    "error": "corp_code_not_found",
                    "has_major_holders": False,
                }
            )
            print(f"[{index}/{len(candidates)}] MISS {candidate.code} {candidate.name} -> corp_code not found")
            continue

        try:
            major = fetch_major_holders(session, api_key, corp_info["corp_code"])
            rows.append(
                {
                    "code": candidate.code,
                    "name": candidate.name,
                    "market_label": candidate.market_label,
                    "corp_code": corp_info["corp_code"],
                    "corp_name": corp_info["corp_name"],
                    "priority_snapshot": {
                        "recommended_roe_base": candidate.recommended_roe_base,
                        "pbr": candidate.pbr,
                        "estimated_n_base": candidate.estimated_n_base,
                        "market_implied_n": candidate.market_implied_n,
                        "current_price": candidate.current_price,
                    },
                    **major,
                }
            )
            print(f"[{index}/{len(candidates)}] OK {candidate.code} {candidate.name}")
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "code": candidate.code,
                    "name": candidate.name,
                    "market_label": candidate.market_label,
                    "corp_code": corp_info["corp_code"],
                    "corp_name": corp_info["corp_name"],
                    "error": str(exc),
                    "has_major_holders": False,
                }
            )
            print(f"[{index}/{len(candidates)}] FAIL {candidate.code} {candidate.name} -> {exc}")

        time.sleep(args.delay)

    payload = {
        "source": "OpenDART majorstock.json",
        "scope": args.scope,
        "min_roe": args.min_roe,
        "count": len(rows),
        "crawled_at_utc": datetime.now(timezone.utc).isoformat(),
        "stocks": rows,
    }
    write_json(Path(args.output), payload)

    print(f"Output: {args.output}")
    print(f"Rows: {len(rows)}")


if __name__ == "__main__":
    main()
