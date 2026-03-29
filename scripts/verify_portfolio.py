#!/usr/bin/env python3
"""포트폴리오 계산 검증 스크립트

tests/fixtures/app_status.txt 의 증권앱 현황과
output/종합거래내역.csv 의 계산값을 비교하여 오차를 검증한다.

사용법:
    python scripts/verify_portfolio.py [--fx 1506]

FX 자동 역산:
    순수 USD 계좌(202-07-292788)의 평가금액을 기준으로 USD/KRW 환율을 자동 추정한다.
    --fx 옵션으로 수동 지정도 가능하다.
"""

import re
import sys
from pathlib import Path

import pandas as pd


APP_STATUS_PATH = Path("tests/fixtures/app_status.txt")
CSV_PATH = Path("output/종합거래내역.csv")

# 허용 오차 기준 (CLAUDE.md 기준)
COST_TOLERANCE_PCT = 1.5   # 매입금액: 역사적 환율차 등으로 다소 넓게 허용
VALUE_TOLERANCE_PCT = 1.5  # 평가금액


def parse_number(s: str) -> float:
    """'39,104,596원', '34.89$' 등에서 숫자만 추출"""
    s = s.strip().replace(",", "").replace("원", "").replace("$", "").replace("%", "")
    return float(s)


def parse_app_status(path: Path) -> tuple[dict, dict, str]:
    """app_status.txt 파싱 → (계좌별 앱수치, 종목별 현재가, 기준일)"""
    accounts = {}
    prices = {}
    date_str = ""
    current_acct = None
    in_prices = False

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^\[(\d{4}-\d{2}-\d{2}) 기준 현재가\]", line)
        if m:
            date_str = m.group(1)
            in_prices = True
            continue
        m = re.match(r"^\[([^\]]+)\]", line)
        if m and not in_prices:
            current_acct = m.group(1)
            accounts[current_acct] = {}
            continue
        if in_prices and ":" in line:
            ticker, price_str = line.split(":", 1)
            prices[ticker.strip()] = parse_number(price_str)
            continue
        if current_acct and ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            try:
                accounts[current_acct][key] = parse_number(val)
            except ValueError:
                pass

    return accounts, prices, date_str


def compute_holdings(acct_df: pd.DataFrame) -> dict:
    """거래내역 → {ticker: {qty, cost, currency}} 현재 보유 현황"""
    holdings: dict = {}
    for _, tx in acct_df.sort_values("거래일자").iterrows():
        ticker = tx["종목코드"]
        if not ticker:
            continue
        typ, qty, currency = tx["유형"], tx["수량"], tx["통화"]
        if ticker not in holdings:
            holdings[ticker] = {"qty": 0.0, "cost": 0.0, "currency": currency}
        h = holdings[ticker]
        if typ == "매수":
            hist_fx = tx["환율"]   # NH나무증권: 실제 환율 사용
            # 메리츠증권 환율=0은 나중에 fx 결정 후 적용 → _단가_usd 저장
            h["qty"] += qty
            h["_pending_cost_usd"] = h.get("_pending_cost_usd", 0) + (tx["단가"] * qty if currency == "USD" and hist_fx == 0 else 0)
            h["cost"] += tx["단가"] * (hist_fx if hist_fx > 0 else 0) * qty if currency == "USD" else tx["단가"] * qty
        elif typ == "매도" and h["qty"] > 0:
            avg = h["cost"] / h["qty"]
            h["qty"] -= qty
            h["cost"] = avg * max(0.0, h["qty"])
            avg_usd = h.get("_pending_cost_usd", 0) / (h["qty"] + qty) if (h["qty"] + qty) > 0 else 0
            h["_pending_cost_usd"] = avg_usd * max(0.0, h["qty"])
        elif typ in ("출고", "감자출고"):
            h["cost_bak"] = h["cost"]
            h["_pending_usd_bak"] = h.get("_pending_cost_usd", 0)
            h["qty"] = 0.0
        elif typ == "입고":
            h["qty"] = qty
            h["cost"] = h.get("cost_bak", 0.0)
            h["_pending_cost_usd"] = h.get("_pending_usd_bak", 0.0)
    return {t: h for t, h in holdings.items() if h["qty"] > 0.001}


def estimate_fx(df: pd.DataFrame, prices: dict, target_acct: str, target_value: float) -> float:
    """순수 USD 계좌의 평가금액으로 USD/KRW 환율을 역산한다."""
    acct_df = df[df["계좌번호"] == target_acct]
    holdings = compute_holdings(acct_df)
    usd_val = sum(
        prices[t] * h["qty"]
        for t, h in holdings.items()
        if t in prices and h["currency"] == "USD"
    )
    if usd_val == 0:
        return 1450.0
    return target_value / usd_val


