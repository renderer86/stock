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
DEFAULT_OUTPUT = Path("data/market_sum.json")
DEFAULT_ROE_OUTPUT = Path("data/market_sum_by_roe.json")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)


def clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def parse_float(value: str) -> float | None:
    text = clean_text(value).replace(",", "").replace("%", "")
    if not text or text.upper() == "N/A":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: str) -> int | None:
    text = clean_text(value).replace(",", "")
    if not text or text.upper() == "N/A":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def extract_code(href: str) -> str:
    query = parse_qs(urlparse(href).query)
    return query.get("code", [""])[0]


def fetch_page(session: requests.Session, page: int) -> str:
    response = session.get(BASE_URL, params={"page": page}, timeout=20)
    response.raise_for_status()
    response.encoding = "euc-kr"
    return response.text


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

    raise RuntimeError("총 페이지 수를 찾지 못했습니다.")


def parse_stock_rows(html: str, page: int) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    stocks: list[dict[str, Any]] = []

    for row in soup.select("table.type_2 tr"):
        name_link = row.select_one("a.tltle")
        if not name_link:
            continue

        cells = [clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all("td")]
        if len(cells) < 12:
            continue

        code = extract_code(name_link.get("href", ""))
        stock = {
            "page": page,
            "rank": parse_int(cells[0]),
            "name": clean_text(name_link.get_text(strip=True)),
            "code": code,
            "detail_url": urljoin(BASE_URL, f"/item/main.naver?code={code}"),
            "current_price": parse_int(cells[2]),
            "diff": parse_int(cells[3]),
            "diff_rate": parse_float(cells[4]),
            "par_value": parse_int(cells[5]),
            "market_cap_krw_100m": parse_int(cells[6]),
            "listed_shares": parse_int(cells[7]),
            "foreigner_ratio": parse_float(cells[8]),
            "volume": parse_int(cells[9]),
            "per": parse_float(cells[10]),
            "roe": parse_float(cells[11]),
            "raw": {
                "current_price": cells[2],
                "diff": cells[3],
                "diff_rate": cells[4],
                "par_value": cells[5],
                "market_cap_krw_100m": cells[6],
                "listed_shares": cells[7],
                "foreigner_ratio": cells[8],
                "volume": cells[9],
                "per": cells[10],
                "roe": cells[11],
            },
        }
        stocks.append(stock)

    return stocks


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def crawl_all(delay: float) -> tuple[int, list[dict[str, Any]]]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Referer": BASE_URL,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )

    first_html = fetch_page(session, 1)
    total_pages = get_total_pages(first_html)
    all_stocks = parse_stock_rows(first_html, 1)

    for page in range(2, total_pages + 1):
        time.sleep(delay)
        html = fetch_page(session, page)
        all_stocks.extend(parse_stock_rows(html, page))

    return total_pages, all_stocks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="네이버 금융 시가총액 페이지를 끝페이지까지 수집합니다."
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="전체 데이터를 저장할 JSON 경로",
    )
    parser.add_argument(
        "--roe-output",
        default=str(DEFAULT_ROE_OUTPUT),
        help="ROE 내림차순 데이터를 저장할 JSON 경로",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="페이지 요청 사이 대기 시간(초)",
    )
    args = parser.parse_args()

    total_pages, stocks = crawl_all(delay=args.delay)
    crawled_at = datetime.now(timezone.utc).isoformat()

    all_payload = {
        "source": BASE_URL,
        "total_pages": total_pages,
        "count": len(stocks),
        "crawled_at_utc": crawled_at,
        "stocks": stocks,
    }

    roe_sorted = sorted(
        stocks,
        key=lambda item: (item["roe"] is None, -(item["roe"] or 0), item["rank"] or 999999),
    )
    roe_payload = {
        "source": BASE_URL,
        "sort": "roe_desc",
        "total_pages": total_pages,
        "count": len(roe_sorted),
        "crawled_at_utc": crawled_at,
        "stocks": roe_sorted,
    }

    write_json(Path(args.output), all_payload)
    write_json(Path(args.roe_output), roe_payload)

    print(f"총 페이지 수: {total_pages}")
    print(f"수집 종목 수: {len(stocks)}")
    print(f"전체 데이터 저장: {args.output}")
    print(f"ROE 정렬 데이터 저장: {args.roe_output}")


if __name__ == "__main__":
    main()
