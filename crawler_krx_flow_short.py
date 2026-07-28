from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from collector_common import atomic_write_json, utc_now_iso
from env_loader import load_env_file


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_FLOW_OUTPUT = Path("data/korea_investor_flow.json")
DEFAULT_SHORT_OUTPUT = Path("data/korea_short_selling.json")
MARKETS = ("KOSPI", "KOSDAQ")
INVESTORS = {
    "foreign": "외국인",
    "institution": "기관합계",
    "individual": "개인",
}
FLOW_COLUMNS = {
    "종목명": "name",
    "매도거래량": "sell_volume",
    "매수거래량": "buy_volume",
    "순매수거래량": "net_volume",
    "매도거래대금": "sell_value",
    "매수거래대금": "buy_value",
    "순매수거래대금": "net_value",
}
SHORT_TRADE_COLUMNS = {
    "공매도": "short_volume",
    "매수": "total_volume",
    "비중": "volume_ratio",
}
SHORT_VALUE_COLUMNS = {
    "공매도": "short_value",
    "매수": "total_value",
    "비중": "value_ratio",
}
SHORT_BALANCE_COLUMNS = {
    "순위": "rank",
    "공매도잔고": "short_balance",
    "상장주식수": "listed_shares",
    "공매도금액": "short_balance_value",
    "시가총액": "market_cap",
    "비중": "balance_ratio",
}
SHORT_TOP_COLUMNS = {
    "순위": "rank",
    "공매도거래대금": "short_value",
    "총거래대금": "total_value",
    "공매도비중": "short_ratio",
    "직전40일거래대금평균": "average_value_40d",
    "공매도거래대금증가율": "short_value_change_ratio",
    "직전40일공매도평균비중": "average_short_ratio_40d",
    "공매도비중증가율": "short_ratio_change_ratio",
    "주가수익률": "price_return",
}


def require_login() -> None:
    missing = [
        name
        for name in ("KRX_ID", "KRX_PW")
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        raise SystemExit(
            f"Required KRX login environment variables are missing: {', '.join(missing)}"
        )


def scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    if hasattr(value, "to_pydatetime"):
        converted = value.to_pydatetime()
        return converted.date().isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float) and value != value:
        return None
    return value


def frame_records(
    frame: Any,
    *,
    columns: dict[str, str] | None = None,
    index_name: str,
) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    reset = frame.reset_index()
    source_index = str(reset.columns[0])
    records: list[dict[str, Any]] = []
    for raw in reset.to_dict(orient="records"):
        row = {index_name: scalar(raw.pop(source_index))}
        for key, value in raw.items():
            output_key = (columns or {}).get(str(key), str(key))
            row[output_key] = scalar(value)
        records.append(row)
    return records


def yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def find_latest(
    label: str,
    fetch: Callable[[str], Any],
    *,
    lookback_days: int,
) -> tuple[date, Any]:
    last_error: Exception | None = None
    for offset in range(lookback_days + 1):
        candidate = date.today() - timedelta(days=offset)
        try:
            frame = fetch(yyyymmdd(candidate))
            if frame is not None and not frame.empty:
                print(f"[DATE] {label}: {candidate.isoformat()}", flush=True)
                return candidate, frame
        except Exception as exc:  # pykrx raises request/parser-specific exceptions
            last_error = exc
            print(
                f"[RETRY] {label} {candidate.isoformat()}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
        time.sleep(0.15)
    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(
        f"No valid {label} data found in the last {lookback_days + 1} days{detail}"
    )


def load_name_map() -> dict[str, str]:
    path = ROOT_DIR / "data" / "market_sum.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        str(row.get("code")): str(row.get("name"))
        for row in (payload.get("stocks") or [])
        if row.get("code") and row.get("name")
    }


def add_names(rows: list[dict[str, Any]], names: dict[str, str]) -> None:
    for row in rows:
        ticker = str(row.get("ticker") or "")
        if ticker:
            row["name"] = names.get(ticker)


