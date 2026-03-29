#!/usr/bin/env python3
"""과거 월별 종가 조회 및 캐시 스크립트

output/종합거래내역.csv에서 보유 종목을 파악하고,
누락된 월별 종가를 yfinance로 조회하여 저장한다.
기존 캐시가 있으면 누락분만 추가한다.

저장 위치:
  output/price_history.json  — 로컬 캐시 (gitignore)
  web/data/price_history.json — GitHub Pages 배포용 (커밋 필요)

사용법:
    source .venv/bin/activate
    python scripts/fetch_historical_prices.py
"""

import json
import csv
import os
import sys
import requests
from datetime import datetime
from collections import defaultdict
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent

KNOWN_SYMBOLS_PATH = ROOT / "output" / "known_symbols.json"


def _load_known_symbols() -> dict[str, str]:
    """output/known_symbols.json에서 KRW 종목명 → Yahoo Finance 심볼 매핑 로드.
    중첩 그룹 구조를 평탄화하고 빈 문자열(미확인) 항목은 제외한다."""
    if not KNOWN_SYMBOLS_PATH.exists():
        return {}
    with open(KNOWN_SYMBOLS_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    result = {}
    for group in raw.values():
        if not isinstance(group, dict):
            continue
        for name, symbol in group.items():
            if symbol:  # 빈 문자열 제외
                result[name] = symbol
    return result


KNOWN_SYMBOLS: dict[str, str] = _load_known_symbols()

CSV_PATH     = ROOT / "output" / "종합거래내역.csv"
CACHE_PATH   = ROOT / "output" / "price_history.json"
WEB_PATH     = ROOT / "web" / "data" / "price_history.json"
SYM_CACHE    = ROOT / "output" / "symbol_cache.json"


# ── 유틸 ────────────────────────────────────────────────────────
def load_json(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def month_range(start: str, end: str) -> list[str]:
    """'YYYY-MM' 범위의 모든 월 목록 반환 (inclusive)."""
    result = []
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    while (y, m) <= (ey, em):
        result.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return result


# ── KRW 종목 심볼 조회 ───────────────────────────────────────────
def resolve_krw_symbol(ticker: str) -> str | None:
    """KRW 종목명 → Yahoo Finance 심볼 변환.
    1) KNOWN_SYMBOLS 우선 확인
    2) Yahoo Finance 검색 API 시도 (한글 미지원 — 영문명/코드 등록 종목만 가능)
    """
    # 1) 수동 매핑 우선
    if ticker in KNOWN_SYMBOLS:
        return KNOWN_SYMBOLS[ticker]
    # 2) 검색 API 시도
    try:
        resp = requests.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": ticker, "quotesCount": 6, "newsCount": 0, "listsCount": 0},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        for q in resp.json().get("quotes", []):
            sym = q.get("symbol", "")
            if sym.endswith(".KS") or sym.endswith(".KQ"):
                return sym
    except Exception as e:
        print(f"  심볼 검색 실패 ({ticker}): {e}")
    return None


# ── 시세 조회 ────────────────────────────────────────────────────
def fetch_monthly(yf_symbol: str, start_month: str) -> dict[str, float]:
    """yfinance로 월별 종가 조회. { 'YYYY-MM': close } 반환."""
    hist = yf.Ticker(yf_symbol).history(
        start=f"{start_month}-01", interval="1mo", auto_adjust=True
    )
    if hist.empty:
        return {}
    result = {}
    for idx, row in hist.iterrows():
        m = idx.strftime("%Y-%m")
        result[m] = round(float(row["Close"]), 4)
    return result


# ── 메인 ────────────────────────────────────────────────────────
def main():
    today_ym = datetime.today().strftime("%Y-%m")
    # 이전 월까지만 저장 (현재 월은 미완성)
    y, m = map(int, today_ym.split("-"))
    m -= 1
    if m == 0:
        m, y = 12, y - 1
    prev_ym = f"{y:04d}-{m:02d}"

    if not CSV_PATH.exists():
        sys.exit(f"CSV 없음: {CSV_PATH}")

    # ── 거래내역에서 종목별 통화·거래 기간 파악 ──────────────────
    ticker_info: dict[str, dict] = defaultdict(lambda: {"currency": None, "first": None, "last": None})
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            t = row.get("종목코드", "").strip()
            if not t:
                continue
            currency = row.get("통화", "").strip() or None
            date_str = row.get("거래일자", "").strip()
            if len(date_str) < 7:
                continue
            month = date_str[:7]
            if currency:
                ticker_info[t]["currency"] = currency
            info = ticker_info[t]
            if info["first"] is None or month < info["first"]:
                info["first"] = month
            if info["last"] is None or month > info["last"]:
                info["last"] = month

    # ── 캐시 로드 ────────────────────────────────────────────────
    cache = load_json(CACHE_PATH)
    sym_cache = load_json(SYM_CACHE)

    updated = 0
    sym_cache_dirty = False

    for ticker, info in sorted(ticker_info.items()):
        currency = info["currency"]
        first, last = info["first"], info["last"]
        if not first:
            continue

        # 조회 범위: 첫 거래 월 ~ 이전 월
        end = min(last, prev_ym) if last < today_ym else prev_ym
        all_months = month_range(first, end)
        missing = [mo for mo in all_months if cache.get(ticker, {}).get(mo) is None]
        if not missing:
            continue

        # Yahoo Finance 심볼 결정
        if currency == "USD":
            yf_symbol = ticker
        else:
            if ticker not in sym_cache:
                print(f"  심볼 검색: {ticker}")
                sym_cache[ticker] = resolve_krw_symbol(ticker)
                sym_cache_dirty = True
            yf_symbol = sym_cache[ticker]
            if not yf_symbol:
                print(f"  심볼 없음 (스킵): {ticker}")
                continue

        print(f"조회: {ticker:30s} ({yf_symbol:15s})  {missing[0]} ~ {missing[-1]}  ({len(missing)}개월)")
        try:
            prices = fetch_monthly(yf_symbol, missing[0])
            if not prices:
                print(f"  데이터 없음")
                continue
            if ticker not in cache:
                cache[ticker] = {}
            for mo, price in prices.items():
                if mo <= prev_ym:   # 현재 월 제외
                    cache[ticker][mo] = price
            updated += 1
        except Exception as e:
            print(f"  조회 실패: {e}")

    if sym_cache_dirty:
        save_json(SYM_CACHE, sym_cache)

    if updated > 0:
        save_json(CACHE_PATH, cache)
        save_json(WEB_PATH, cache)
        print(f"\n✓ {updated}개 종목 업데이트 → {CACHE_PATH.name}, {WEB_PATH.name}")
    else:
        print("새로 조회할 데이터 없음")


if __name__ == "__main__":
    main()
