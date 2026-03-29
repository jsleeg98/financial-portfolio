#!/usr/bin/env python3
"""web/data/portfolio_config.json 생성

.env의 설정값을 읽어 대시보드가 참조하는 portfolio_config.json을 생성한다.

사용법:
    python scripts/generate_web_config.py

생성 파일:
    web/data/portfolio_config.json

지원 설정값 (.env):
    EXCLUDED_TICKERS  쉼표로 구분된 종목코드. 대시보드 보유종목 목록에서 숨김
                      (총자산 계산에는 포함됨).
                      예: EXCLUDED_TICKERS=KODEX미국S&P500,KODEX미국나스닥100
"""

import json
from pathlib import Path


def load_env() -> dict:
    env_path = Path(".env")
    if not env_path.exists():
        return {}
    result = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def main():
    env = load_env()

    raw = env.get("EXCLUDED_TICKERS", "")
    excluded = [t.strip() for t in raw.split(",") if t.strip()] if raw else []

    config = {"excludedTickers": excluded}

    out_path = Path("web/data/portfolio_config.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"portfolio_config.json 생성 완료")
    print(f"  excludedTickers: {excluded if excluded else '(없음)'}")


if __name__ == "__main__":
    main()
