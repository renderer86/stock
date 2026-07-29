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

from collector_common import atomic_write_json


FN_GUIDE_LEGACY_URL = (
    "https://comp.fnguide.com/SVO2/ASP/SVD_Finance.asp"
    "?pGB=1&gicode=A{code}&cID=&MenuYn=Y&ReportGB=&NewMenuID=103&stkGb=701"
)
FN_GUIDE_LEGACY_RATIO_URL = (
    "https://comp.fnguide.com/SVO2/ASP/SVD_FinanceRatio.asp"
    "?pGB=1&gicode=A{code}&cID=&MenuYn=Y&ReportGB=&NewMenuID=104&stkGb=701"
)
FN_GUIDE_URL = "https://wcomp.fnguide.com/CompanyInfo/FinanceRatio?cmp_cd={code}"
FN_GUIDE_RATIO_API_URL = "https://wcomp.fnguide.com/CompanyInfo/getRtoAccumulate"
DEFAULT_INPUT = Path("data/market_sum.json")
DEFAULT_OUTPUT = Path("data/fnguide_roe_history.json")
DEBUG_DIR = Path("data/fnguide_debug")
DEFAULT_MIN_ROE = 10.0
DEFAULT_MIN_ROA = 7.0
FINANCIAL_ROA_EXEMPT_KEYWORDS = (
    "은행",
    "금융",
    "증권",
    "보험",
    "화재",
    "생명",
    "손해",
    "카드",
    "캐피탈",
    "리츠",
    "스팩",
)
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


def is_financial_roa_exempt(stock: dict[str, Any]) -> bool:
    name = str(stock.get("name") or "")
    return any(keyword in name for keyword in FINANCIAL_ROA_EXEMPT_KEYWORDS)


def filter_by_quality(
    stocks: list[dict[str, Any]],
    min_roe: float | None,
    min_roa: float | None,
    exempt_financial_roa: bool,
) -> list[dict[str, Any]]:
    if min_roe is None and min_roa is None:
        return stocks

    filtered: list[dict[str, Any]] = []
    for stock in stocks:
        roe = stock.get("roe")
        if min_roe is not None and (not isinstance(roe, (int, float)) or roe < min_roe):
            continue

        roa = stock.get("roa")
        if (
            min_roa is not None
            and not (exempt_financial_roa and is_financial_roa_exempt(stock))
            and (not isinstance(roa, (int, float)) or roa < min_roa)
        ):
            continue

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


def extract_table_rows_with_titles(table: BeautifulSoup) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.select("tr"):
        cells: list[str] = []
        for cell in tr.find_all(["th", "td"]):
            title = cell.get("title")
            text = title if isinstance(title, str) and title.strip() else cell.get_text(" ", strip=True)
            cells.append(clean_text(text))
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


def extract_periods_from_rows(rows: list[list[str]]) -> list[str]:
    periods: list[str] = []
    for row in rows[:8]:
        for cell in row:
            for period in PERIOD_SCAN_PATTERN.findall(cell):
                if period not in periods:
                    periods.append(period)
    return periods


def find_row_values(rows: list[list[str]], label_patterns: list[str], period_count: int) -> list[float | None] | None:
    for row in rows:
        label = clean_text(row[0]) if row else ""
        if not all(pattern in label for pattern in label_patterns):
            continue

        values = [parse_float(cell) for cell in row[1 : 1 + period_count]]
        if sum(value is not None for value in values) >= min(2, period_count):
            return values

    return None


def keep_dominant_annual_month(periods: list[str]) -> list[tuple[int, str]]:
    if not periods:
        return []

    month_counts: dict[str, int] = {}
    for period in periods:
        month = period.split("/")[1]
        month_counts[month] = month_counts.get(month, 0) + 1

    annual_month = max(
        month_counts,
        key=lambda month: (
            month_counts[month],
            -next(index for index, period in enumerate(periods) if period.endswith(f"/{month}")),
        ),
    )
    return [
        (index, period)
        for index, period in enumerate(periods)
        if period.endswith(f"/{annual_month}")
    ]


