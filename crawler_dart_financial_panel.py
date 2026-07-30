from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests

from collector_common import USER_AGENT, atomic_write_json, request_json, utc_now_iso
from env_loader import load_env_file


ROOT_DIR = Path(__file__).resolve().parent
DART_API_ROOT = "https://opendart.fss.or.kr/api"
CORP_CODE_URL = f"{DART_API_ROOT}/corpCode.xml"
MULTI_ACCOUNT_URL = f"{DART_API_ROOT}/fnlttMultiAcnt.json"
DEFAULT_INPUT = Path("data/market_sum.json")
DEFAULT_SECTOR_INPUT = Path("data/market_heatmap.json")
DEFAULT_OUTPUT = Path("data/dart_financial_panel.json")
ANNUAL_REPORT_CODE = "11011"
MIN_DART_YEAR = 2015
MAX_COMPANIES_PER_REQUEST = 100
SCHEMA_VERSION = 1
KST = ZoneInfo("Asia/Seoul")

ACCOUNT_ALIASES: dict[str, tuple[str, ...]] = {
    "assets": ("자산총계",),
    "liabilities": ("부채총계",),
    "equity": ("자본총계",),
    "owners_equity": (
        "지배기업소유주지분",
        "지배기업의소유주에게귀속되는자본",
        "지배기업의소유주에게귀속되는지분",
    ),
    "revenue": (
        "매출액",
        "수익(매출액)",
        "영업수익",
        "보험수익",
        "이자수익",
    ),
    "gross_profit": ("매출총이익",),
    "operating_income": (
        "영업이익",
        "영업이익(손실)",
        "영업손익",
    ),
    "net_income": (
        "당기순이익",
        "당기순이익(손실)",
        "연결당기순이익",
        "분기순이익",
    ),
    "owners_net_income": (
        "지배기업의소유주에게귀속되는당기순이익",
        "지배기업소유주지분순이익",
        "지배기업소유주귀속당기순이익",
    ),
}

FINANCIAL_KEYWORDS = (
    "금융",
    "은행",
    "증권",
    "보험",
    "생명보험",
    "손해보험",
    "카드",
    "캐피탈",
)


class DartRateLimitError(RuntimeError):
    """Raised when OpenDART refuses more requests for the current day."""


