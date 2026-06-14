from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://finance.naver.com/sise/sise_market_sum.naver"
FIELD_SUBMIT_URL = "https://finance.naver.com/sise/field_submit.naver"
DEFAULT_OUTPUT = Path("data/market_sum.json")
DEFAULT_ROE_OUTPUT = Path("data/market_sum_by_roe.json")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)

MARKETS = [
    {"sosok": "0", "market": "KOSPI", "market_label": "코스피"},
    {"sosok": "1", "market": "KOSDAQ", "market_label": "코스닥"},
]

FIELD_GROUPS: list[list[str]] = [
    [
        "market_sum",
        "property_total",
        "debt_total",
        "sales",
        "sales_increasing_rate",
        "operating_profit",
    ],
    [
        "operating_profit_increasing_rate",
        "net_income",
        "eps",
        "dividend",
        "per",
        "roe",
    ],
    [
        "quant",
        "frgn_rate",
        "listed_stock_cnt",
        "roa",
        "pbr",
        "reserve_ratio",
    ],
]

FIELD_LABELS = {
    "market_sum": "시가총액",
    "property_total": "자산총계",
    "debt_total": "부채총계",
    "sales": "매출액",
    "sales_increasing_rate": "매출액증가율",
    "operating_profit": "영업이익",
    "operating_profit_increasing_rate": "영업이익증가율",
    "net_income": "당기순이익",
    "eps": "주당순이익",
    "dividend": "보통주배당금",
    "per": "PER",
    "roe": "ROE",
    "quant": "거래량",
    "frgn_rate": "외국인비율",
    "listed_stock_cnt": "상장주식수",
    "roa": "ROA",
    "pbr": "PBR",
    "reserve_ratio": "유보율",
}

HEADER_TO_FIELD_ID = {label: field_id for field_id, label in FIELD_LABELS.items()}
FIELD_OUTPUT_KEYS = {
    "market_sum": "market_cap_krw_100m",
    "property_total": "property_total_krw_100m",
    "debt_total": "debt_total_krw_100m",
    "sales": "sales_krw_100m",
    "sales_increasing_rate": "sales_increasing_rate",
    "operating_profit": "operating_profit_krw_100m",
    "operating_profit_increasing_rate": "operating_profit_increasing_rate",
    "net_income": "net_income_krw_100m",
    "eps": "eps",
    "dividend": "dividend",
    "per": "per",
    "roe": "roe",
    "roa": "roa",
    "pbr": "pbr",
    "reserve_ratio": "reserve_ratio",
    "quant": "volume",
    "frgn_rate": "foreigner_ratio",
    "listed_stock_cnt": "listed_shares",
}


def clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def extract_number_text(value: str) -> str:
    text = clean_text(value).replace(",", "").replace("%", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return match.group(0) if match else ""


def parse_float(value: str) -> float | None:
    text = extract_number_text(value)
    if not text or text.upper() == "N/A":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: str) -> int | None:
    text = extract_number_text(value)
    if not text or text.upper() == "N/A":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_by_field(field_id: str, value: str) -> float | int | None:
    float_fields = {
        "sales_increasing_rate",
        "operating_profit_increasing_rate",
        "roe",
        "roa",
        "pbr",
        "per",
        "frgn_rate",
    }
    return parse_float(value) if field_id in float_fields else parse_int(value)


def extract_code(href: str) -> str:
    query = parse_qs(urlparse(href).query)
    return query.get("code", [""])[0]


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Referer": BASE_URL,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )
    return session


def fetch_page(session: requests.Session, page: int, sosok: str) -> str:
    response = session.get(BASE_URL, params={"page": page, "sosok": sosok}, timeout=20)
    response.raise_for_status()
    response.encoding = "euc-kr"
    return response.text


def apply_field_selection(session: requests.Session, field_ids: list[str], page: int, sosok: str) -> None:
    body: list[tuple[str, str]] = [
        ("menu", "market_sum"),
        (
            "returnUrl",
            f"http://finance.naver.com/sise/sise_market_sum.naver?page={page}&sosok={sosok}",
        ),
    ]
    body.extend(("fieldIds", field_id) for field_id in field_ids)

    response = session.post(FIELD_SUBMIT_URL, data=body, timeout=20)
    response.raise_for_status()


