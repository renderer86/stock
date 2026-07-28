from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests

from collector_common import USER_AGENT, atomic_write_json, utc_now_iso
from env_loader import load_env_file


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = Path("data/ai_market_briefing.json")
DEFAULT_MODEL = "gemini-2.5-flash"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def compact_context() -> dict[str, Any]:
    rates = load_json(Path("data/treasury_yields.json"))
    krx = load_json(Path("data/krx_openapi.json"))
    korea_flow = load_json(Path("data/korea_investor_flow.json"))
    korea_short = load_json(Path("data/korea_short_selling.json"))
    us = load_json(Path("data/us_market_snapshot.json"))
    news = load_json(Path("data/naver_news.json"))
    dart = load_json(Path("data/dart_disclosures.json"))
    finnhub = load_json(Path("data/us_finnhub.json"))
    short_interest = load_json(Path("data/us_finra_short_interest.json"))
    sec = load_json(Path("data/us_sec_filings.json"))

    us_stocks = us.get("stocks") or []
    us_ranked = sorted(
        us_stocks,
        key=lambda row: abs(float(row.get("change_pct") or 0)),
        reverse=True,
    )[:20]

    krx_summary: dict[str, Any] = {}
    for name, dataset in (krx.get("datasets") or {}).items():
        rows = dataset.get("rows") or []
        krx_summary[name] = {
            "base_date": dataset.get("base_date"),
            "count": len(rows),
            "sample": rows[:10],
        }

    return {
        "treasury_yields": rates,
        "krx_summary": krx_summary,
        "korea_investor_flow": {
            "trade_date": korea_flow.get("trade_date"),
            "markets": {
                market: {
                    "daily_net_value": (data.get("daily_net_value") or [])[-10:],
                    "leaders": {
                        investor: {
                            "net_buy": (ranking.get("net_buy") or [])[:10],
                            "net_sell": (ranking.get("net_sell") or [])[:10],
                        }
                        for investor, ranking in (data.get("top50") or {}).items()
                    },
                }
                for market, data in (korea_flow.get("markets") or {}).items()
            },
        },
        "korea_short_selling": {
            "transaction_date": korea_short.get("transaction_date"),
            "balance_date": korea_short.get("balance_date"),
            "markets": {
                market: {
                    "trade_ratio_top50": (data.get("trade_ratio_top50") or [])[:20],
                    "balance_top50": (data.get("balance_top50") or [])[:20],
                    "investor_daily_value": (data.get("investor_daily_value") or [])[-10:],
                }
                for market, data in (korea_short.get("markets") or {}).items()
            },
        },
        "us_top_absolute_movers": us_ranked,
        "latest_news": (news.get("items") or [])[:30],
        "dart_category_counts": dart.get("category_counts") or {},
        "latest_dart_filings": (dart.get("filings") or [])[:20],
        "finnhub_count": finnhub.get("count") or 0,
        "largest_short_interest": (short_interest.get("rows") or [])[:20],
        "sec_category_counts": sec.get("category_counts") or {},
    }


def extract_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {payload}")
    parts = (((candidates[0].get("content") or {}).get("parts")) or [])
    text = "\n".join(str(part.get("text") or "") for part in parts).strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    return text


def main() -> None:
    load_env_file(ROOT_DIR / ".env")
    parser = argparse.ArgumentParser(description="Generate a Korean market briefing from collected JSON.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set.")

    context = compact_context()
    prompt = (
        "아래는 자동 수집된 시장 데이터다. 제공된 사실만 사용해 한국어 장전·마감 "
        "통합 브리핑을 작성하라. 수치 기준일을 명시하고, 데이터가 없으면 없다고 말하라. "
        "투자 권유나 확정적 예측은 하지 마라.\n\n"
        "형식:\n"
        "1. 한 줄 요약\n2. 한국 시장 핵심 5개\n3. 미국 시장 핵심 5개\n"
        "4. 금리와 매크로\n5. 주요 뉴스와 공시\n6. 오늘 확인할 위험요인\n\n"
        f"수집 데이터(JSON):\n{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}"
    )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{args.model}:generateContent"
    )
    response = requests.post(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096},
        },
        timeout=120,
    )
    response.raise_for_status()
    text = extract_text(response.json())
    payload = {
        "source": "Gemini API + locally collected market JSON",
        "model": args.model,
        "generated_at_utc": utc_now_iso(),
        "briefing": text,
    }
    atomic_write_json(Path(args.output), payload)
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