def extract_periods_and_roe_from_finance_statement(soup: BeautifulSoup) -> tuple[list[str], list[float | None]] | None:
    income_container = soup.select_one("#divSonikY")
    equity_container = soup.select_one("#divDaechaY")
    if income_container is None or equity_container is None:
        return None

    income_table = income_container.select_one("table")
    equity_table = equity_container.select_one("table")
    if income_table is None or equity_table is None:
        return None

    income_rows = extract_table_rows_with_titles(income_table)
    equity_rows = extract_table_rows_with_titles(equity_table)
    raw_periods = extract_periods_from_rows(income_rows)[:4]
    annual_periods = keep_dominant_annual_month(raw_periods)
    periods = [period for _, period in annual_periods]
    if not periods:
        raise RuntimeError("Failed to parse annual periods from finance statement.")

    raw_period_count = len(raw_periods)
    net_income_all = (
        find_row_values(income_rows, ["지배", "순이익"], raw_period_count)
        or find_row_values(income_rows, ["당기순이익"], raw_period_count)
    )
    equity_all = (
        find_row_values(equity_rows, ["지배", "주주", "지분"], raw_period_count)
        or find_row_values(equity_rows, ["자본"], raw_period_count)
    )
    if net_income_all is None or equity_all is None:
        raise RuntimeError("Failed to parse net income or controlling equity from finance statement.")

    net_income = [net_income_all[index] for index, _ in annual_periods]
    equity = [equity_all[index] for index, _ in annual_periods]

    roe_values: list[float | None] = []
    for index, income in enumerate(net_income):
        current_equity = equity[index]
        previous_equity = equity[index - 1] if index > 0 else None
        if income is None or current_equity in (None, 0):
            roe_values.append(None)
            continue

        equity_base = (
            (previous_equity + current_equity) / 2
            if previous_equity not in (None, 0)
            else current_equity
        )
        roe_values.append(round(income / equity_base * 100, 2))

    return periods, roe_values


def extract_periods_and_roe_from_ratio_dataset(
    payload: Any,
) -> tuple[list[str], list[float | None], list[bool]]:
    if not isinstance(payload, dict):
        raise RuntimeError("FnGuide ratio API returned a non-object payload.")

    dataset = payload.get("dataset")
    if not isinstance(dataset, dict):
        raise RuntimeError("FnGuide ratio API response has no dataset.")

    headers = dataset.get("header")
    rows = dataset.get("data")
    if not isinstance(headers, list) or not isinstance(rows, list):
        raise RuntimeError("FnGuide ratio API dataset has invalid header or data.")

    columns: list[tuple[str, str, bool]] = []
    for header in headers:
        if not isinstance(header, dict):
            continue

        period_match = PERIOD_SCAN_PATTERN.search(str(header.get("YYMM") or ""))
        value_key = str(header.get("CD") or "")
        if period_match is None or not value_key:
            continue

        line = header.get("LINE")
        is_full_year = line in (0, "0", None, "")
        columns.append((period_match.group(0), value_key, is_full_year))

    if len(columns) < 2:
        raise RuntimeError("FnGuide ratio API response has too few period headers.")

    roe_row: dict[str, Any] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = clean_text(str(row.get("NM") or "")).upper()
        if label == "ROE" or label.startswith("ROE("):
            roe_row = row
            break

    if roe_row is None:
        raise RuntimeError("FnGuide ratio API response has no ROE row.")

    periods = [period for period, _, _ in columns]
    roe_values = [parse_float(str(roe_row.get(value_key) or "")) for _, value_key, _ in columns]
    full_year_flags = [is_full_year for _, _, is_full_year in columns]
    if not any(value is not None for value in roe_values):
        raise RuntimeError("FnGuide ratio API ROE row contains no numeric values.")

    return periods, roe_values, full_year_flags


