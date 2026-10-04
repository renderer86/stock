from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from collector_common import atomic_write_json


# 2026-09 네이버 증권 개편으로 finance.naver.com/sise/sise_market_sum.naver 가
# stock.naver.com 으로 리다이렉트된다. 새 PC 화면이 쓰는 JSON API에서 종목
# 재무 지표를 받고, 이 API가 제외하는 ETF·ETN 등은 모바일 시가총액 API로 보완한다.
BASE_URL = "https://stock.naver.com/market/stock/kr/stocklist/capitalization"
STOCK_LIST_API_URL = "https://stock.naver.com/api/domestic/market/stock/default"
MOBILE_MARKET_VALUE_API_URL = "https://m.stock.naver.com/api/stocks/marketValue/{market}"
DETAIL_URL = "https://stock.naver.com/domestic/stock/{code}"
DEFAULT_OUTPUT = Path("data/market_sum.json")
DEFAULT_ROE_OUTPUT = Path("data/market_sum_by_roe.json")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)
STOCK_PAGE_SIZE = 100
MOBILE_PAGE_SIZE = 100
REQUEST_RETRIES = 3
# 정상 수집 시 코스피 약 940, 코스닥 약 1,820 종목이다. 응답 구조가 바뀌어
# 일부만 받아진 경우 기존 JSON을 덮어쓰지 않도록 실패 처리한다.
MIN_STOCKS_PER_MARKET = 500

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


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text or text.upper() == "N/A" or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: Any) -> int | None:
    number = parse_float(value)
    return None if number is None else int(number)


def scaled_int(value: Any, divisor: int) -> int | None:
    number = parse_float(value)
    return None if number is None else int(round(number / divisor))


def abs_int(value: Any) -> int | None:
    number = parse_int(value)
    return None if number is None else abs(number)


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Referer": BASE_URL,
            "Accept": "application/json",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )
    return session


def get_json(session: requests.Session, url: str, params: dict[str, Any]) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            response = session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < REQUEST_RETRIES:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Naver API request failed: {url} {params}: {last_error}")


def stock_row(item: dict[str, Any], market_info: dict[str, str], page: int) -> dict[str, Any]:
    code = str(item.get("itemcode") or "").strip()
    stock = {
        "market": market_info["market"],
        "market_label": market_info["market_label"],
        "sosok": market_info["sosok"],
        "page": page,
        "rank": None,
        "name": str(item.get("itemname") or "").strip(),
        "code": code,
        "detail_url": DETAIL_URL.format(code=code),
        "security_type": item.get("type"),
        "current_price": parse_int(item.get("nowPrice")),
        "diff": abs_int(item.get("prevChangePrice")),
        "diff_rate": parse_float(item.get("prevChangeRate")),
        # 새 API는 액면가를 제공하지 않는다. 0은 펀드형(ETF 등) 표시로 쓰이므로
        # 일반 종목은 None으로 둔다.
        "par_value": None,
        "market_cap_krw_100m": scaled_int(item.get("marketSum"), 100_000_000),
        "property_total_krw_100m": parse_int(item.get("propertyTotal")),
        "debt_total_krw_100m": parse_int(item.get("debtTotal")),
        "sales_krw_100m": parse_int(item.get("sales")),
        "sales_increasing_rate": parse_float(item.get("salesIncreasingRate")),
        "operating_profit_krw_100m": parse_int(item.get("operatingProfit")),
        "operating_profit_increasing_rate": parse_float(
            item.get("operatingProfitIncreasingRate")
        ),
        "net_income_krw_100m": parse_int(item.get("netIncome")),
        "eps": parse_int(item.get("eps")),
        "dividend": parse_int(item.get("dividend")),
        "per": parse_float(item.get("per")),
        "roe": parse_float(item.get("roe")),
        "roa": parse_float(item.get("roa")),
        "pbr": parse_float(item.get("pbr")),
        "reserve_ratio": parse_int(item.get("reserveRatio")),
        "volume": parse_int(item.get("tradeVolume")),
        "foreigner_ratio": parse_float(item.get("frgnHoldRate")),
        # 기존 네이버 화면과 같은 천 주 단위로 저장한다.
        "listed_shares": scaled_int(item.get("listedStockCnt"), 1_000),
        "trade_stop": item.get("tradeStopYn") == "Y",
    }
    # 새 API는 적자 기업의 PER을 null로 준다. 기존 화면처럼 음수 PER을 유지한다.
    if stock["per"] is None and stock["eps"] and stock["current_price"]:
        stock["per"] = round(stock["current_price"] / stock["eps"], 2)
    stock["is_suspended"] = stock["trade_stop"] or (
        stock.get("volume") == 0
        and stock.get("diff") == 0
        and stock.get("diff_rate") == 0
    )
    return stock


