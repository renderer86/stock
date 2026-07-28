from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from env_loader import load_env_file


ROOT_DIR = Path(__file__).resolve().parent
PROFILE_COMMANDS = {
    "rates": ["crawler_treasury_yields.py"],
    "market-close": ["run_all.py", "--skip-rates"],
    "all": ["run_all.py"],
}
PROFILE_REQUIRED_ENV = {
    "rates": ("ECOS_API_KEY",),
    "market-close": ("DART_API_KEY", "KRX_ID", "KRX_PW"),
    "all": ("ECOS_API_KEY", "DART_API_KEY", "KRX_ID", "KRX_PW"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one of the scheduled market-data collection profiles."
    )
    parser.add_argument(
        "profile",
        choices=PROFILE_COMMANDS,
        help="rates, market-close, or all",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate keys and print the selected command without crawling.",
    )
    return parser


def main() -> None:
    load_env_file(ROOT_DIR / ".env")
    args = build_parser().parse_args()

    missing = [
        key
        for key in PROFILE_REQUIRED_ENV[args.profile]
        if not os.environ.get(key, "").strip()
    ]
    if missing:
        names = ", ".join(missing)
        raise SystemExit(
            f"필수 환경변수가 없습니다: {names}. "
            "로컬은 .env, GitHub Actions는 Repository secrets에 등록하세요."
        )

    script, *arguments = PROFILE_COMMANDS[args.profile]
    command = [sys.executable, str(ROOT_DIR / script), *arguments]
    print(f"[PROFILE] {args.profile}", flush=True)
    print(f"[COMMAND] {Path(command[1]).name} {' '.join(arguments)}".rstrip(), flush=True)

    if args.dry_run:
        print("[DRY RUN] API 키 이름과 실행 구성을 확인했습니다.", flush=True)
        return

    result = subprocess.run(command, cwd=ROOT_DIR, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
