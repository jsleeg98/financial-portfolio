#!/usr/bin/env python3
"""벤치마크 일별 종가 다운로드 스크립트

S&P 500(^GSPC)과 NASDAQ 100(^NDX)의 일별 종가를 다운로드하여 CSV로 저장한다.
기존 CSV가 있으면 마지막 날짜 이후의 데이터만 추가한다.

사용법:
    python scripts/fetch_benchmark.py
    python scripts/fetch_benchmark.py --start 2022-01-01
"""

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

BENCHMARKS = {
    "sp500": {"symbol": "^GSPC", "file": "sp500_daily.csv"},
    "nasdaq100": {"symbol": "^NDX", "file": "nasdaq100_daily.csv"},
    "kospi": {"symbol": "^KS11", "file": "kospi_daily.csv"},
    "usdkrw": {"symbol": "KRW=X", "file": "usdkrw_daily.csv"},
}

DEFAULT_START = "2019-12-01"


def load_existing(filepath: Path) -> pd.DataFrame | None:
    """기존 CSV를 로드한다. 없으면 None 반환."""
    if not filepath.exists():
        return None
    df = pd.read_csv(filepath, parse_dates=["Date"])
    return df


def fetch_and_save(name: str, info: dict, start_date: str) -> None:
    """벤치마크 데이터를 다운로드하고 CSV로 저장한다."""
    filepath = OUTPUT_DIR / info["file"]
    existing = load_existing(filepath)

    if existing is not None and len(existing) > 0:
        last_date = existing["Date"].max()
        fetch_start = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"  {name}: 기존 {len(existing)}건, 마지막 날짜 {last_date.strftime('%Y-%m-%d')}")
    else:
        fetch_start = start_date
        print(f"  {name}: 새로 다운로드 (시작: {fetch_start})")

    today = datetime.now().strftime("%Y-%m-%d")
    if fetch_start >= today:
        print(f"  {name}: 이미 최신 데이터")
        return

    print(f"  {name}: {fetch_start} ~ {today} 다운로드 중...")
    ticker = yf.Ticker(info["symbol"])
    hist = ticker.history(start=fetch_start, end=today)

    if hist.empty:
        print(f"  {name}: 새 데이터 없음")
        return

    new_df = hist[["Close"]].reset_index()
    new_df.columns = ["Date", "Close"]
    new_df["Date"] = pd.to_datetime(new_df["Date"]).dt.tz_localize(None)
    new_df["Close"] = new_df["Close"].round(2)

    if existing is not None and len(existing) > 0:
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["Date"], keep="last")
    else:
        combined = new_df

    combined = combined.sort_values("Date").reset_index(drop=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_csv(filepath, index=False)
    print(f"  {name}: {len(combined)}건 저장 → {filepath}")


def main():
    parser = argparse.ArgumentParser(description="벤치마크 일별 종가 다운로드")
    parser.add_argument("--start", default=DEFAULT_START, help="시작 날짜 (기본: 2019-12-01)")
    args = parser.parse_args()

    print("=== 벤치마크 데이터 다운로드 ===\n")

    for name, info in BENCHMARKS.items():
        fetch_and_save(name, info, args.start)

    print("\n=== 완료 ===")


if __name__ == "__main__":
    main()