def get_total_pages(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")

    last_link = soup.select_one("td.pgRR a")
    if last_link and last_link.get("href"):
        match = re.search(r"page=(\d+)", last_link["href"])
        if match:
            return int(match.group(1))

    page_numbers: list[int] = []
    for anchor in soup.select("table.Nnavi a[href*='page=']"):
        match = re.search(r"page=(\d+)", anchor.get("href", ""))
        if match:
            page_numbers.append(int(match.group(1)))

    if page_numbers:
        return max(page_numbers)

    raise RuntimeError("Failed to detect the last page.")


def extract_selected_field_ids(soup: BeautifulSoup) -> list[str]:
    headers = [clean_text(th.get_text(" ", strip=True)) for th in soup.select("table.type_2 thead th")]
    dynamic_headers = headers[6:-1]

    selected_field_ids: list[str] = []
    for header in dynamic_headers:
        field_id = HEADER_TO_FIELD_ID.get(header)
        if not field_id:
            raise RuntimeError(f"Unknown header label: {header}")
        selected_field_ids.append(field_id)

    return selected_field_ids


def parse_stock_rows(html: str, page: int, market_info: dict[str, str]) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    selected_field_ids = extract_selected_field_ids(soup)
    stocks: list[dict[str, Any]] = []

    for row in soup.select("table.type_2 tr"):
        name_link = row.select_one("a.tltle")
        if not name_link:
            continue

        cells = [clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all("td")]
        required_len = 6 + len(selected_field_ids) + 1
        if len(cells) < required_len:
            continue

        code = extract_code(name_link.get("href", ""))
        raw_selected: dict[str, str] = {}
        parsed_selected: dict[str, float | int | None] = {}

        for offset, field_id in enumerate(selected_field_ids):
            raw_value = cells[6 + offset]
            raw_selected[field_id] = raw_value
            parsed_selected[FIELD_OUTPUT_KEYS[field_id]] = parse_by_field(field_id, raw_value)

        stock = {
            "market": market_info["market"],
            "market_label": market_info["market_label"],
            "sosok": market_info["sosok"],
            "page": page,
            "rank": parse_int(cells[0]),
            "name": clean_text(name_link.get_text(strip=True)),
            "code": code,
            "detail_url": urljoin(BASE_URL, f"/item/main.naver?code={code}"),
            "current_price": parse_int(cells[2]),
            "diff": parse_int(cells[3]),
            "diff_rate": parse_float(cells[4]),
            "par_value": parse_int(cells[5]),
            **parsed_selected,
            "raw": {
                "current_price": cells[2],
                "diff": cells[3],
                "diff_rate": cells[4],
                "par_value": cells[5],
                **raw_selected,
            },
        }
        stock["is_suspended"] = (
            stock.get("volume") == 0
            and stock.get("diff") == 0
            and stock.get("diff_rate") == 0
        )
        stocks.append(stock)

    return stocks


def merge_stock_maps(base: dict[str, dict[str, Any]], updates: list[dict[str, Any]]) -> None:
    for stock in updates:
        code = stock["code"]
        current = base.get(code)
        if current is None:
            base[code] = stock
            continue

        for key, value in stock.items():
            if key == "raw":
                current.setdefault("raw", {}).update(value)
                continue
            if value is not None:
                current[key] = value


def crawl_field_group(
    session: requests.Session,
    field_ids: list[str],
    market_info: dict[str, str],
    total_pages: int,
    delay: float,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for page in range(1, total_pages + 1):
        apply_field_selection(session, field_ids, page, market_info["sosok"])
        html = fetch_page(session, page, market_info["sosok"])
        results.extend(parse_stock_rows(html, page, market_info))
        time.sleep(delay)

    return results


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def crawl_market(session: requests.Session, market_info: dict[str, str], delay: float) -> tuple[int, list[dict[str, Any]]]:
    first_html = fetch_page(session, 1, market_info["sosok"])
    total_pages = get_total_pages(first_html)

    merged: dict[str, dict[str, Any]] = {}
    for field_ids in FIELD_GROUPS:
        grouped_rows = crawl_field_group(session, field_ids, market_info, total_pages, delay)
        merge_stock_maps(merged, grouped_rows)

    stocks = sorted(
        merged.values(),
        key=lambda item: (item.get("rank") is None, item.get("rank") or 999999),
    )
    return total_pages, stocks


def crawl_all(delay: float) -> tuple[dict[str, int], list[dict[str, Any]]]:
    session = create_session()
    pages_by_market: dict[str, int] = {}
    all_stocks: list[dict[str, Any]] = []

    for market_info in MARKETS:
        total_pages, stocks = crawl_market(session, market_info, delay)
        pages_by_market[market_info["market"]] = total_pages
        all_stocks.extend(stocks)

    all_stocks.sort(
        key=lambda item: (
            item.get("market") != "KOSPI",
            item.get("rank") is None,
            item.get("rank") or 999999,
        )
    )
    return pages_by_market, all_stocks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl Naver market cap pages for both KOSPI and KOSDAQ."
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Path for the merged full JSON output.",
    )
    parser.add_argument(
        "--roe-output",
        default=str(DEFAULT_ROE_OUTPUT),
        help="Path for the ROE-sorted JSON output.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Sleep time between page requests in seconds.",
    )
    args = parser.parse_args()

    pages_by_market, stocks = crawl_all(delay=args.delay)
    crawled_at = datetime.now(timezone.utc).isoformat()

    all_payload = {
        "source": [f"{BASE_URL}?sosok=0", f"{BASE_URL}?sosok=1"],
        "markets": MARKETS,
        "field_groups": FIELD_GROUPS,
        "pages_by_market": pages_by_market,
        "count": len(stocks),
        "crawled_at_utc": crawled_at,
        "stocks": stocks,
    }

    roe_sorted = sorted(
        stocks,
        key=lambda item: (
            item.get("roe") is None,
            -(item.get("roe") or 0),
            item.get("market") != "KOSPI",
            item.get("rank") or 999999,
        ),
    )
    roe_payload = {
        "source": [f"{BASE_URL}?sosok=0", f"{BASE_URL}?sosok=1"],
        "sort": "roe_desc",
        "markets": MARKETS,
        "field_groups": FIELD_GROUPS,
        "pages_by_market": pages_by_market,
        "count": len(roe_sorted),
        "crawled_at_utc": crawled_at,
        "stocks": roe_sorted,
    }

    write_json(Path(args.output), all_payload)
    write_json(Path(args.roe_output), roe_payload)

    print(f"Pages by market: {pages_by_market}")
    print(f"Total stocks: {len(stocks)}")
    print(f"Full output: {args.output}")
    print(f"ROE output: {args.roe_output}")


if __name__ == "__main__":
    main()