def split_histories(
    periods: list[str],
    values: list[float | None],
    *,
    all_periods_are_full_years: bool = False,
    full_year_flags: list[bool] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if full_year_flags is not None and len(full_year_flags) != len(periods):
        raise RuntimeError("Full-year flags do not match period count.")

    full_years: list[dict[str, Any]] = []
    latest_periods: list[dict[str, Any]] = []

    for index, (period, value) in enumerate(zip(periods, values, strict=True)):
        item = {"period": period, "roe": value}
        month = int(period.split("/")[1])
        is_full_year = (
            full_year_flags[index]
            if full_year_flags is not None
            else all_periods_are_full_years or month == 12
        )
        if is_full_year:
            full_years.append(item)
        else:
            latest_periods.append(item)

    return full_years, latest_periods


def fetch_roe_history(session: requests.Session, code: str) -> dict[str, Any]:
    url = FN_GUIDE_URL.format(code=code)
    api_response: requests.Response | None = None
    errors: list[str] = []
    statement_basis = ""

    for consol_typ, basis_name in (("C", "consolidated"), ("S", "separate")):
        try:
            api_response = session.get(
                FN_GUIDE_RATIO_API_URL,
                params={"cmp_cd": code, "consol_typ": consol_typ},
                headers={
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Referer": url,
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=20,
            )
            api_response.raise_for_status()
            periods, roe_values, full_year_flags = extract_periods_and_roe_from_ratio_dataset(
                api_response.json()
            )
            statement_basis = basis_name
            break
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{consol_typ}: {exc}")
    else:
        debug_text = api_response.text if api_response is not None else ""
        write_debug_files(code, debug_text, [*errors, debug_text])
        raise RuntimeError(
            "FnGuide ratio API failed for consolidated and separate statements: "
            + " | ".join(errors)
        )

    full_years, latest_periods = split_histories(
        periods,
        roe_values,
        full_year_flags=full_year_flags,
    )

    return {
        "code": code,
        "fnguide_url": url,
        "statement_basis": statement_basis,
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
    atomic_write_json(path, payload)


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
    parser.add_argument(
        "--min-roa",
        type=float,
        default=DEFAULT_MIN_ROA,
        help="Only crawl stocks whose current ROA in the input JSON is at least this value. Use a negative value to disable.",
    )
    parser.add_argument(
        "--no-financial-roa-exempt",
        action="store_true",
        help="Apply the ROA filter to bank, securities, insurance, REIT, and SPAC-like names too.",
    )
    args = parser.parse_args()

    if args.codes.strip():
        requested_codes = [code.strip() for code in args.codes.split(",") if code.strip()]
        universe = [{"code": code, "name": None} for code in requested_codes]
    else:
        universe = load_stock_universe(Path(args.input))
        universe = filter_by_quality(
            universe,
            None if args.min_roe < 0 else args.min_roe,
            None if args.min_roa < 0 else args.min_roa,
            not args.no_financial_roa_exempt,
        )

    if args.limit > 0:
        universe = universe[: args.limit]

    session = create_session()
    rows: list[dict[str, Any]] = []

    for index, stock in enumerate(universe, start=1):
        raw_code = str(stock.get("code") or "").strip().upper()
        code = raw_code.zfill(6) if raw_code.isdigit() else raw_code
        name = stock.get("name")
        if not re.fullmatch(r"[0-9A-Z]{6}", code):
            print(
                f"[{index}/{len(universe)}] SKIP {raw_code or '(empty)'} "
                f"{name or ''} -> Invalid KRX stock code.".rstrip()
            )
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
        "source": "FnGuide CompanyInfo/getRtoAccumulate",
        "input": args.input,
        "min_roe": None if args.min_roe < 0 else args.min_roe,
        "min_roa": None if args.min_roa < 0 else args.min_roa,
        "financial_roa_exempt": not args.no_financial_roa_exempt,
        "note": (
            "FnGuide's legacy SVO2 pages were retired. Historical ROE is read from the new "
            "CompanyInfo annual ratio dataset. full_years contains completed fiscal years only."
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