def parse_args() -> argparse.Namespace:
    current_year = datetime.now(KST).year
    parser = argparse.ArgumentParser(
        description=(
            "Build a ten-year annual Korean financial panel from OpenDART's "
            "multi-company major-account API."
        )
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--sector-input", default=str(DEFAULT_SECTOR_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--years",
        type=int,
        default=10,
        help="Number of completed fiscal years. Ignored when --start-year is set.",
    )
    parser.add_argument("--start-year", type=int, default=0)
    parser.add_argument(
        "--end-year",
        type=int,
        default=current_year - 1,
        help="Latest completed fiscal year.",
    )
    parser.add_argument(
        "--codes",
        default="",
        help="Optional comma-separated ticker list for validation or a partial run.",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=MAX_COMPANIES_PER_REQUEST)
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=5,
        help="Atomically save progress after this many API requests.",
    )
    parser.add_argument(
        "--max-consecutive-errors",
        type=int,
        default=5,
        help="Abort after repeated batch errors while preserving the checkpoint.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Discard the existing panel and rebuild the requested period.",
    )
    parser.add_argument(
        "--refresh-latest",
        action="store_true",
        help="Refetch the requested end year while retaining older completed years.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def normalize_ticker(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text.zfill(6) if text.isdigit() else text


def normalize_account_name(value: Any) -> str:
    return re.sub(r"[\s·]", "", str(value or "")).replace("－", "-")


def parse_amount(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "N/A"}:
        return None
    negative_parentheses = text.startswith("(") and text.endswith(")")
    if negative_parentheses:
        text = text[1:-1]
    try:
        amount = int(float(text))
    except ValueError:
        return None
    return -amount if negative_parentheses else amount


def parse_order(value: Any) -> int:
    try:
        return int(float(str(value or "").strip()))
    except ValueError:
        return 999_999


def safe_ratio(numerator: int | float | None, denominator: int | float | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    value = float(numerator) / float(denominator)
    if not math.isfinite(value):
        return None
    return round(value, 6)


def chunks(items: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def load_sector_lookup(path: Path) -> dict[str, dict[str, str]]:
    payload = load_json(path)
    lookup: dict[str, dict[str, str]] = {}
    for stock in ((payload.get("markets") or {}).get("KR") or {}).get("stocks") or []:
        ticker = normalize_ticker(stock.get("symbol"))
        if not re.fullmatch(r"\d{6}", ticker):
            continue
        lookup[ticker] = {
            "sector": str(stock.get("sector") or "").strip(),
            "industry": str(stock.get("industry") or "").strip(),
        }
    return lookup


def load_universe(
    path: Path,
    sector_path: Path,
    requested_codes: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    payload = load_json(path)
    sector_lookup = load_sector_lookup(sector_path)
    unique: dict[str, dict[str, Any]] = {}
    for stock in payload.get("stocks") or []:
        ticker = normalize_ticker(stock.get("code"))
        if not re.fullmatch(r"\d{6}", ticker):
            continue
        if requested_codes and ticker not in requested_codes:
            continue
        sector = sector_lookup.get(ticker, {})
        unique[ticker] = {
            "ticker": ticker,
            "company": str(stock.get("name") or "").strip(),
            "market": str(stock.get("market") or "").strip(),
            "sector": sector.get("sector") or None,
            "industry": sector.get("industry") or None,
        }

    universe = sorted(
        unique.values(),
        key=lambda row: (row["market"], row["ticker"]),
    )
    return universe[:limit] if limit > 0 else universe


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )
    return session


def fetch_corp_code_map(
    session: requests.Session,
    api_key: str,
) -> dict[str, dict[str, str]]:
    try:
        response = session.get(
            CORP_CODE_URL,
            params={"crtfc_key": api_key},
            timeout=60,
        )
        response.raise_for_status()
    except requests.RequestException:
        raise RuntimeError(
            "OpenDART corporation-code download failed; credentials hidden."
        ) from None
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            xml_name = next(
                name for name in archive.namelist() if not name.endswith("/")
            )
            root = ElementTree.fromstring(archive.read(xml_name))
    except (zipfile.BadZipFile, StopIteration, ElementTree.ParseError) as exc:
        raise RuntimeError("OpenDART corpCode.xml returned an invalid ZIP/XML file.") from exc

    mapping: dict[str, dict[str, str]] = {}
    for item in root.findall("list"):
        ticker = normalize_ticker(item.findtext("stock_code"))
        corp_code = str(item.findtext("corp_code") or "").strip()
        if re.fullmatch(r"\d{6}", ticker) and re.fullmatch(r"\d{8}", corp_code):
            mapping[ticker] = {
                "corp_code": corp_code,
                "corp_name": str(item.findtext("corp_name") or "").strip(),
                "modify_date": str(item.findtext("modify_date") or "").strip(),
            }
    return mapping


def fetch_multi_accounts(
    session: requests.Session,
    api_key: str,
    year: int,
    companies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    params = {
        "crtfc_key": api_key,
        "corp_code": ",".join(row["corp_code"] for row in companies),
        "bsns_year": str(year),
        "reprt_code": ANNUAL_REPORT_CODE,
    }
    payload: dict[str, Any] | None = None
    for attempt in range(3):
        payload = request_json(
            session,
            "GET",
            MULTI_ACCOUNT_URL,
            params=params,
            attempts=3,
            timeout=60,
        )
        status = str(payload.get("status") or "")
        if status in {"000", "013"}:
            return payload.get("list") or []
        if status == "020":
            raise DartRateLimitError(
                f"OpenDART request limit reached in fiscal year {year}."
            )
        if status not in {"800", "900"} or attempt == 2:
            raise RuntimeError(
                f"OpenDART {status}: {payload.get('message') or 'unknown error'}"
            )
        time.sleep(2.0 * (attempt + 1))
    return []


def preferred_statement_rows(rows: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    by_basis: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        basis = str(row.get("fs_div") or "").strip().upper()
        if basis in {"CFS", "OFS"}:
            by_basis[basis].append(row)
    if by_basis.get("CFS"):
        return "CFS", by_basis["CFS"]
    if by_basis.get("OFS"):
        return "OFS", by_basis["OFS"]
    return "", []


def account_value(
    accounts: list[dict[str, Any]],
    standardized_name: str,
) -> int | None:
    aliases = tuple(
        normalize_account_name(alias)
        for alias in ACCOUNT_ALIASES[standardized_name]
    )
    candidates: list[tuple[int, int, int]] = []
    for index, account in enumerate(accounts):
        name = normalize_account_name(account.get("account_name"))
        amount = account.get("amount")
        if amount is None:
            continue
        for alias_rank, alias in enumerate(aliases):
            if name == alias:
                candidates.append((0, alias_rank, index))
                break
            if alias in name:
                candidates.append((1, alias_rank, index))
                break
    if not candidates:
        return None
    _, _, selected_index = min(candidates)
    return accounts[selected_index]["amount"]


def build_observation(
    company: dict[str, Any],
    year: int,
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    basis, selected_rows = preferred_statement_rows(rows)
    if not selected_rows:
        return None

    accounts: list[dict[str, Any]] = []
    for row in sorted(
        selected_rows,
        key=lambda item: parse_order(item.get("ord")),
    ):
        amount = parse_amount(row.get("thstrm_amount"))
        if amount is None:
            amount = parse_amount(row.get("thstrm_add_amount"))
        accounts.append(
            {
                "statement": str(row.get("sj_div") or "").strip(),
                "account_name": str(row.get("account_nm") or "").strip(),
                "amount": amount,
            }
        )

    standardized = {
        name: account_value(accounts, name)
        for name in ACCOUNT_ALIASES
    }
    receipt = next(
        (
            str(row.get("rcept_no") or "").strip()
            for row in selected_rows
            if row.get("rcept_no")
        ),
        "",
    )
    currencies = [
        str(row.get("currency") or "").strip()
        for row in selected_rows
        if str(row.get("currency") or "").strip()
    ]
    currency = Counter(currencies).most_common(1)[0][0] if currencies else None
    sector_text = " ".join(
        str(company.get(key) or "") for key in ("sector", "industry")
    )

    return {
        "ticker": company["ticker"],
        "corp_code": company["corp_code"],
        "company": company["company"],
        "market": company["market"],
        "sector": company.get("sector"),
        "industry": company.get("industry"),
        "fiscal_year": year,
        "report_code": ANNUAL_REPORT_CODE,
        "statement_basis": basis,
        "currency": currency,
        "receipt_number": receipt or None,
        "dart_url": (
            f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}"
            if receipt
            else None
        ),
        "is_financial": any(keyword in sector_text for keyword in FINANCIAL_KEYWORDS),
        "accounts": accounts,
        "standardized": standardized,
    }


def enrich_derived_metrics(observations: list[dict[str, Any]]) -> None:
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        by_ticker[observation["ticker"]].append(observation)

    for company_rows in by_ticker.values():
        company_rows.sort(key=lambda row: row["fiscal_year"])
        previous: dict[str, Any] | None = None
        for row in company_rows:
            values = row["standardized"]
            previous_values = previous["standardized"] if previous else {}

            equity = values.get("owners_equity") or values.get("equity")
            net_income = values.get("owners_net_income")
            if net_income is None:
                net_income = values.get("net_income")
            assets = values.get("assets")
            previous_equity = (
                previous_values.get("owners_equity") or previous_values.get("equity")
            )
            previous_assets = previous_values.get("assets")
            has_adjacent_previous = bool(
                previous
                and previous["fiscal_year"] == row["fiscal_year"] - 1
            )

            average_equity = (
                (equity + previous_equity) / 2
                if has_adjacent_previous
                and equity is not None
                and previous_equity is not None
                else equity
            )
            average_assets = (
                (assets + previous_assets) / 2
                if has_adjacent_previous
                and assets is not None
                and previous_assets is not None
                else assets
            )
            roe_ratio = safe_ratio(net_income, average_equity)
            roa_ratio = safe_ratio(net_income, average_assets)
            equity_assets_ratio = safe_ratio(equity, assets)
            raw_roe_pct = round(roe_ratio * 100, 4) if roe_ratio is not None else None
            capital_noise = bool(
                equity is None
                or equity <= 0
                or equity_assets_ratio is None
                or equity_assets_ratio < 0.05
            )

            row["metrics"] = {
                "roe_pct": raw_roe_pct,
                "roe_for_model_pct": (
                    round(max(-50.0, min(50.0, raw_roe_pct)), 4)
                    if raw_roe_pct is not None and not capital_noise
                    else None
                ),
                "roa_pct": (
                    round(roa_ratio * 100, 4)
                    if roa_ratio is not None
                    else None
                ),
                "operating_margin_pct": _percent(
                    values.get("operating_income"),
                    values.get("revenue"),
                ),
                "net_margin_pct": _percent(
                    net_income,
                    values.get("revenue"),
                ),
                "gross_profit_to_assets_pct": _percent(
                    values.get("gross_profit"),
                    average_assets,
                ),
                "asset_turnover": safe_ratio(values.get("revenue"), average_assets),
                "debt_to_equity_pct": _percent(
                    values.get("liabilities"),
                    equity,
                ),
                "equity_to_assets_pct": (
                    round(equity_assets_ratio * 100, 4)
                    if equity_assets_ratio is not None
                    else None
                ),
            }
            row["quality_flags"] = {
                "average_balance_sheet_denominator": has_adjacent_previous,
                "capital_impairment_or_thin_equity": capital_noise,
                "roe_winsorized_at_50_pct": bool(
                    raw_roe_pct is not None and abs(raw_roe_pct) > 50
                ),
                "post_k_ifrs_regime": row["fiscal_year"] >= 2011,
            }
            previous = row


def _percent(
    numerator: int | float | None,
    denominator: int | float | None,
) -> float | None:
    ratio = safe_ratio(numerator, denominator)
    return round(ratio * 100, 4) if ratio is not None else None


def observation_key(row: dict[str, Any]) -> tuple[str, int]:
    return normalize_ticker(row.get("ticker")), int(row.get("fiscal_year") or 0)


def no_data_key(row: dict[str, Any]) -> tuple[str, int]:
    return normalize_ticker(row.get("ticker")), int(row.get("fiscal_year") or 0)


def build_payload(
    *,
    input_path: Path,
    sector_path: Path,
    start_year: int,
    end_year: int,
    universe_count: int,
    mapped_count: int,
    observations: list[dict[str, Any]],
    no_data: list[dict[str, Any]],
    unmapped: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    request_count: int,
    complete: bool,
) -> dict[str, Any]:
    enrich_derived_metrics(observations)
    observations.sort(key=lambda row: (row["ticker"], row["fiscal_year"]))
    no_data.sort(key=lambda row: (row["ticker"], row["fiscal_year"]))
    by_year = Counter(row["fiscal_year"] for row in observations)
    by_basis = Counter(row["statement_basis"] for row in observations)
    model_ready = sum(
        row.get("metrics", {}).get("roe_for_model_pct") is not None
        for row in observations
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "OpenDART fnlttMultiAcnt annual major accounts",
        "source_url": MULTI_ACCOUNT_URL,
        "crawled_at_utc": utc_now_iso(),
        "complete": complete,
        "count": len(observations),
        "company_count": mapped_count,
        "period": {"start_year": start_year, "end_year": end_year},
        "report_code": ANNUAL_REPORT_CODE,
        "inputs": {
            "universe": input_path.as_posix(),
            "sector_mapping": sector_path.as_posix(),
        },
        "methodology": {
            "statement_preference": "CFS first, OFS fallback",
            "roe": "owner net income / average owner equity; total values fallback",
            "roa": "net income / average total assets",
            "model_roe_cap_pct": 50,
            "thin_equity_floor_pct_of_assets": 5,
            "survivorship_bias": (
                "Current-listed KOSPI/KOSDAQ universe. Delisted-company history is not "
                "included yet; do not use this version for final persistence base rates."
            ),
            "financials": (
                "Financial companies are flagged and should be modeled separately."
            ),
        },
        "summary": {
            "universe_count": universe_count,
            "mapped_company_count": mapped_count,
            "unmapped_instrument_count": len(unmapped),
            "observation_count": len(observations),
            "model_ready_roe_count": model_ready,
            "no_data_count": len(no_data),
            "error_count": len(errors),
            "api_request_count_this_run": request_count,
            "observations_by_year": dict(sorted(by_year.items())),
            "observations_by_statement_basis": dict(sorted(by_basis.items())),
        },
        "unmapped_instruments": unmapped,
        "no_data": no_data,
        "errors": errors,
        "observations": observations,
    }


def main() -> None:
    load_env_file(ROOT_DIR / ".env")
    args = parse_args()
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DART_API_KEY is not set.")

    end_year = args.end_year
    start_year = (
        args.start_year
        if args.start_year
        else end_year - max(args.years, 1) + 1
    )
    start_year = max(MIN_DART_YEAR, start_year)
    if end_year < start_year:
        raise SystemExit("--end-year must be greater than or equal to --start-year.")
    if not 1 <= args.batch_size <= MAX_COMPANIES_PER_REQUEST:
        raise SystemExit("--batch-size must be between 1 and 100.")

    requested_codes = {
        normalize_ticker(code)
        for code in args.codes.split(",")
        if code.strip()
    }
    input_path = Path(args.input)
    sector_path = Path(args.sector_input)
    output_path = Path(args.output)
    universe = load_universe(
        input_path,
        sector_path,
        requested_codes,
        max(0, args.limit),
    )
    if not universe:
        raise SystemExit("No stocks found in the requested universe.")

    print(
        f"[DART PANEL] universe {len(universe):,} | "
        f"fiscal years {start_year}-{end_year} | annual reports",
        flush=True,
    )
    session = create_session()
    print("[DART PANEL] downloading corporation-code mapping", flush=True)
    corp_map = fetch_corp_code_map(session, api_key)

    mapped: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    for company in universe:
        corp = corp_map.get(company["ticker"])
        if not corp:
            unmapped.append(
                {
                    "ticker": company["ticker"],
                    "company": company["company"],
                    "market": company["market"],
                    "reason": "corp_code_not_found",
                }
            )
            continue
        mapped.append(
            {
                **company,
                "company": corp.get("corp_name") or company["company"],
                "corp_code": corp["corp_code"],
            }
        )

    print(
        f"[DART PANEL] mapped companies {len(mapped):,} | "
        f"non-company instruments/unmapped {len(unmapped):,}",
        flush=True,
    )
    if not mapped:
        raise SystemExit("No OpenDART corporation codes matched the universe.")

    existing = {} if args.reset else load_json(output_path)
    observations_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    no_data_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    if existing.get("schema_version") == SCHEMA_VERSION:
        observations_by_key = {
            observation_key(row): row
            for row in existing.get("observations") or []
            if start_year <= int(row.get("fiscal_year") or 0) <= end_year
        }
        no_data_by_key = {
            no_data_key(row): row
            for row in existing.get("no_data") or []
            if start_year <= int(row.get("fiscal_year") or 0) <= end_year
        }

    if args.refresh_latest:
        observations_by_key = {
            key: row
            for key, row in observations_by_key.items()
            if key[1] != end_year
        }
        no_data_by_key = {
            key: row
            for key, row in no_data_by_key.items()
            if key[1] != end_year
        }

    errors: list[dict[str, Any]] = []
    request_count = 0
    consecutive_errors = 0
    started_at = time.monotonic()

    def save_checkpoint(complete: bool) -> None:
        payload = build_payload(
            input_path=input_path,
            sector_path=sector_path,
            start_year=start_year,
            end_year=end_year,
            universe_count=len(universe),
            mapped_count=len(mapped),
            observations=list(observations_by_key.values()),
            no_data=list(no_data_by_key.values()),
            unmapped=unmapped,
            errors=errors,
            request_count=request_count,
            complete=complete,
        )
        atomic_write_json(output_path, payload, compact=True)

    try:
        for year in range(start_year, end_year + 1):
            pending = [
                company
                for company in mapped
                if (company["ticker"], year) not in observations_by_key
                and (company["ticker"], year) not in no_data_by_key
            ]
            batches = list(chunks(pending, args.batch_size))
            if not batches:
                print(f"[DART PANEL] {year}: already complete", flush=True)
                continue

            print(
                f"[DART PANEL] {year}: pending {len(pending):,} companies "
                f"in {len(batches):,} batches",
                flush=True,
            )
            for batch_index, batch in enumerate(batches, start=1):
                request_count += 1
                try:
                    rows = fetch_multi_accounts(
                        session,
                        api_key,
                        year,
                        batch,
                    )
                    rows_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
                    corp_to_ticker = {
                        company["corp_code"]: company["ticker"]
                        for company in batch
                    }
                    for row in rows:
                        ticker = normalize_ticker(row.get("stock_code"))
                        if not re.fullmatch(r"\d{6}", ticker):
                            ticker = corp_to_ticker.get(
                                str(row.get("corp_code") or "").strip(),
                                "",
                            )
                        if ticker:
                            rows_by_ticker[ticker].append(row)

                    for company in batch:
                        key = (company["ticker"], year)
                        observation = build_observation(
                            company,
                            year,
                            rows_by_ticker.get(company["ticker"], []),
                        )
                        if observation:
                            observations_by_key[key] = observation
                            no_data_by_key.pop(key, None)
                        else:
                            no_data_by_key[key] = {
                                "ticker": company["ticker"],
                                "corp_code": company["corp_code"],
                                "company": company["company"],
                                "fiscal_year": year,
                                "reason": "annual_major_accounts_not_found",
                            }
                    consecutive_errors = 0
                except DartRateLimitError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    consecutive_errors += 1
                    errors.append(
                        {
                            "fiscal_year": year,
                            "batch": batch_index,
                            "tickers": [company["ticker"] for company in batch],
                            "error": str(exc),
                        }
                    )
                    print(
                        f"[DART PANEL] {year} batch {batch_index}/{len(batches)} "
                        f"FAIL -> {exc}",
                        flush=True,
                    )

                completed_pairs = len(observations_by_key) + len(no_data_by_key)
                elapsed = time.monotonic() - started_at
                print(
                    f"[DART PANEL] {year} batch {batch_index}/{len(batches)} | "
                    f"completed pairs {completed_pairs:,} | "
                    f"observations {len(observations_by_key):,} | "
                    f"errors {len(errors):,} | {elapsed:.1f}s",
                    flush=True,
                )
                if request_count % max(1, args.checkpoint_every) == 0:
                    save_checkpoint(complete=False)
                    print(
                        f"[DART PANEL] checkpoint saved: {output_path}",
                        flush=True,
                    )
                if consecutive_errors >= max(1, args.max_consecutive_errors):
                    raise RuntimeError(
                        f"Aborting after {consecutive_errors} consecutive batch errors."
                    )
                time.sleep(max(0.0, args.delay))

            save_checkpoint(complete=False)
    except Exception:
        save_checkpoint(complete=False)
        print(
            f"[DART PANEL] partial checkpoint preserved at {output_path}",
            flush=True,
        )
        raise

    save_checkpoint(complete=not errors)
    print(f"[DART PANEL] output: {output_path}", flush=True)
    print(
        f"[DART PANEL] observations {len(observations_by_key):,} | "
        f"no-data {len(no_data_by_key):,} | errors {len(errors):,} | "
        f"{time.monotonic() - started_at:.1f}s",
        flush=True,
    )
    if errors:
        raise SystemExit(
            "Some OpenDART batches failed. The partial panel was saved; rerun in resume mode."
        )


if __name__ == "__main__":
    main()
