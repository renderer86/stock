from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT_DIR / "data" / "naver_etf_brands.json"
NAVER_ETF_API_URL = "https://finance.naver.com/api/sise/etfItemList.nhn"
NAVER_ETF_PAGE_URL = "https://finance.naver.com/sise/etf.naver"
REQUEST_TIMEOUT = 30
DEFAULT_BRANDS = ("KoAct", "TIME")


class EtfCrawlerError(RuntimeError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def normalize_brands(brands: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()

    for brand in brands:
        value = brand.strip()
        key = value.casefold()
        if value and key not in seen:
            normalized.append(value)
            seen.add(key)

    if not normalized:
        raise EtfCrawlerError("ETF 브랜드를 한 개 이상 지정하세요.")
    return normalized


def fetch_all_etfs(session: requests.Session) -> list[dict[str, Any]]:
    response = session.get(
        NAVER_ETF_API_URL,
        params={
            "etfType": 0,
            "targetColumn": "market_sum",
            "sortOrder": "desc",
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    response.encoding = "euc-kr"

    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError as error:
        raise EtfCrawlerError("네이버 ETF JSON 응답을 해석하지 못했습니다.") from error

    if payload.get("resultCode") != "success":
        raise EtfCrawlerError(
            f"네이버 ETF API 오류: {payload.get('resultCode', 'unknown')}"
        )

    rows = payload.get("result", {}).get("etfItemList")
    if not isinstance(rows, list):
        raise EtfCrawlerError("네이버 ETF 응답에 종목 목록이 없습니다.")
    return [row for row in rows if isinstance(row, dict)]


def parse_number(value: Any, *, integer: bool = False) -> int | float | None:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).replace(",", ""))
    except ValueError:
        return None
    return int(number) if integer else number


def direction_from_change(change_rate: float | None) -> str:
    if change_rate is None or change_rate == 0:
        return "flat"
    return "up" if change_rate > 0 else "down"


def parse_etf(row: dict[str, Any], brand: str) -> dict[str, Any]:
    name = str(row.get("itemname", "")).strip()
    code = str(row.get("itemcode", "")).strip()
    current_price = parse_number(row.get("nowVal"), integer=True)
    change_value = parse_number(row.get("changeVal"), integer=True)
    change_rate = parse_number(row.get("changeRate"))

    if not name or not code or current_price is None or change_rate is None:
        raise EtfCrawlerError(f"{brand} ETF 필수 필드가 비어 있습니다: {name or code}")

    short_name = name[len(brand) :].strip() if name.casefold().startswith(
        brand.casefold()
    ) else name

    return {
        "code": code,
        "name": name,
        "short_name": short_name,
        "current_price": current_price,
        "change_value": change_value,
        "change_rate": change_rate,
        "direction": direction_from_change(change_rate),
        "rise_fall_code": str(row.get("risefall", "")),
        "nav": parse_number(row.get("nav")),
        "volume": parse_number(row.get("quant"), integer=True),
        "trading_value_krw_1m": parse_number(row.get("amonut"), integer=True),
        "market_cap_krw_100m": parse_number(row.get("marketSum"), integer=True),
        "naver_url": f"https://finance.naver.com/item/main.naver?code={code}",
    }


def select_brand_etfs(
    rows: list[dict[str, Any]],
    brand: str,
) -> list[dict[str, Any]]:
    prefix = brand.casefold()
    selected = [
        parse_etf(row, brand)
        for row in rows
        if str(row.get("itemname", "")).strip().casefold().startswith(prefix)
    ]
    if not selected:
        raise EtfCrawlerError(f"'{brand}'로 시작하는 ETF를 찾지 못했습니다.")
    return selected


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


def crawl_etf_brands(
    *,
    brands: list[str],
    output_path: Path,
) -> dict[str, Any]:
    selected_brands = normalize_brands(brands)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/126.0 ETFBrandTicker/1.0"
            ),
            "Referer": NAVER_ETF_PAGE_URL,
        }
    )

    rows = fetch_all_etfs(session)
    payload = {
        "schema_version": 1,
        "crawled_at_utc": utc_now_iso(),
        "source": "Naver Finance ETF",
        "source_url": NAVER_ETF_PAGE_URL,
        "brands": [
            {
                "brand": brand,
                "count": len(etfs),
                "etfs": etfs,
            }
            for brand in selected_brands
            for etfs in [select_brand_etfs(rows, brand)]
        ],
    }
    write_json_atomic(output_path, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "네이버 금융 ETF 전체 목록에서 지정한 브랜드 종목의 현재가와 "
            "등락률을 수집합니다."
        )
    )
    parser.add_argument(
        "brands",
        nargs="*",
        default=list(DEFAULT_BRANDS),
        help="수집할 ETF 이름 접두어. 예: KoAct TIME",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="생성할 JSON 경로",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output_path = args.output
    if not output_path.is_absolute():
        output_path = ROOT_DIR / output_path

    try:
        payload = crawl_etf_brands(brands=args.brands, output_path=output_path)
    except (requests.RequestException, EtfCrawlerError) as error:
        raise SystemExit(f"[FAIL] 네이버 ETF 브랜드 수집: {error}") from None

    summary = " · ".join(
        f"{brand['brand']} {brand['count']}개" for brand in payload["brands"]
    )
    print(f"[DONE] 네이버 ETF 브랜드 수집 ({summary})")
    print(f"[SAVE] {output_path}")


if __name__ == "__main__":
    main()