def fund_row(item: dict[str, Any], market_info: dict[str, str], page: int) -> dict[str, Any]:
    code = str(item.get("itemCode") or "").strip()
    price = parse_int(item.get("closePriceRaw") or item.get("closePrice"))
    market_cap_raw = parse_float(item.get("marketValueRaw"))
    listed_shares = (
        int(round(market_cap_raw / price / 1_000))
        if market_cap_raw and price
        else None
    )
    stock = {
        "market": market_info["market"],
        "market_label": market_info["market_label"],
        "sosok": market_info["sosok"],
        "page": page,
        "rank": None,
        "name": str(item.get("stockName") or "").strip(),
        "code": code,
        "detail_url": DETAIL_URL.format(code=code),
        "security_type": item.get("stockEndType"),
        "current_price": price,
        "diff": abs_int(
            item.get("compareToPreviousClosePriceRaw")
            or item.get("compareToPreviousClosePrice")
        ),
        "diff_rate": parse_float(item.get("fluctuationsRatio")),
        "par_value": 0,
        "market_cap_krw_100m": parse_int(item.get("marketValue")),
        "property_total_krw_100m": None,
        "debt_total_krw_100m": None,
        "sales_krw_100m": None,
        "sales_increasing_rate": None,
        "operating_profit_krw_100m": None,
        "operating_profit_increasing_rate": None,
        "net_income_krw_100m": None,
        "eps": None,
        "dividend": None,
        "per": None,
        "roe": None,
        "roa": None,
        "pbr": None,
        "reserve_ratio": None,
        "volume": parse_int(
            item.get("accumulatedTradingVolumeRaw")
            or item.get("accumulatedTradingVolume")
        ),
        "foreigner_ratio": None,
        "listed_shares": listed_shares,
        "trade_stop": (item.get("tradeStopType") or {}).get("name") not in (None, "TRADING"),
    }
    stock["is_suspended"] = stock["trade_stop"] or (
        stock.get("volume") == 0
        and stock.get("diff") == 0
        and stock.get("diff_rate") == 0
    )
    return stock