def flow_rows(frame: Any, investor_key: str) -> dict[str, dict[str, Any]]:
    rows = frame_records(
        frame,
        columns=FLOW_COLUMNS,
        index_name="ticker",
    )
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = str(row.pop("ticker"))
        name = row.pop("name", None)
        result[ticker] = {
            "ticker": ticker,
            "name": name,
            investor_key: row,
        }
    return result


def collect_investor_flow(stock: Any, trade_date: date, history_days: int) -> dict[str, Any]:
    start = trade_date - timedelta(days=max(history_days, 1) - 1)
    markets: dict[str, Any] = {}
    for market in MARKETS:
        merged: dict[str, dict[str, Any]] = {}
        for investor_key, investor_name in INVESTORS.items():
            print(f"[FETCH] {market} {investor_name} ticker flow", flush=True)
            frame = stock.get_market_net_purchases_of_equities(
                yyyymmdd(trade_date),
                yyyymmdd(trade_date),
                market,
                investor_name,
            )
            for ticker, item in flow_rows(frame, investor_key).items():
                target = merged.setdefault(
                    ticker,
                    {"ticker": ticker, "name": item.get("name")},
                )
                if not target.get("name") and item.get("name"):
                    target["name"] = item["name"]
                target[investor_key] = item[investor_key]
            time.sleep(0.2)

        rows = list(merged.values())
        for row in rows:
            for investor_key in INVESTORS:
                row.setdefault(investor_key, None)
        rows.sort(
            key=lambda row: abs(
                int(((row.get("foreign") or {}).get("net_value")) or 0)
            ),
            reverse=True,
        )

        history_frame = stock.get_market_trading_value_by_date(
            yyyymmdd(start),
            yyyymmdd(trade_date),
            market,
            detail=True,
        )
        rankings: dict[str, Any] = {}
        for investor_key in INVESTORS:
            available = [
                row for row in rows if isinstance(row.get(investor_key), dict)
            ]
            rankings[investor_key] = {
                "net_buy": sorted(
                    available,
                    key=lambda row: int(
                        ((row[investor_key] or {}).get("net_value")) or 0
                    ),
                    reverse=True,
                )[:50],
                "net_sell": sorted(
                    available,
                    key=lambda row: int(
                        ((row[investor_key] or {}).get("net_value")) or 0
                    ),
                )[:50],
            }
        markets[market] = {
            "count": len(rows),
            "by_ticker": rows,
            "top50": rankings,
            "daily_net_value": frame_records(
                history_frame,
                index_name="date",
            ),
        }
    return {
        "source": "KRX authenticated data via pykrx",
        "crawled_at_utc": utc_now_iso(),
        "trade_date": trade_date.isoformat(),
        "history": {
            "from": start.isoformat(),
            "to": trade_date.isoformat(),
        },
        "unit": {
            "volume": "shares",
            "value": "KRW",
        },
        "markets": markets,
    }


