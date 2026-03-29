#!/usr/bin/env python3
"""포트폴리오 계산 검증 스크립트

tests/fixtures/app_status.txt 의 증권앱 현황과
output/종합거래내역.csv 의 계산값을 비교하여 오차를 검증한다.

비교 기준:
  앱 총자산 = 평가금액 + 예수금(원화) + 예수금(달러) × FX
  계산 총자산 = 주식평가 + 계산현금(KRW) + 계산현금(USD) × FX

현금 한계:
  - NH나무증권 종합파일: 외화 잔고금액 컬럼 없음 → USD 현금 미추적
  - 메리츠/토스: 파일 종료일 이후 배당·이자는 반영 안 됨

사용법:
    python scripts/verify_portfolio.py [--fx 1506]

FX 자동 역산:
    순수 USD 계좌(202-07-292788)의 평가금액을 기준으로 USD/KRW 환율을 자동 추정한다.
    --fx 옵션으로 수동 지정도 가능하다.
"""

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


APP_STATUS_PATH = Path("tests/fixtures/app_status.txt")
CSV_PATH = Path("output/종합거래내역.csv")

# 허용 오차 기준
TOTAL_TOLERANCE_PCT = 1.5   # 총자산(주식+현금)
COST_TOLERANCE_PCT  = 1.5   # 매입금액 (취득환율 차이로 별도 허용)
CASH_TOLERANCE_KRW  = 10_000  # 현금 허용 오차 (원화 절대값)
CASH_TOLERANCE_USD  = 5.0     # 현금 허용 오차 (달러 절대값)


def parse_number(s: str) -> float:
    """'39,104,596원', '34.89$' 등에서 숫자만 추출"""
    s = s.strip().replace(",", "").replace("원", "").replace("$", "").replace("%", "")
    return float(s)


def parse_app_status(path: Path) -> tuple[dict, dict, str]:
    """app_status.txt 파싱 → (계좌별 앱수치, 종목별 현재가, 기준일)

    계좌별 앱수치: {
        '평가금액': float,
        '매입금액': float,
        '예수금(원화)': float,  # 새 필드
        '예수금(달러)': float,  # 새 필드
    }
    """
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
            hist_fx = tx["환율"]
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


