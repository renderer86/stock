from __future__ import annotations

import argparse
import html
import io
import json
import os
import re
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from collector_common import USER_AGENT, atomic_write_json, request_json, utc_now_iso
from env_loader import load_env_file


ROOT_DIR = Path(__file__).resolve().parent
DART_API = "https://opendart.fss.or.kr/api"
DEFAULT_DISCLOSURES = Path("data/dart_disclosures.json")
DEFAULT_MARKET = Path("data/market_sum.json")
DEFAULT_EVENTS_OUTPUT = Path("data/dart_event_details.json")
DEFAULT_INSIDERS_OUTPUT = Path("data/dart_insider_trades.json")
KST = ZoneInfo("Asia/Seoul")
DATE_PATTERN = r"(\d{4}-\d{2}-\d{2})"

# Mir의 주요사항보고서 상세 파서가 사용하는 공시명 → OpenDART DS005 API 기준.
EVENT_API_RULES = (
    ("자기주식취득신탁계약체결결정", "buyback_trust", "tsstkAqTrctrCcDecsn"),
    ("자기주식취득결정", "buyback", "tsstkAqDecsn"),
    ("자기주식처분결정", "treasury_disposal", "tsstkDpDecsn"),
    ("전환사채권발행결정", "convertible_bond", "cvbdIsDecsn"),
)
PURCHASE_REASON_RULES = (
    ("장내매수", "open_market_purchase"),
    ("장외매수", "off_market_purchase"),
    ("시간외매수", "after_hours_purchase"),
)
NON_PURCHASE_INCREASE_RULES = (
    ("주식매수선택권", "stock_option"),
    ("스톡옵션", "stock_option"),
    ("상속", "inheritance"),
    ("증여", "gift"),
    ("무상신주", "bonus_shares"),
    ("주식배당", "stock_dividend"),
    ("신주인수권", "warrant"),
    ("전환권", "conversion"),
)


def should_log_progress(current: int, total: int, every: int) -> bool:
    return (
        current == 1
        or current == total
        or current % max(every, 1) == 0
    )


def progress_percent(current: int, total: int) -> float:
    return current / total * 100 if total else 100.0


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def receipt_number(row: dict[str, Any]) -> str:
    return str(row.get("rcept_no") or "").strip()


def disclosure_url(receipt: str) -> str:
    return (
        f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}"
        if receipt
        else "https://dart.fss.or.kr/"
    )


