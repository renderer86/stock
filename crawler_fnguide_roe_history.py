from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


FN_GUIDE_URL = (
    "https://comp.fnguide.com/SVO2/ASP/SVD_FinanceRatio.asp"
    "?pGB=1&gicode=A{code}&cID=&MenuYn=Y&ReportGB=&NewMenuID=104&stkGb=701"
)
DEFAULT_INPUT = Path("data/market_sum.json")
DEFAULT_OUTPUT = Path("data/fnguide_roe_history.json")
DEBUG_DIR = Path("data/fnguide_debug")
DEFAULT_MIN_ROE = 10.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)
PERIOD_PATTERN = re.compile(r"^\d{4}/\d{2}$")
PERIOD_SCAN_PATTERN = re.compile(r"\d{4}/\d{2}")
NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


def clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def parse_float(value: str) -> float | None:
    text = clean_text(value).replace(",", "").replace("%", "")
    match = NUMBER_PATTERN.search(text)
    if not match:
        return None

    try:
        return float(match.group(0))
    except ValueError:
        return None


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Referer": "https://comp.fnguide.com/",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )
    return session


def load_stock_universe(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    stocks = payload.get("stocks")
    if not isinstance(stocks, list):
        raise RuntimeError(f"Invalid stock payload in {path}")
    return stocks


def filter_by_min_roe(stocks: list[dict[str, Any]], min_roe: float | None) -> list[dict[str, Any]]:
    if min_roe is None:
        return stocks

    filtered: list[dict[str, Any]] = []
    for stock in stocks:
        roe = stock.get("roe")
        if isinstance(roe, (int, float)) and roe >= min_roe:
            filtered.append(stock)
    return filtered


def extract_relevant_lines(soup: BeautifulSoup) -> list[str]:
    return [clean_text(text) for text in soup.stripped_strings if clean_text(text)]


def extract_periods_from_lines(section_lines: list[str]) -> list[str]:
    periods: list[str] = []
    for line in section_lines[:12]:
        for period in PERIOD_SCAN_PATTERN.findall(line):
            if period not in periods:
                periods.append(period)

    if len(periods) >= 4:
        return periods[:5]

    raise RuntimeError("Failed to parse period headers from annual section.")


def extract_roe_values_from_lines(section_lines: list[str], period_count: int) -> list[float | None]:
    for index, line in enumerate(section_lines):
        if "ROE" not in line:
            continue

        for candidate in section_lines[index + 1 : index + 12]:
            number_texts = NUMBER_PATTERN.findall(candidate.replace(",", ""))
            if len(number_texts) < period_count:
                continue

            values = [float(number_text) for number_text in number_texts[:period_count]]
            if len(values) == period_count:
                return values

    raise RuntimeError("Failed to parse ROE row from annual section.")


def extract_table_rows(table: BeautifulSoup) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.select("tr"):
        cells = [clean_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    return rows


def find_annual_ratio_table(soup: BeautifulSoup) -> list[list[str]] | None:
    candidates: list[tuple[int, int, list[list[str]]]] = []

    for table in soup.select("table"):
        rows = extract_table_rows(table)
        if not rows:
            continue

        flattened = " ".join(" ".join(row) for row in rows)
        if "ROE" not in flattened:
            continue
        if "IFRS" not in flattened:
            continue

        periods: list[str] = []
        for row in rows[:8]:
            for cell in row:
                for period in PERIOD_SCAN_PATTERN.findall(cell):
                    if period not in periods:
                        periods.append(period)

        if len(periods) < 4:
            continue

        annual_count = sum(period.endswith("/12") for period in periods)
        has_roe_row = any(any("ROE" in cell for cell in row[:3]) for row in rows)
        if not has_roe_row:
            continue

        candidates.append((annual_count, len(periods), rows))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def extract_periods_and_roe_from_table(rows: list[list[str]]) -> tuple[list[str], list[float | None]]:
    periods: list[str] = []
    for row in rows[:8]:
        for cell in row:
            for period in PERIOD_SCAN_PATTERN.findall(cell):
                if period not in periods:
                    periods.append(period)

    periods = periods[:5]
    if len(periods) < 4:
        raise RuntimeError("Failed to parse period headers from annual ratio table.")

    period_count = len(periods)

    for row in rows:
        label = " ".join(row[:3])
        if "ROE" not in label:
            continue

        trailing = row[-period_count:]
        values = [parse_float(cell) for cell in trailing]
        numeric_count = sum(value is not None for value in values)
        if numeric_count >= max(3, period_count - 1):
            return periods, values

    return periods, [None] * period_count


def extract_annual_section(lines: list[str]) -> list[str]:
    start_index = -1
    end_index = len(lines)

    for index, line in enumerate(lines):
        if "IFRS" in line and "[3" not in line:
            start_index = index
            break

    if start_index < 0:
        raise RuntimeError("Failed to find annual finance ratio section.")

    for index in range(start_index + 1, len(lines)):
        line = lines[index]
        if "[3" in line or ("IFRS" in line and index > start_index):
            end_index = index
            break

    return lines[start_index:end_index]


def split_histories(periods: list[str], values: list[float | None]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    full_years: list[dict[str, Any]] = []
    latest_periods: list[dict[str, Any]] = []

    for period, value in zip(periods, values, strict=True):
        item = {"period": period, "roe": value}
        month = int(period.split("/")[1])
        if month == 12:
            full_years.append(item)
        else:
            latest_periods.append(item)

    return full_years, latest_periods


def fetch_roe_history(session: requests.Session, code: str) -> dict[str, Any]:
    url = FN_GUIDE_URL.format(code=code)
    response = session.get(url, timeout=20)
    response.raise_for_status()
    response.encoding = "utf-8"

    soup = BeautifulSoup(response.text, "html.parser")
    lines = extract_relevant_lines(soup)
    try:
        annual_table_rows = find_annual_ratio_table(soup)
        if annual_table_rows is not None:
            periods, roe_values = extract_periods_and_roe_from_table(annual_table_rows)
        else:
            annual_section = extract_annual_section(lines)
            periods = extract_periods_from_lines(annual_section)
            try:
                roe_values = extract_roe_values_from_lines(annual_section, len(periods))
            except RuntimeError:
                roe_values = [None] * len(periods)
    except Exception:
        write_debug_files(code, response.text, lines)
        raise
    full_years, latest_periods = split_histories(periods, roe_values)

    return {
        "code": code,
        "fnguide_url": url,
        "periods": periods,
        "roe_values": roe_values,
        "full_years": full_years,
        "latest_periods": latest_periods,
        "latest_full_year_roe": full_years[-1]["roe"] if full_years else None,
        "five_period_average_roe": _average([value for value in roe_values if value is not None]),
        "four_full_year_average_roe": _average(
            [item["roe"] for item in full_years if item["roe"] is not None]
        ),
    }


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_debug_files(code: str, html: str, lines: list[str]) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    (DEBUG_DIR / f"{code}.html").write_text(html, encoding="utf-8")
    (DEBUG_DIR / f"{code}.txt").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl FnGuide annual finance ratio pages and extract historical ROE."
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT),
        help="Path to market_sum.json containing stock codes.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Path for FnGuide ROE history JSON output.",
    )
    parser.add_argument(
        "--codes",
        default="",
        help="Comma-separated stock codes. If provided, skips --input universe loading.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional cap on number of stocks to crawl.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
        help="Sleep time between stock requests in seconds.",
    )
    parser.add_argument(
        "--min-roe",
        type=float,
        default=DEFAULT_MIN_ROE,
        help="Only crawl stocks whose current ROE in the input JSON is at least this value. Use a negative value to disable.",
    )
    args = parser.parse_args()

    if args.codes.strip():
        requested_codes = [code.strip() for code in args.codes.split(",") if code.strip()]
        universe = [{"code": code, "name": None} for code in requested_codes]
    else:
        universe = load_stock_universe(Path(args.input))
        universe = filter_by_min_roe(universe, None if args.min_roe < 0 else args.min_roe)

    if args.limit > 0:
        universe = universe[: args.limit]

    session = create_session()
    rows: list[dict[str, Any]] = []

    for index, stock in enumerate(universe, start=1):
        code = str(stock.get("code") or "").zfill(6)
        name = stock.get("name")
        if not re.fullmatch(r"\d{6}", code):
            continue

        try:
            history = fetch_roe_history(session, code)
            rows.append(
                {
                    "code": code,
                    "name": name,
                    **history,
                }
            )
            print(f"[{index}/{len(universe)}] OK {code} {name or ''}".rstrip())
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "error": str(exc),
                    "fnguide_url": FN_GUIDE_URL.format(code=code),
                }
            )
            print(f"[{index}/{len(universe)}] FAIL {code} {name or ''} -> {exc}".rstrip())

        time.sleep(args.delay)

    payload = {
        "source": "FnGuide SVD_FinanceRatio.asp",
        "input": args.input,
        "min_roe": None if args.min_roe < 0 else args.min_roe,
        "note": (
            "FnGuide public finance ratio page currently exposes the most recent annual periods "
            "plus the latest interim period in the visible annual table. "
            "full_years contains completed fiscal years only."
        ),
        "count": len(rows),
        "crawled_at_utc": datetime.now(timezone.utc).isoformat(),
        "stocks": rows,
    }
    write_json(Path(args.output), payload)

    print(f"Output: {args.output}")
    print(f"Rows: {len(rows)}")


if __name__ == "__main__":
    main()