def compute_cash_snapshot(acct_df: pd.DataFrame, verify_date: str, fx: float) -> tuple[float, float]:
    """CSV의 현금잔고 행에서 USD·KRW 현금을 계산한다 (90일 이내 스냅샷만).

    Returns: (cash_usd, cash_krw)
    """
    cash_rows = acct_df[acct_df["유형"] == "현금잔고"].sort_values("거래일자")
    if cash_rows.empty:
        return 0.0, 0.0

    if verify_date:
        cutoff = (datetime.strptime(verify_date, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
        cash_rows = cash_rows[cash_rows["거래일자"] >= cutoff]

    cash_usd = cash_krw = 0.0
    for currency, grp in cash_rows.groupby("통화"):
        last = grp.iloc[-1]
        if currency == "USD":
            usd = float(last["금액"]) if float(last["금액"]) > 0 else float(last["금액KRW"]) / fx
            cash_usd += usd
        elif currency == "KRW":
            cash_krw += float(last["금액KRW"])
    return cash_usd, cash_krw


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


def compute_stock_value(acct_df: pd.DataFrame, prices: dict, fx: float) -> tuple[float, float, list]:
    """보유 주식 → (총 매입금액, 주식 평가금액, 가격없는 종목 목록)"""
    holdings = compute_holdings(acct_df)
    total_cost = total_val = 0.0
    unknown = []
    for ticker, h in holdings.items():
        pending_usd = h.get("_pending_cost_usd", 0)
        cost = h["cost"] + pending_usd * fx
        total_cost += cost
        if ticker in prices:
            val = prices[ticker] * h["qty"] * (fx if h["currency"] == "USD" else 1)
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

    # FX 자동 역산: 202-07-292788 (IREN+RKLB 순수 USD 계좌, 예수금=0)
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

    # ── 총자산 비교 ─────────────────────────────────────────────────
    # 앱 총자산 = 평가금액 + 예수금(원화) + 예수금(달러) × FX
    # 계산 총자산 = 주식평가 + 계산현금(KRW) + 계산현금(USD) × FX
    print()
    print(f"{'계좌':<22} {'주식(계산)':>12} {'주식(앱)':>12} {'주식오차':>8}  "
          f"{'총자산(계산)':>12} {'총자산(앱)':>12} {'총자산오차':>9}  상태")
    print("-" * 118)

    all_ok = True
    results = {}

    for acct, app in app_accounts.items():
        acct_df = df[df["계좌번호"] == acct]
        if acct_df.empty:
            print(f"{acct:<22} [CSV에 데이터 없음]")
            continue

        cost, stock_val, unknown = compute_stock_value(acct_df, prices, fx)
        cash_usd, cash_krw = compute_cash_snapshot(acct_df, date_str, fx)

        our_total = stock_val + cash_usd * fx + cash_krw

        app_eval   = app.get("평가금액", 0)
        app_dep_krw = app.get("예수금(원화)", 0)
        app_dep_usd = app.get("예수금(달러)", 0)
        app_total  = app_eval + app_dep_krw + app_dep_usd * fx
        app_cost   = app.get("매입금액", 0)

        # 주식 vs 앱 평가금액 비교 (NH나무/메리츠: 주식only; 토스: USD 포함)
        se = (stock_val - app_eval) / app_eval * 100 if app_eval else 0
        te = (our_total - app_total) / app_total * 100 if app_total else 0
        ok_t = abs(te) <= TOTAL_TOLERANCE_PCT
        if not ok_t:
            all_ok = False

        note_s = "✅" if abs(se) <= TOTAL_TOLERANCE_PCT else "⚠️"
        note_t = "✅" if ok_t else "⚠️"
        status = "✅" if ok_t else "⚠️"

        print(f"{acct:<22} {stock_val:>12,.0f} {app_eval:>12,.0f} {note_s}{se:>+7.2f}%  "
              f"{our_total:>12,.0f} {app_total:>12,.0f} {note_t}{te:>+8.2f}%  {status}", end="")
        if unknown:
            print(f"  (가격없음: {[t for t, _ in unknown]})", end="")
        print()

        results[acct] = {
            "cash_usd": cash_usd, "cash_krw": cash_krw,
            "app_dep_usd": app_dep_usd, "app_dep_krw": app_dep_krw,
        }

    print()
    print("※ 주식오차: NH나무/메리츠는 주식평가 vs 평가금액, 토스는 달러포지션 포함 비교")
    print("※ 총자산오차: (주식+계산현금) vs (평가금액+예수금) — 현금 스냅샷 정확도에 따라 달라짐")
    print()

    # ── 예수금 대조표 ────────────────────────────────────────────────
    print(f"{'계좌':<22} {'원화현금(계산)':>14} {'원화현금(앱)':>14} {'상태':>4}  "
          f"{'달러현금(계산)':>14} {'달러현금(앱)':>14} {'상태':>4}  비고")
    print("-" * 104)

    cash_all_ok = True
    for acct, r in results.items():
        dep_krw = r["app_dep_krw"]
        dep_usd = r["app_dep_usd"]
        our_krw = r["cash_krw"]
        our_usd = r["cash_usd"]

        ok_krw = abs(our_krw - dep_krw) <= CASH_TOLERANCE_KRW
        ok_usd = abs(our_usd - dep_usd) <= CASH_TOLERANCE_USD
        note_krw = "✅" if ok_krw else "⚠️"
        note_usd = "✅" if ok_usd else "⚠️"
        if not ok_usd or not ok_krw:
            cash_all_ok = False

        # 비고: 왜 다를 수 있는지
        note_parts = []
        if not ok_usd:
            if dep_usd == 0 and our_usd > CASH_TOLERANCE_USD:
                note_parts.append("달러포지션 평가금액 포함됨")
            elif dep_usd > 0 and our_usd == 0:
                note_parts.append("USD 잔고 미추적 (파일 구조 한계)")
            elif dep_usd > our_usd:
                note_parts.append(f"파일 종료일 이후 배당·이자 +${dep_usd - our_usd:.2f} 미반영")
        if not ok_krw:
            if dep_krw > 0 and our_krw == 0:
                note_parts.append(f"원화 섹션 미파싱 (+₩{dep_krw:,.0f})")

        print(f"{acct:<22} {our_krw:>14,.0f} {dep_krw:>14,.0f} {note_krw:>4}  "
              f"{our_usd:>14.2f}$ {dep_usd:>13.2f}$ {note_usd:>4}  "
              f"{'  '.join(note_parts)}")

    print()
    print(f"※ 원화현금 허용 오차 ±₩{CASH_TOLERANCE_KRW:,} / 달러현금 허용 오차 ±${CASH_TOLERANCE_USD}")
    print()

    # ── 최종 결론 ─────────────────────────────────────────────────
    if all_ok:
        print("✅ 총자산 오차 모두 허용 범위 내 — 정상")
    else:
        print("⚠️  총자산 오차 초과 계좌 있음 — 현재가·환율·파일 범위 확인 필요")

    if not cash_all_ok:
        print("ℹ️  현금 불일치: NH나무 종합파일에 외화 잔고 없음, 또는 파일 종료일 이후 배당·이자 미반영")


if __name__ == "__main__":
    main()
