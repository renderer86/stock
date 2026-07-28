from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from collector_common import USER_AGENT, atomic_write_json, utc_now_iso
from env_loader import load_env_file


ROOT_DIR = Path(__file__).resolve().parent
BASE_URL = "https://data-dbg.krx.co.kr/svc/apis"
DEFAULT_OUTPUT = Path("data/krx_openapi.json")

# KRX Open API의 공개 서비스 목록에 있는 EOD API만 사용한다.
DATASETS = {
    "kospi_stocks": "sto/stk_bydd_trd",
    "kosdaq_stocks": "sto/ksq_bydd_trd",
    "konex_stocks": "sto/knx_bydd_trd",
    "etf": "etp/etf_bydd_trd",
    "krx_indices": "idx/krx_dd_trd",
    "kospi_indices": "idx/kospi_dd_trd",
    "kosdaq_indices": "idx/kosdaq_dd_trd",
    "government_bonds": "bon/kts_bydd_trd",
}


def response_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    for key, value in payload.items():
        if key.lower().startswith("outblock") and isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def fetch_dataset(
    session: requests.Session,
    api_key: str,
    endpoint: str,
    start_date: datetime,
    lookback_days: int,
) -> dict[str, Any]:
    url = f"{BASE_URL}/{endpoint}"
    errors: list[str] = []

    for offset in range(lookback_days + 1):
        current = start_date - timedelta(days=offset)
        base_date = current.strftime("%Y%m%d")
        try:
            response = session.get(
                url,
                params={"basDd": base_date},
                headers={"AUTH_KEY": api_key},
                timeout=30,
            )
            if response.status_code in {401, 403}:
                return {
                    "status": "not_authorized",
                    "endpoint": endpoint,
                    "message": (
                        "인증키는 있지만 이 API 서비스의 이용신청이 승인되지 않았거나 "
                        "인증키가 유효하지 않습니다."
                    ),
                    "http_status": response.status_code,
                    "rows": [],
                }
            response.raise_for_status()
            rows = response_rows(response.json())
            if rows:
                return {
                    "status": "ok",
                    "endpoint": endpoint,
                    "base_date": base_date,
                    "count": len(rows),
                    "rows": rows,
                }
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{base_date}: {exc}")

    return {
        "status": "empty",
        "endpoint": endpoint,
        "message": f"최근 {lookback_days + 1}일에서 데이터를 찾지 못했습니다.",
        "errors": errors[-3:],
        "rows": [],
    }


def main() -> None:
    load_env_file(ROOT_DIR / ".env")
    parser = argparse.ArgumentParser(description="Collect official KRX Open API EOD datasets.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--lookback-days", type=int, default=10)
    args = parser.parse_args()

    api_key = os.environ.get("KRX_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("KRX_API_KEY is not set.")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    start_date = datetime.now(ZoneInfo("Asia/Seoul"))

    datasets: dict[str, Any] = {}
    for name, endpoint in DATASETS.items():
        result = fetch_dataset(
            session,
            api_key,
            endpoint,
            start_date,
            max(0, args.lookback_days),
        )
        datasets[name] = result
        print(f"[KRX] {name}: {result['status']} ({len(result.get('rows', []))} rows)")

    payload = {
        "source": "KRX Data Marketplace Open API",
        "base_url": BASE_URL,
        "crawled_at_utc": utc_now_iso(),
        "note": (
            "공식 Open API 서비스 목록의 일별 시세·지수·ETF·채권 데이터입니다. "
            "종목별 공매도 잔고와 투자자별 수급은 이 Open API 목록에 포함되지 않습니다."
        ),
        "datasets": datasets,
    }
    atomic_write_json(Path(args.output), payload, compact=True)
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
