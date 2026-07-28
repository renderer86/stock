from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from collector_common import USER_AGENT, atomic_write_json, request_json, utc_now_iso
from env_loader import load_env_file


ROOT_DIR = Path(__file__).resolve().parent
API_URL = "https://opendart.fss.or.kr/api/list.json"
DEFAULT_OUTPUT = Path("data/dart_disclosures.json")

CATEGORIES = {
    "ownership": ("대량보유", "임원ㆍ주요주주", "주식등의대량보유"),
    "buyback": ("자기주식취득", "자기주식처분", "자기주식소각"),
    "earnings": ("영업(잠정)실적", "매출액또는손익구조"),
    "dividend": ("현금ㆍ현물배당", "배당결정"),
    "contract": ("단일판매ㆍ공급계약", "공급계약체결"),
    "capital": ("유상증자", "무상증자", "전환사채", "신주인수권부사채", "교환사채"),
    "major_event": ("합병", "분할", "영업양수", "영업양도", "부도", "회생절차"),
}


def classify(report_name: str) -> list[str]:
    return [
        category
        for category, keywords in CATEGORIES.items()
        if any(keyword in report_name for keyword in keywords)
    ]


def main() -> None:
    load_env_file(ROOT_DIR / ".env")
    parser = argparse.ArgumentParser(description="Collect recent KOSPI/KOSDAQ OpenDART filings.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Recent calendar-day window. Seven days matches the Mir full-market method.",
    )
    parser.add_argument("--max-pages", type=int, default=60)
    args = parser.parse_args()

    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DART_API_KEY is not set.")

    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    begin = today - timedelta(days=max(1, args.days))
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    filings: list[dict[str, Any]] = []
    total_pages = 1
    for page in range(1, max(1, args.max_pages) + 1):
        payload = request_json(
            session,
            "GET",
            API_URL,
            params={
                "crtfc_key": api_key,
                "bgn_de": begin.strftime("%Y%m%d"),
                "end_de": today.strftime("%Y%m%d"),
                "page_no": page,
                "page_count": 100,
                "sort": "date",
                "sort_mth": "desc",
            },
        )
        status = str(payload.get("status") or "")
        if status == "013":
            break
        if status != "000":
            raise RuntimeError(
                f"OpenDART error {status}: {payload.get('message', 'unknown error')}"
            )
        total_pages = int(payload.get("total_page") or 1)
        for item in payload.get("list") or []:
            if item.get("corp_cls") not in {"Y", "K"}:
                continue
            report_name = str(item.get("report_nm") or "")
            receipt_number = str(item.get("rcept_no") or "")
            filings.append(
                {
                    **item,
                    "categories": classify(report_name),
                    "dart_url": (
                        f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_number}"
                        if receipt_number
                        else None
                    ),
                }
            )
        print(f"[DART] page {page}/{total_pages}, rows {len(filings)}")
        if page >= total_pages:
            break

    counts = {
        category: sum(category in row["categories"] for row in filings)
        for category in CATEGORIES
    }
    payload = {
        "source": "OpenDART disclosure list API",
        "period": {"begin": begin.isoformat(), "end": today.isoformat()},
        "crawled_at_utc": utc_now_iso(),
        "count": len(filings),
        "category_counts": counts,
        "filings": filings,
    }
    atomic_write_json(Path(args.output), payload, compact=True)
    print(f"Output: {args.output}")
    print(f"Filings: {len(filings)}")


if __name__ == "__main__":
    main()
