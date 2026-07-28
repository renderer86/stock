from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests

from collector_common import USER_AGENT
from env_loader import load_env_file


ROOT_DIR = Path(__file__).resolve().parent


def load_json(path: str) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def build_message(status: str, profile: str) -> str:
    us = load_json("data/us_market_snapshot.json")
    krx = load_json("data/krx_openapi.json")
    korea_flow = load_json("data/korea_investor_flow.json")
    korea_short = load_json("data/korea_short_selling.json")
    news = load_json("data/naver_news.json")
    dart = load_json("data/dart_disclosures.json")
    finnhub = load_json("data/us_finnhub.json")
    short_interest = load_json("data/us_finra_short_interest.json")
    sec = load_json("data/us_sec_filings.json")

    krx_ok = sum(
        dataset.get("status") == "ok"
        for dataset in (krx.get("datasets") or {}).values()
    )
    flow_count = sum(
        int(market.get("count") or 0)
        for market in (korea_flow.get("markets") or {}).values()
    )
    korea_short_count = sum(
        int(market.get("count") or 0)
        for market in (korea_short.get("markets") or {}).values()
    )
    marker = "✅" if status == "success" else "❌"
    lines = [
        f"{marker} stock 데이터 자동 갱신: {status}",
        f"프로필: {profile}",
        f"미국 종목: {us.get('count', 0):,}개 (차트 {us.get('history_count', 0):,}개)",
        f"Finnhub 보강: {finnhub.get('count', 0):,}개",
        f"FINRA 공매도 잔고: {short_interest.get('count', 0):,}개",
        f"SEC 확인 기업: {sec.get('company_count', 0):,}개",
        f"KRX 성공 데이터셋: {krx_ok}개",
        f"국내 수급: {flow_count:,}종목 ({korea_flow.get('trade_date') or '-'})",
        f"국내 공매도: {korea_short_count:,}종목 ({korea_short.get('transaction_date') or '-'})",
        f"네이버 뉴스: {news.get('count', 0):,}건",
        f"DART 공시: {dart.get('count', 0):,}건",
    ]
    return "\n".join(lines)


def main() -> None:
    load_env_file(ROOT_DIR / ".env")
    parser = argparse.ArgumentParser(description="Send the crawler result to Telegram.")
    parser.add_argument("--status", choices=["success", "failure"], required=True)
    parser.add_argument("--profile", default="all")
    args = parser.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram secrets are not set; notification skipped.")
        return

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        headers={"User-Agent": USER_AGENT},
        json={
            "chat_id": chat_id,
            "text": build_message(args.status, args.profile),
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    response.raise_for_status()
    print("Telegram notification sent.")


if __name__ == "__main__":
    main()