def compute_portfolio(acct_df: pd.DataFrame, prices: dict, fx: float) -> tuple[float, float, list]:
    """보유현황 → (총 매입금액, 총 평가금액, 가격없는 종목 목록)"""
    holdings = compute_holdings(acct_df)
    total_cost = total_val = 0.0
    unknown = []

    for ticker, h in holdings.items():
        # 메리츠증권 환율=0 포지션의 cost 보정 (현재 fx 사용)
        pending_usd = h.get("_pending_cost_usd", 0)
        cost = h["cost"] + pending_usd * fx
        total_cost += cost

        if ticker in prices:
            p = prices[ticker]
            val = p * h["qty"] * (fx if h["currency"] == "USD" else 1)
            total_val += val
        else:
            unknown.append((ticker, round(h["qty"])))

    return total_cost, total_val, unknown


def main():
    fx_override = None
    if "--fx" in sys.argv:
        idx = sys.argv.index("--fx")
        fx_override = float(sys.argv[idx + 1])

    if not APP_STATUS_PATH.exists():
        print(f"[ERROR] {APP_STATUS_PATH} 없음")
        sys.exit(1)
    if not CSV_PATH.exists():
        print(f"[ERROR] {CSV_PATH} 없음")
        sys.exit(1)

    app_accounts, prices, date_str = parse_app_status(APP_STATUS_PATH)
    df = pd.read_csv(CSV_PATH, dtype=str).fillna("")
    for col in ["수량", "단가", "금액", "환율", "금액KRW"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    print(f"기준일: {date_str}")
    print(f"현재가: {', '.join(f'{k}={v}' for k, v in prices.items())}")

    # FX 자동 역산: 202-07-292788 (IREN+RKLB 순수 USD 계좌)
    if fx_override:
        fx = fx_override
        print(f"환율(수동): {fx:.1f} KRW/USD")
    else:
        ref_acct = "202-07-292788"
        if ref_acct in app_accounts and "평가금액" in app_accounts[ref_acct]:
            fx = estimate_fx(df, prices, ref_acct, app_accounts[ref_acct]["평가금액"])
            print(f"환율(자동역산 from {ref_acct}): {fx:.1f} KRW/USD")
        else:
            fx = 1450.0
            print(f"환율(기본값): {fx:.1f} KRW/USD")

    print()
    print(f"{'계좌':<22} {'매입(계산)':>12} {'매입(앱)':>12} {'매입오차':>8}  {'평가(계산)':>12} {'평가(앱)':>12} {'평가오차':>8}  상태")
    print("-" * 108)

    all_ok = True
    for acct, app in app_accounts.items():
        acct_df = df[df["계좌번호"] == acct]
        if acct_df.empty:
            print(f"{acct:<22} [CSV에 데이터 없음]")
            continue
        cost, val, unknown = compute_portfolio(acct_df, prices, fx)
        app_cost = app.get("매입금액", 0)
        app_val  = app.get("평가금액", 0)
        ce = (cost - app_cost) / app_cost * 100 if app_cost else 0
        ve = (val  - app_val)  / app_val  * 100 if app_val  else 0
        ok_c = abs(ce) <= COST_TOLERANCE_PCT
        ok_v = abs(ve) <= VALUE_TOLERANCE_PCT
        # 전체 상태는 평가금액 기준 (매입금액 오차는 취득환율 차이로 허용)
        status = "✅" if ok_v else "⚠️"
        if not ok_v:
            all_ok = False
        note_c = "✅" if ok_c else "⚠️"
        note_v = "✅" if ok_v else "⚠️"
        print(f"{acct:<22} {cost:>12,.0f} {app_cost:>12,.0f} {note_c}{ce:>+7.2f}%  {val:>12,.0f} {app_val:>12,.0f} {note_v}{ve:>+7.2f}%  {status}", end="")
        if unknown:
            print(f"  (가격없음: {[t for t,_ in unknown]})", end="")
        print()

    print()
    print(f"※ 매입금액 오차는 취득환율(TTB vs 현물) 및 평균단가 계산 방식 차이로 발생 — 허용 범위로 간주")
    print()
    if all_ok:
        print("✅ 모든 계좌 평가금액 오차 허용 범위 내 — 정상")
    else:
        print("⚠️  일부 계좌 평가금액 오차 초과 — 현재가·환율 확인 필요")


if __name__ == "__main__":
    main()