def merge_short_trade(
    volume_frame: Any,
    value_frame: Any,
    names: dict[str, str],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in frame_records(
        volume_frame,
        columns=SHORT_TRADE_COLUMNS,
        index_name="ticker",
    ):
        ticker = str(row.pop("ticker"))
        merged[ticker] = {"ticker": ticker, "name": names.get(ticker), **row}
    for row in frame_records(
        value_frame,
        columns=SHORT_VALUE_COLUMNS,
        index_name="ticker",
    ):
        ticker = str(row.pop("ticker"))
        merged.setdefault(
            ticker,
            {"ticker": ticker, "name": names.get(ticker)},
        ).update(row)
    rows = list(merged.values())
    rows.sort(
        key=lambda row: float(row.get("value_ratio") or row.get("volume_ratio") or 0),
        reverse=True,
    )
    return rows


def collect_short_selling(
    stock: Any,
    trade_date: date,
    balance_date: date,
    history_days: int,
    names: dict[str, str],
) -> dict[str, Any]:
    start = trade_date - timedelta(days=max(history_days, 1) - 1)
    markets: dict[str, Any] = {}
    for market in MARKETS:
        print(f"[FETCH] {market} short-selling transactions", flush=True)
        volume_frame = stock.get_shorting_volume_by_ticker(
            yyyymmdd(trade_date),
            market,
        )
        value_frame = stock.get_shorting_value_by_ticker(
            yyyymmdd(trade_date),
            market,
        )
        trade_rows = merge_short_trade(volume_frame, value_frame, names)

        balance_rows = frame_records(
            stock.get_shorting_balance_top50(
                yyyymmdd(balance_date),
                market=market,
            ),
            columns=SHORT_BALANCE_COLUMNS,
            index_name="ticker",
        )
        add_names(balance_rows, names)

        top_rows = frame_records(
            stock.get_shorting_volume_top50(
                yyyymmdd(trade_date),
                market,
            ),
            columns=SHORT_TOP_COLUMNS,
            index_name="ticker",
        )
        add_names(top_rows, names)

        investor_volume = frame_records(
            stock.get_shorting_investor_volume_by_date(
                yyyymmdd(start),
                yyyymmdd(trade_date),
                market,
            ),
            index_name="date",
        )
        investor_value = frame_records(
            stock.get_shorting_investor_value_by_date(
                yyyymmdd(start),
                yyyymmdd(trade_date),
                market,
            ),
            index_name="date",
        )
        markets[market] = {
            "count": len(trade_rows),
            "by_ticker": trade_rows,
            "trade_ratio_top50": top_rows,
            "balance_top50": balance_rows,
            "investor_daily_volume": investor_volume,
            "investor_daily_value": investor_value,
        }
    return {
        "source": "KRX authenticated data via pykrx",
        "crawled_at_utc": utc_now_iso(),
        "transaction_date": trade_date.isoformat(),
        "balance_date": balance_date.isoformat(),
        "balance_delay_note": (
            "KRX short balance data is normally published with a business-day delay."
        ),
        "history": {
            "from": start.isoformat(),
            "to": trade_date.isoformat(),
        },
        "unit": {
            "volume": "shares",
            "value": "KRW",
            "ratio": "percent",
        },
        "markets": markets,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect authenticated KRX investor-flow and short-selling data."
    )
    parser.add_argument("--flow-output", default=str(DEFAULT_FLOW_OUTPUT))
    parser.add_argument("--short-output", default=str(DEFAULT_SHORT_OUTPUT))
    parser.add_argument("--lookback-days", type=int, default=14)
    parser.add_argument("--history-days", type=int, default=31)
    return parser


def main() -> None:
    load_env_file(ROOT_DIR / ".env")
    args = build_parser().parse_args()
    require_login()

    try:
        from pykrx import stock
    except ImportError as exc:
        raise SystemExit(
            "pykrx is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    flow_date, _ = find_latest(
        "investor flow",
        lambda value: stock.get_market_net_purchases_of_equities(
            value,
            value,
            "KOSPI",
            "외국인",
        ),
        lookback_days=args.lookback_days,
    )
    short_date, _ = find_latest(
        "short transactions",
        lambda value: stock.get_shorting_volume_by_ticker(value, "KOSPI"),
        lookback_days=args.lookback_days,
    )
    balance_date, _ = find_latest(
        "short balance",
        lambda value: stock.get_shorting_balance_top50(value, market="KOSPI"),
        lookback_days=args.lookback_days,
    )

    names = load_name_map()
    flow_payload = collect_investor_flow(stock, flow_date, args.history_days)
    short_payload = collect_short_selling(
        stock,
        short_date,
        balance_date,
        args.history_days,
        names,
    )
    atomic_write_json(Path(args.flow_output), flow_payload)
    atomic_write_json(Path(args.short_output), short_payload)
    print(
        f"Investor flow: {args.flow_output} "
        f"({sum(market['count'] for market in flow_payload['markets'].values()):,} rows)"
    )
    print(
        f"Short selling: {args.short_output} "
        f"({sum(market['count'] for market in short_payload['markets'].values()):,} rows)"
    )


if __name__ == "__main__":
    main()
