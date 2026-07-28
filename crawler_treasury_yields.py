from __future__ import annotations

import argparse
import csv
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any

import requests

from env_loader import load_env_file


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT_DIR / "data" / "treasury_yields.json"
ECOS_BASE_URL = "https://ecos.bok.or.kr/api/StatisticSearch"
ECOS_STAT_CODE = "817Y002"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
US_TREASURY_XML_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/pages/xml"
)
REQUEST_TIMEOUT = 30
FRED_REQUEST_TIMEOUT = 10
PAGE_SIZE = 1_000

# FRED H.15에서 제공하는 미국 명목 국채 Constant Maturity 일별 시계열 전체.
FRED_SERIES = (
    ("DGS1MO", "1M", "1개월", 1),
    ("DGS3MO", "3M", "3개월", 3),
    ("DGS6MO", "6M", "6개월", 6),
    ("DGS1", "1Y", "1년", 12),
    ("DGS2", "2Y", "2년", 24),
    ("DGS3", "3Y", "3년", 36),
    ("DGS5", "5Y", "5년", 60),
    ("DGS7", "7Y", "7년", 84),
    ("DGS10", "10Y", "10년", 120),
    ("DGS20", "20Y", "20년", 240),
    ("DGS30", "30Y", "30년", 360),
)

TREASURY_XML_FIELDS = {
    "DGS1MO": "BC_1MONTH",
    "DGS3MO": "BC_3MONTH",
    "DGS6MO": "BC_6MONTH",
    "DGS1": "BC_1YEAR",
    "DGS2": "BC_2YEAR",
    "DGS3": "BC_3YEAR",
    "DGS5": "BC_5YEAR",
    "DGS7": "BC_7YEAR",
    "DGS10": "BC_10YEAR",
    "DGS20": "BC_20YEAR",
    "DGS30": "BC_30YEAR",
}

KOREA_GOVERNMENT_BOND_PATTERN = re.compile(r"^국고채\s*\((\d+)년\)$")