def normalized_date(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def number(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "").rstrip("%")
    if not text or text == "-":
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return None if parsed != parsed else parsed


def integer(value: Any) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None else None


def clean_document(document: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", document)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def after(text: str, label: str, pattern: str, window: int = 90) -> str | None:
    index = text.find(label)
    if index < 0:
        return None
    match = re.search(
        pattern,
        text[index + len(label) : index + len(label) + window],
    )
    return match.group(1).strip() if match else None


def after_number(text: str, label: str, window: int = 25) -> float | None:
    index = text.find(label)
    if index < 0:
        return None
    tail = text[index + len(label) : index + len(label) + window]
    match = re.match(r"\s*([\d.,]+)\b", tail)
    return number(match.group(1)) if match else None


def parse_dividend(text: str) -> dict[str, Any]:
    return {
        "dividend_kind": after(text, "1. 배당구분", r"([가-힣]+배당)", 20),
        "dividend_type": after(text, "2. 배당종류", r"(현금배당|현물배당)", 20),
        "dps_common_krw": after_number(text, "1주당 배당금(원) 보통주식"),
        "market_yield_common_pct": after_number(
            text,
            "시가배당률(%) 보통주식",
        ),
        "total_dividend_krw": after_number(text, "배당금총액(원)"),
        "record_date": after(text, "배당기준일", DATE_PATTERN),
        "payment_date": after(text, "배당금지급 예정일자", DATE_PATTERN),
        "decision_date": after(text, "이사회결의일", DATE_PATTERN),
    }


def parse_contract(text: str) -> dict[str, Any]:
    amount = after_number(text, "계약금액 총액(원)")
    recent_sales = after_number(text, "최근 매출액(원)")
    ratio = after_number(text, "매출액 대비(%)")
    if ratio is not None and ratio > 1000:
        ratio = None
    if ratio is None and amount and recent_sales:
        ratio = round(amount / recent_sales * 100, 2)
    counterparty = after(text, "계약상대방", r"\s*([^\-]{1,50}?)\s*-", 70)
    return {
        "contract_amount_krw": amount,
        "recent_sales_krw": recent_sales,
        "sales_ratio_pct": ratio,
        "counterparty": counterparty,
        "region": after(text, "공급지역", r"\s*([^\-\d]{1,30}?)\s*[\-\d]", 45),
        "start_date": after(text, "계약기간 시작일", DATE_PATTERN),
        "end_date": after(text, "종료일", DATE_PATTERN),
    }


def event_rule(report_name: str) -> tuple[str, str] | None:
    for keyword, category, endpoint in EVENT_API_RULES:
        if keyword in report_name:
            return category, endpoint
    return None


def summarize_event(endpoint: str, row: dict[str, Any]) -> dict[str, Any]:
    if endpoint == "cvbdIsDecsn":
        return {
            "amount_krw": integer(row.get("bd_fta")),
            "conversion_price_krw": integer(row.get("cv_prc")),
            "dilution_pct": number(row.get("cvisstk_tisstk_vs")),
            "new_shares": integer(row.get("cvisstk_cnt")),
            "coupon_pct": number(row.get("bd_intr_ex")),
            "ytm_pct": number(row.get("bd_intr_sf")),
            "issue_method": (
                str(row.get("bdis_mthn")).strip()
                if str(row.get("bdis_mthn") or "").strip() not in {"", "-"}
                else None
            ),
        }

    quantity = integer(row.get("aqpln_stk_ostk")) or integer(
        row.get("dppln_stk_ostk")
    )
    amount = (
        integer(row.get("aqpln_prc_ostk"))
        or integer(row.get("dppln_prc_ostk"))
        or integer(row.get("ctr_prc"))
    )
    return {
        "shares": quantity,
        "amount_krw": amount,
        "purpose": (
            str(row.get("aq_pp")).strip()[:100]
            if str(row.get("aq_pp") or "").strip() not in {"", "-"}
            else None
        ),
        "method": (
            str(row.get("aq_mth")).strip()
            if str(row.get("aq_mth") or "").strip() not in {"", "-"}
            else None
        ),
        "treasury_held_pct": number(row.get("eaq_ostk_rt")),
    }


def fetch_document(
    session: requests.Session,
    api_key: str,
    receipt: str,
) -> str | None:
    for attempt in range(3):
        try:
            response = session.get(
                f"{DART_API}/document.xml",
                params={"crtfc_key": api_key, "rcept_no": receipt},
                timeout=30,
            )
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                files = [
                    name
                    for name in archive.namelist()
                    if not name.endswith("/")
                ]
                if not files:
                    return None
                parts: list[str] = []
                for name in files:
                    raw = archive.read(name)
                    for encoding in ("utf-8", "euc-kr", "cp949"):
                        try:
                            parts.append(raw.decode(encoding))
                            break
                        except UnicodeDecodeError:
                            continue
                    else:
                        parts.append(raw.decode("utf-8", "replace"))
                return "\n".join(parts)
        except (requests.RequestException, zipfile.BadZipFile):
            if attempt + 1 < 3:
                time.sleep(0.8 * (attempt + 1))
    return None


def dart_rows(
    session: requests.Session,
    api_key: str,
    endpoint: str,
    params: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    payload = request_json(
        session,
        "GET",
        f"{DART_API}/{endpoint}.json",
        params={"crtfc_key": api_key, **params},
        attempts=3,
        timeout=30,
    )
    status = str(payload.get("status") or "")
    if status == "013":
        return [], None
    if status != "000":
        return [], f"{endpoint}:{status}:{payload.get('message') or ''}"
    return payload.get("list") or [], None


def base_event(row: dict[str, Any]) -> dict[str, Any]:
    receipt = receipt_number(row)
    return {
        "ticker": str(row.get("stock_code") or "").zfill(6),
        "company": str(row.get("corp_name") or "").strip(),
        "report_name": str(row.get("report_nm") or "").strip(),
        "receipt_number": receipt,
        "file_date": normalized_date(row.get("rcept_dt")),
        "dart_url": disclosure_url(receipt),
    }


def collect_document_events(
    session: requests.Session,
    api_key: str,
    filings: list[dict[str, Any]],
    delay: float,
    progress_every: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    dividends: list[dict[str, Any]] = []
    contracts: list[dict[str, Any]] = []
    errors: list[str] = []
    targets: list[tuple[dict[str, Any], str, str]] = []
    for row in filings:
        name = str(row.get("report_nm") or "")
        kind: str | None = None
        if "현금ㆍ현물배당결정" in name or "현금·현물배당결정" in name:
            kind = "dividend"
        elif "단일판매ㆍ공급계약체결" in name or "단일판매·공급계약체결" in name:
            kind = "contract"
        if not kind:
            continue

        receipt = receipt_number(row)
        if not receipt:
            continue
        targets.append((row, kind, receipt))

    started_at = time.monotonic()
    print(
        f"[DART 1/3] Dividend/contract documents: "
        f"{len(targets):,} targets from {len(filings):,} filings",
        flush=True,
    )
    for index, (row, kind, receipt) in enumerate(targets, start=1):
        document = fetch_document(session, api_key, receipt)
        if not document:
            errors.append(f"document:{receipt}")
        else:
            text = clean_document(document)
            parsed = (
                parse_dividend(text)
                if kind == "dividend"
                else parse_contract(text)
            )
            if kind == "dividend":
                if (
                    parsed.get("record_date")
                    or parsed.get("dps_common_krw") is not None
                ):
                    dividends.append({**base_event(row), **parsed})
            elif (
                parsed.get("contract_amount_krw") is not None
                or parsed.get("sales_ratio_pct") is not None
            ):
                contracts.append({**base_event(row), **parsed})
        if should_log_progress(index, len(targets), progress_every):
            print(
                f"[DART 1/3] documents {index}/{len(targets)} "
                f"({progress_percent(index, len(targets)):.0f}%) | "
                f"dividends {len(dividends)} | contracts {len(contracts)} | "
                f"errors {len(errors)} | {time.monotonic() - started_at:.1f}s",
                flush=True,
            )
        time.sleep(delay)

    dividends.sort(
        key=lambda row: row.get("record_date") or row.get("file_date") or "",
        reverse=True,
    )
    contracts.sort(
        key=lambda row: float(row.get("sales_ratio_pct") or 0),
        reverse=True,
    )
    print(
        f"[DART 1/3] completed in {time.monotonic() - started_at:.1f}s",
        flush=True,
    )
    return dividends, contracts, errors


def collect_structured_events(
    session: requests.Session,
    api_key: str,
    filings: list[dict[str, Any]],
    begin: str,
    end: str,
    delay: float,
    progress_every: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    targets: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for filing in filings:
        rule = event_rule(str(filing.get("report_nm") or ""))
        corp_code = str(filing.get("corp_code") or "").strip()
        receipt = receipt_number(filing)
        if not rule or not corp_code or not receipt:
            continue
        category, endpoint = rule
        targets[(corp_code, category, endpoint)][receipt] = filing

    events: list[dict[str, Any]] = []
    errors: list[str] = []
    started_at = time.monotonic()
    target_items = list(targets.items())
    print(
        f"[DART 2/3] Buyback/CB structured APIs: "
        f"{len(target_items):,} company-endpoint targets",
        flush=True,
    )
    for index, ((corp_code, category, endpoint), wanted) in enumerate(
        target_items,
        start=1,
    ):
        rows, error = dart_rows(
            session,
            api_key,
            endpoint,
            {"corp_code": corp_code, "bgn_de": begin, "end_de": end},
        )
        if error:
            errors.append(error)
        else:
            for raw in rows:
                receipt = str(raw.get("rcept_no") or "").strip()
                source = wanted.get(receipt)
                if not source:
                    continue
                details = {
                    key: value
                    for key, value in summarize_event(endpoint, raw).items()
                    if value is not None
                }
                if not details:
                    continue
                events.append(
                    {
                        **base_event(source),
                        "category": category,
                        "dart_api": endpoint,
                        **details,
                    }
                )
        if should_log_progress(index, len(target_items), progress_every):
            print(
                f"[DART 2/3] API targets {index}/{len(target_items)} "
                f"({progress_percent(index, len(target_items)):.0f}%) | "
                f"events {len(events)} | errors {len(errors)} | "
                f"{time.monotonic() - started_at:.1f}s",
                flush=True,
            )
        time.sleep(delay)
    events.sort(key=lambda row: row.get("file_date") or "", reverse=True)
    print(
        f"[DART 2/3] completed in {time.monotonic() - started_at:.1f}s",
        flush=True,
    )
    return events, errors


def load_prices(path: Path) -> dict[str, int]:
    payload = load_json(path)
    result: dict[str, int] = {}
    for row in payload.get("stocks") or []:
        code = str(row.get("code") or "")
        value = row.get("current_price")
        if not isinstance(value, (int, float)):
            value = row.get("now")
        if code and isinstance(value, (int, float)):
            result[code] = int(value)
    return result


def reason_from_document(text: str | None) -> tuple[list[str], bool]:
    if not text:
        return [], False
    reasons: list[str] = []
    purchase = False
    for keyword, label in PURCHASE_REASON_RULES:
        if keyword in text:
            reasons.append(label)
            purchase = True
    for keyword, label in NON_PURCHASE_INCREASE_RULES:
        if keyword in text and label not in reasons:
            reasons.append(label)
    return reasons, purchase


def collect_insiders(
    session: requests.Session,
    api_key: str,
    filings: list[dict[str, Any]],
    cutoff: str,
    prices: dict[str, int],
    delay: float,
    progress_every: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    sources_by_corp: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in filings:
        name = str(row.get("report_nm") or "")
        if "소유상황보고" not in name and "임원ㆍ주요주주" not in name:
            continue
        corp_code = str(row.get("corp_code") or "").strip()
        receipt = receipt_number(row)
        if corp_code and receipt:
            sources_by_corp[corp_code][receipt] = row

    insider_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    document_cache: dict[str, str | None] = {}
    source_items = list(sources_by_corp.items())
    source_receipt_count = sum(len(sources) for _, sources in source_items)
    started_at = time.monotonic()
    document_processed = 0
    print(
        f"[DART 3/3] Insider ownership: {len(source_items):,} companies, "
        f"{source_receipt_count:,} disclosure receipts",
        flush=True,
    )
    for corp_index, (corp_code, sources) in enumerate(source_items, start=1):
        rows, error = dart_rows(
            session,
            api_key,
            "elestock",
            {"corp_code": corp_code},
        )
        if error:
            errors.append(error)
        else:
            for raw in rows:
                receipt = str(raw.get("rcept_no") or "").strip()
                source = sources.get(receipt)
                file_date = normalized_date(raw.get("rcept_dt"))
                if not source or file_date < cutoff:
                    continue
                shares_change = integer(raw.get("sp_stock_lmp_irds_cnt"))
                ticker = str(source.get("stock_code") or "").zfill(6)
                current_price = prices.get(ticker)
                if shares_change is None:
                    direction = "unknown"
                elif shares_change > 0:
                    direction = "increase"
                elif shares_change < 0:
                    direction = "decrease"
                else:
                    direction = "unchanged"

                if receipt not in document_cache:
                    document = fetch_document(session, api_key, receipt)
                    document_cache[receipt] = (
                        clean_document(document) if document else None
                    )
                    document_processed += 1
                    if (
                        document_processed == 1
                        or document_processed % max(progress_every, 1) == 0
                    ):
                        print(
                            f"[DART 3/3] ownership documents "
                            f"{document_processed}/{source_receipt_count} | "
                            f"rows {len(insider_rows)} | "
                            f"{time.monotonic() - started_at:.1f}s",
                            flush=True,
                        )
                    time.sleep(delay)
                reasons, confirmed_purchase = reason_from_document(
                    document_cache[receipt]
                )
                estimated_value = (
                    abs(shares_change) * current_price
                    if shares_change is not None and current_price is not None
                    else None
                )
                insider_rows.append(
                    {
                        **base_event(source),
                        "filer": str(raw.get("repror") or "").strip(),
                        "position": str(raw.get("isu_exctv_ofcps") or "").strip(),
                        "registered": str(
                            raw.get("isu_exctv_rgist_at") or ""
                        ).strip(),
                        "holder_type": str(
                            raw.get("isu_main_shrholdr") or ""
                        ).strip(),
                        "shares": integer(raw.get("sp_stock_lmp_cnt")),
                        "shares_change": shares_change,
                        "direction": direction,
                        "change_reasons": reasons,
                        "purchase_candidate": direction == "increase",
                        "confirmed_purchase": (
                            direction == "increase" and confirmed_purchase
                        ),
                        "current_price_krw": current_price,
                        "estimated_change_value_krw": estimated_value,
                        "estimate_note": (
                            "공시 수량 변화 × 수집 시점 현재가이며 실제 거래금액이 아님"
                            if estimated_value is not None
                            else None
                        ),
                    }
                )
        if should_log_progress(corp_index, len(source_items), progress_every):
            print(
                f"[DART 3/3] companies {corp_index}/{len(source_items)} "
                f"({progress_percent(corp_index, len(source_items)):.0f}%) | "
                f"ownership rows {len(insider_rows)} | errors {len(errors)} | "
                f"{time.monotonic() - started_at:.1f}s",
                flush=True,
            )
        time.sleep(delay)

    insider_rows.sort(
        key=lambda row: (
            row.get("file_date") or "",
            abs(int(row.get("shares_change") or 0)),
        ),
        reverse=True,
    )
    print(
        f"[DART 3/3] completed in {time.monotonic() - started_at:.1f}s",
        flush=True,
    )
    return insider_rows, errors


def main() -> None:
    load_env_file(ROOT_DIR / ".env")
    parser = argparse.ArgumentParser(
        description=(
            "Parse Korean dividend, contract, buyback, CB, and insider disclosures."
        )
    )
    parser.add_argument("--disclosures", default=str(DEFAULT_DISCLOSURES))
    parser.add_argument("--market-data", default=str(DEFAULT_MARKET))
    parser.add_argument("--events-output", default=str(DEFAULT_EVENTS_OUTPUT))
    parser.add_argument("--insiders-output", default=str(DEFAULT_INSIDERS_OUTPUT))
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument(
        "--progress-every",
        type=int,
        default=5,
        help="Print progress after this many documents or companies.",
    )
    args = parser.parse_args()
    progress_every = max(args.progress_every, 1)

    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DART_API_KEY is not set.")

    disclosure_payload = load_json(Path(args.disclosures))
    filings = disclosure_payload.get("filings") or []
    if not filings:
        raise SystemExit(
            f"No filings found in {args.disclosures}; run crawler_dart_disclosures.py first."
        )

    period = disclosure_payload.get("period") or {}
    today = datetime.now(KST).date()
    begin_date = str(period.get("begin") or (today - timedelta(days=30)).isoformat())
    end_date = str(period.get("end") or today.isoformat())
    begin = begin_date.replace("-", "")
    end = end_date.replace("-", "")
    overall_started_at = time.monotonic()
    print(
        f"[DART] Event details started: {len(filings):,} filings, "
        f"period {begin_date} to {end_date}",
        flush=True,
    )

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "ko-KR,ko;q=0.9",
        }
    )

    dividends, contracts, document_errors = collect_document_events(
        session,
        api_key,
        filings,
        args.delay,
        progress_every,
    )
    structured_events, structured_errors = collect_structured_events(
        session,
        api_key,
        filings,
        begin,
        end,
        args.delay,
        progress_every,
    )
    insiders, insider_errors = collect_insiders(
        session,
        api_key,
        filings,
        begin_date,
        load_prices(Path(args.market_data)),
        args.delay,
        progress_every,
    )

    buybacks = [
        row
        for row in structured_events
        if row.get("category") in {
            "buyback",
            "buyback_trust",
            "treasury_disposal",
        }
    ]
    convertible_bonds = [
        row
        for row in structured_events
        if row.get("category") == "convertible_bond"
    ]
    event_errors = document_errors + structured_errors
    event_payload = {
        "source": [
            "OpenDART document.xml",
            "OpenDART DS005 major event APIs",
        ],
        "reference_method": "Mir_US_Stocks disclosure parsing criteria",
        "period": {"begin": begin_date, "end": end_date},
        "crawled_at_utc": utc_now_iso(),
        "counts": {
            "dividends": len(dividends),
            "contracts": len(contracts),
            "buybacks": len(buybacks),
            "convertible_bonds": len(convertible_bonds),
        },
        "errors": event_errors[:100],
        "dividends": dividends,
        "contracts": contracts,
        "buybacks": buybacks,
        "convertible_bonds": convertible_bonds,
    }
    purchase_candidates = [
        row for row in insiders if row.get("purchase_candidate")
    ]
    confirmed_purchases = [
        row for row in insiders if row.get("confirmed_purchase")
    ]
    insider_payload = {
        "source": [
            "OpenDART elestock.json",
            "OpenDART document.xml",
        ],
        "reference_method": (
            "Mir_US_Stocks recent ownership-change criteria plus purchase-reason parsing"
        ),
        "period": {"begin": begin_date, "end": end_date},
        "crawled_at_utc": utc_now_iso(),
        "count": len(insiders),
        "purchase_candidate_count": len(purchase_candidates),
        "confirmed_purchase_count": len(confirmed_purchases),
        "interpretation_note": (
            "shares_change>0은 보유 증가 후보입니다. document.xml에서 장내·장외·"
            "시간외매수 문구가 확인된 경우만 confirmed_purchase=true입니다."
        ),
        "errors": insider_errors[:100],
        "confirmed_purchases": confirmed_purchases,
        "purchase_candidates": purchase_candidates,
        "rows": insiders,
    }
    atomic_write_json(Path(args.events_output), event_payload, compact=True)
    atomic_write_json(Path(args.insiders_output), insider_payload, compact=True)
    print(
        "[DART details] "
        f"dividends={len(dividends)}, contracts={len(contracts)}, "
        f"buybacks={len(buybacks)}, CB={len(convertible_bonds)}",
        flush=True,
    )
    print(
        "[DART insiders] "
        f"rows={len(insiders)}, candidates={len(purchase_candidates)}, "
        f"confirmed={len(confirmed_purchases)}",
        flush=True,
    )
    print(f"Output: {args.events_output}", flush=True)
    print(f"Output: {args.insiders_output}", flush=True)
    print(
        f"[DART] Event details completed in "
        f"{time.monotonic() - overall_started_at:.1f}s",
        flush=True,
    )


if __name__ == "__main__":
    main()