def crawl_stock_list(
    session: requests.Session,
    market_info: dict[str, str],
    delay: float,
    progress_every: int,
) -> tuple[int, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    page_index = 0
    while True:
        items = get_json(
            session,
            STOCK_LIST_API_URL,
            {
                "tradeType": "KRX",
                "marketType": market_info["market"],
                "orderType": "marketSum",
                # startIdx 는 행 위치가 아니라 0부터 시작하는 페이지 번호다.
                "startIdx": page_index,
                "pageSize": STOCK_PAGE_SIZE,
            },
        )
        if not isinstance(items, list):
            raise RuntimeError(f"Unexpected stock list response: {type(items).__name__}")
        page_index += 1
        rows.extend(stock_row(item, market_info, page_index) for item in items)
        if page_index == 1 or page_index % max(progress_every, 1) == 0 or len(items) < STOCK_PAGE_SIZE:
            print(
                f"[NAVER] {market_info['market']} stock list page {page_index} | rows {len(rows):,}",
                flush=True,
            )
        if len(items) < STOCK_PAGE_SIZE:
            break
        time.sleep(delay)
    return page_index, rows


def crawl_mobile_market_value(
    session: requests.Session,
    market_info: dict[str, str],
    delay: float,
    progress_every: int,
) -> tuple[int, list[dict[str, Any]]]:
    url = MOBILE_MARKET_VALUE_API_URL.format(market=market_info["market"])
    items: list[dict[str, Any]] = []
    page = 1
    total_count: int | None = None
    while True:
        payload = get_json(session, url, {"page": page, "pageSize": MOBILE_PAGE_SIZE})
        stocks = payload.get("stocks") if isinstance(payload, dict) else None
        if not isinstance(stocks, list):
            raise RuntimeError("Unexpected mobile market value response")
        total_count = parse_int(payload.get("totalCount")) or total_count
        items.extend({**stock, "_page": page} for stock in stocks)
        if page == 1 or page % max(progress_every, 1) == 0:
            print(
                f"[NAVER] {market_info['market']} market value page {page} | "
                f"rows {len(items):,}/{total_count or '?'}",
                flush=True,
            )
        if not stocks or len(stocks) < MOBILE_PAGE_SIZE or (
            total_count is not None and len(items) >= total_count
        ):
            break
        page += 1
        time.sleep(delay)
    return page, items


def crawl_market(
    session: requests.Session,
    market_info: dict[str, str],
    delay: float,
    progress_every: int,
) -> tuple[int, list[dict[str, Any]]]:
    market_started_at = time.monotonic()
    stock_pages, stocks = crawl_stock_list(session, market_info, delay, progress_every)
    if len(stocks) < MIN_STOCKS_PER_MARKET:
        raise RuntimeError(
            f"{market_info['market']} returned only {len(stocks)} stocks; "
            "the Naver API response may have changed."
        )

    _, mobile_items = crawl_mobile_market_value(session, market_info, delay, progress_every)
    known_codes = {stock["code"] for stock in stocks}
    funds = [
        fund_row(item, market_info, item["_page"])
        for item in mobile_items
        if str(item.get("itemCode") or "").strip() not in known_codes
    ]

    merged = [row for row in stocks + funds if row["code"]]
    merged.sort(
        key=lambda item: (
            item.get("market_cap_krw_100m") is None,
            -(item.get("market_cap_krw_100m") or 0),
        )
    )
    for rank, row in enumerate(merged, start=1):
        row["rank"] = rank

    print(
        f"[NAVER] {market_info['market']} completed: {len(stocks):,} stocks + "
        f"{len(funds):,} ETF/ETN/other in {time.monotonic() - market_started_at:.1f}s",
        flush=True,
    )
    return stock_pages, merged


def crawl_all(
    delay: float,
    progress_every: int,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    session = create_session()
    pages_by_market: dict[str, int] = {}
    all_stocks: list[dict[str, Any]] = []
    started_at = time.monotonic()

    for market_index, market_info in enumerate(MARKETS, start=1):
        print(
            f"[NAVER] Market {market_index}/{len(MARKETS)}: "
            f"{market_info['market']} ({market_info['market_label']})",
            flush=True,
        )
        total_pages, stocks = crawl_market(
            session,
            market_info,
            delay,
            progress_every,
        )
        pages_by_market[market_info["market"]] = total_pages
        all_stocks.extend(stocks)

    all_stocks.sort(
        key=lambda item: (
            item.get("market") != "KOSPI",
            item.get("rank") is None,
            item.get("rank") or 999999,
        )
    )
    print(
        f"[NAVER] All markets collected: {len(all_stocks):,} stocks, "
        f"{time.monotonic() - started_at:.1f}s elapsed",
        flush=True,
    )
    return pages_by_market, all_stocks


def write_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect Naver market cap and valuation data for KOSPI and KOSDAQ."
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
        help="Sleep time between API requests in seconds.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=5,
        help="Print progress after this many pages (default: 5).",
    )
    args = parser.parse_args()

    pages_by_market, stocks = crawl_all(
        delay=args.delay,
        progress_every=max(args.progress_every, 1),
    )
    crawled_at = datetime.now(timezone.utc).isoformat()
    sources = [
        f"{STOCK_LIST_API_URL}?marketType=KOSPI",
        f"{STOCK_LIST_API_URL}?marketType=KOSDAQ",
        MOBILE_MARKET_VALUE_API_URL.format(market="KOSPI"),
        MOBILE_MARKET_VALUE_API_URL.format(market="KOSDAQ"),
    ]

    all_payload = {
        "source": sources,
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
        "source": sources,
        "sort": "roe_desc",
        "markets": MARKETS,
        "field_groups": FIELD_GROUPS,
        "pages_by_market": pages_by_market,
        "count": len(roe_sorted),
        "crawled_at_utc": crawled_at,
        "stocks": roe_sorted,
    }

    print(
        f"[NAVER] Writing {len(stocks):,} stocks to {args.output}...",
        flush=True,
    )
    write_json(Path(args.output), all_payload)
    print(f"[NAVER] Writing ROE-sorted data to {args.roe_output}...", flush=True)
    write_json(Path(args.roe_output), roe_payload)

    print(f"Pages by market: {pages_by_market}", flush=True)
    print(f"Total stocks: {len(stocks)}", flush=True)
    print(f"Full output: {args.output}", flush=True)
    print(f"ROE output: {args.roe_output}", flush=True)


if __name__ == "__main__":
    main()