class YieldCrawlerError(RuntimeError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def request_json(session: requests.Session, url: str) -> dict[str, Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    try:
        payload = response.json()
    except requests.JSONDecodeError as error:
        raise YieldCrawlerError("원격 JSON 응답을 해석하지 못했습니다.") from error

    if not isinstance(payload, dict):
        raise YieldCrawlerError("예상하지 못한 JSON 응답입니다.")
    return payload


def ecos_error_message(payload: dict[str, Any]) -> str | None:
    result = payload.get("RESULT")
    if not isinstance(result, dict):
        return None

    code = str(result.get("CODE", "UNKNOWN"))
    message = str(result.get("MESSAGE", "알 수 없는 오류")).strip()
    return f"ECOS API 오류 {code}: {message}"


def fetch_ecos_rows(
    session: requests.Session,
    api_key: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    def page_url(start: int, end: int) -> str:
        return (
            f"{ECOS_BASE_URL}/{api_key}/json/kr/{start}/{end}/"
            f"{ECOS_STAT_CODE}/D/{start_date}/{end_date}"
        )

    first_payload = request_json(session, page_url(1, PAGE_SIZE))
    error_message = ecos_error_message(first_payload)
    if error_message:
        raise YieldCrawlerError(error_message)

    container = first_payload.get("StatisticSearch")
    if not isinstance(container, dict):
        raise YieldCrawlerError("ECOS 응답에 StatisticSearch 데이터가 없습니다.")

    total_count = int(container.get("list_total_count", 0))
    rows = list(container.get("row") or [])

    for start in range(PAGE_SIZE + 1, total_count + 1, PAGE_SIZE):
        end = min(start + PAGE_SIZE - 1, total_count)
        payload = request_json(session, page_url(start, end))
        error_message = ecos_error_message(payload)
        if error_message:
            raise YieldCrawlerError(error_message)
        page = payload.get("StatisticSearch")
        if not isinstance(page, dict):
            raise YieldCrawlerError(f"ECOS {start}~{end}행 응답이 올바르지 않습니다.")
        rows.extend(page.get("row") or [])

    return [row for row in rows if isinstance(row, dict)]


def parse_float(value: Any) -> float | None:
    if value is None:
        return None

    normalized = str(value).strip().replace(",", "")
    if not normalized or normalized == ".":
        return None

    try:
        return float(normalized)
    except ValueError:
        return None


def observations_to_yield(
    observations: list[tuple[str, float]],
    *,
    maturity: str,
    label: str,
    months: int,
    series_id: str,
) -> dict[str, Any] | None:
    if not observations:
        return None

    observations.sort(key=lambda item: item[0])
    latest_date, latest_value = observations[-1]
    previous_date: str | None = None
    previous_value: float | None = None

    if len(observations) >= 2:
        previous_date, previous_value = observations[-2]

    change = (
        round(latest_value - previous_value, 4)
        if previous_value is not None
        else None
    )

    return {
        "maturity": maturity,
        "label": label,
        "months": months,
        "series_id": series_id,
        "date": latest_date,
        "value": latest_value,
        "previous_date": previous_date,
        "previous_value": previous_value,
        "change": change,
        "unit": "%",
    }


def parse_ecos_yields(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, int], list[tuple[str, float]]] = {}

    for row in rows:
        item_name = str(row.get("ITEM_NAME1", "")).strip()
        match = KOREA_GOVERNMENT_BOND_PATTERN.fullmatch(item_name)
        value = parse_float(row.get("DATA_VALUE"))
        date = str(row.get("TIME", "")).strip()

        if not match or value is None or not re.fullmatch(r"\d{8}", date):
            continue

        years = int(match.group(1))
        item_code = str(row.get("ITEM_CODE1", "")).strip()
        key = (item_code, item_name, years)
        grouped.setdefault(key, []).append((date, value))

    yields: list[dict[str, Any]] = []
    for (item_code, item_name, years), observations in grouped.items():
        parsed = observations_to_yield(
            observations,
            maturity=f"{years}Y",
            label=f"{years}년",
            months=years * 12,
            series_id=item_code,
        )
        if parsed:
            parsed["name"] = item_name
            yields.append(parsed)

    yields.sort(key=lambda item: item["months"])
    if not yields:
        raise YieldCrawlerError(
            "ECOS 응답에서 국고채 만기별 금리를 찾지 못했습니다."
        )
    return yields


def fetch_one_fred_yield(
    headers: dict[str, str],
    series: tuple[str, str, str, int],
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    series_id, maturity, label, months = series
    response = requests.get(
        FRED_CSV_URL,
        params={"id": series_id, "cosd": start_date, "coed": end_date},
        headers=headers,
        timeout=FRED_REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    reader = csv.DictReader(StringIO(response.text))
    observations: list[tuple[str, float]] = []
    for row in reader:
        date = str(row.get("observation_date") or row.get("DATE") or "").strip()
        value = parse_float(row.get(series_id))
        if date and value is not None:
            observations.append((date, value))

    parsed = observations_to_yield(
        observations,
        maturity=maturity,
        label=label,
        months=months,
        series_id=series_id,
    )
    if not parsed:
        raise YieldCrawlerError(f"FRED {series_id}에서 유효한 값을 찾지 못했습니다.")
    parsed["name"] = f"미국 국채 {label}"
    return parsed


def fetch_fred_yields(
    session: requests.Session,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    headers = {str(key): str(value) for key, value in session.headers.items()}
    with ThreadPoolExecutor(max_workers=len(FRED_SERIES)) as executor:
        futures = [
            executor.submit(
                fetch_one_fred_yield,
                headers,
                series,
                start_date,
                end_date,
            )
            for series in FRED_SERIES
        ]
        return [future.result() for future in futures]


def months_between(start: datetime, end: datetime) -> list[str]:
    year = start.year
    month = start.month
    result: list[str] = []
    while (year, month) <= (end.year, end.month):
        result.append(f"{year:04d}{month:02d}")
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return result


def fetch_us_treasury_fallback(
    session: requests.Session,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    observations_by_series: dict[str, list[tuple[str, float]]] = {
        series_id: [] for series_id in TREASURY_XML_FIELDS
    }
    atom_ns = "http://www.w3.org/2005/Atom"
    data_ns = "http://schemas.microsoft.com/ado/2007/08/dataservices"
    metadata_ns = "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"

    for year_month in months_between(start, end):
        response = session.get(
            US_TREASURY_XML_URL,
            params={
                "data": "daily_treasury_yield_curve",
                "field_tdr_date_value_month": year_month,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)

        for entry in root.findall(f"{{{atom_ns}}}entry"):
            properties = entry.find(
                f"{{{atom_ns}}}content/{{{metadata_ns}}}properties"
            )
            if properties is None:
                continue

            date_node = properties.find(f"{{{data_ns}}}NEW_DATE")
            if date_node is None or not date_node.text:
                continue
            date = date_node.text[:10]
            if date < start_date or date > end_date:
                continue

            for series_id, field_name in TREASURY_XML_FIELDS.items():
                value_node = properties.find(f"{{{data_ns}}}{field_name}")
                value = parse_float(value_node.text if value_node is not None else None)
                if value is not None:
                    observations_by_series[series_id].append((date, value))

    yields: list[dict[str, Any]] = []
    for series_id, maturity, label, months in FRED_SERIES:
        parsed = observations_to_yield(
            observations_by_series[series_id],
            maturity=maturity,
            label=label,
            months=months,
            series_id=series_id,
        )
        if not parsed:
            raise YieldCrawlerError(
                f"미국 재무부 피드에서 {label} 금리를 찾지 못했습니다."
            )
        parsed["name"] = f"미국 국채 {label}"
        yields.append(parsed)
    return yields


def latest_date(yields: list[dict[str, Any]]) -> str | None:
    dates = [str(item.get("date", "")) for item in yields if item.get("date")]
    return max(dates) if dates else None


def write_json_atomic(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
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


def crawl_treasury_yields(
    *,
    ecos_api_key: str,
    lookback_days: int,
    output_path: Path,
) -> dict[str, Any]:
    if not ecos_api_key.strip():
        raise YieldCrawlerError(
            "ECOS_API_KEY가 없습니다. 환경변수에 한국은행 ECOS 인증키를 설정하세요."
        )
    if lookback_days < 7:
        raise YieldCrawlerError("조회 기간은 휴일을 고려해 7일 이상이어야 합니다.")

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=lookback_days)
    start_compact = start.strftime("%Y%m%d")
    end_compact = end.strftime("%Y%m%d")
    start_iso = start.isoformat()
    end_iso = end.isoformat()

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/126.0 TreasuryYieldDashboard/1.0"
            )
        }
    )

    ecos_rows = fetch_ecos_rows(
        session,
        ecos_api_key.strip(),
        start_compact,
        end_compact,
    )
    korea_yields = parse_ecos_yields(ecos_rows)

    us_source = "FRED (Federal Reserve H.15)"
    us_source_url = "https://fred.stlouisfed.org/"
    us_provider = "fred"
    try:
        us_yields = fetch_fred_yields(session, start_iso, end_iso)
    except (requests.RequestException, YieldCrawlerError):
        print(
            "[WARN] FRED 응답 실패. 미국 재무부 공식 XML 피드로 대체합니다.",
            flush=True,
        )
        us_yields = fetch_us_treasury_fallback(session, start_iso, end_iso)
        us_source = "U.S. Treasury (FRED fallback)"
        us_source_url = (
            "https://home.treasury.gov/resource-center/data-chart-center/"
            "interest-rates/"
        )
        us_provider = "us_treasury_fallback"

    payload = {
        "schema_version": 1,
        "crawled_at_utc": utc_now_iso(),
        "markets": {
            "korea": {
                "country": "대한민국",
                "source": "한국은행 ECOS",
                "source_url": "https://ecos.bok.or.kr/",
                "stat_code": ECOS_STAT_CODE,
                "frequency": "일별",
                "as_of_date": latest_date(korea_yields),
                "yields": korea_yields,
            },
            "united_states": {
                "country": "미국",
                "source": us_source,
                "source_url": us_source_url,
                "preferred_source": "FRED (Federal Reserve H.15)",
                "provider": us_provider,
                "frequency": "일별",
                "as_of_date": latest_date(us_yields),
                "yields": us_yields,
            },
        },
    }
    write_json_atomic(output_path, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="한국 ECOS와 미국 FRED에서 국채 금리 전체 만기를 수집합니다."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="생성할 JSON 경로",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=21,
        help="최근 유효값과 전일값을 찾기 위한 조회 기간",
    )
    parser.add_argument(
        "--ecos-api-key",
        default=os.environ.get("ECOS_API_KEY", ""),
        help="ECOS 인증키. 보안을 위해 ECOS_API_KEY 환경변수 사용을 권장합니다.",
    )
    return parser


def main() -> None:
    load_env_file(ROOT_DIR / ".env")
    args = build_parser().parse_args()
    output_path = args.output
    if not output_path.is_absolute():
        output_path = ROOT_DIR / output_path

    try:
        payload = crawl_treasury_yields(
            ecos_api_key=args.ecos_api_key,
            lookback_days=args.lookback_days,
            output_path=output_path,
        )
    except (requests.RequestException, YieldCrawlerError) as error:
        safe_message = str(error)
        if args.ecos_api_key:
            safe_message = safe_message.replace(str(args.ecos_api_key), "***")
        raise SystemExit(f"[FAIL] 국채 금리 수집: {safe_message}") from None

    korea = payload["markets"]["korea"]
    united_states = payload["markets"]["united_states"]
    print(
        "[DONE] 국채 금리 수집 "
        f"(한국 {len(korea['yields'])}개 · {korea['as_of_date']}, "
        f"미국 {len(united_states['yields'])}개 · "
        f"{united_states['as_of_date']})"
    )
    print(f"[SAVE] {output_path}")


if __name__ == "__main__":
    main()
