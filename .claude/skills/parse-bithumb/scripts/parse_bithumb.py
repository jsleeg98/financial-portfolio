#!/usr/bin/env python3
"""빗썸 거래내역 .xlsx 파서

빗썸에서 다운로드한 기간별 거래내역 .xlsx 파일을 읽어 종합거래내역 CSV로 변환한다.

사용법:
    python parse_bithumb.py <파일 또는 폴더 경로>

예시:
    python parse_bithumb.py resource/빗썸/
    python parse_bithumb.py resource/빗썸/빗썸_250401-250630_종합.xlsx
"""

import os
import sys
import glob
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

# ── 상수 ─────────────────────────────────────────────────────────────
BROKER = "빗썸"
ACCOUNT = "빗썸"

OUTPUT_CSV = "output/종합거래내역.csv"

OUTPUT_COLUMNS = [
    "거래일자", "유형", "종목코드", "수량", "단가",
    "금액", "환율", "금액KRW", "통화", "증권사", "계좌번호", "비고",
]

# 비고에 시간(HH:MM:SS)을 포함하므로 날짜+시간이 곧 유일 키
# 같은 날·같은 수량·같은 종목을 서로 다른 거래로 올바르게 구분한다
DEDUP_KEYS = [
    "거래일자", "유형", "종목코드", "수량", "단가",
    "금액", "통화", "증권사", "계좌번호", "비고",
]

# 무료 수령 거래 유형 → 매수(수량=qty, 단가=0, 금액=0)로 기록
# portfolio.js에서 qty 추적이 가능하도록 매수로 변환
FREE_RECEIVE_TYPES = {
    "가상자산 이벤트 입금",
    "스테이킹(자유형)",
    "이벤트 혜택 지급",
    "이벤트쿠폰입금",
    "친구초대 추천 리워드",
    "포인트샵 입금",
    "외부입금",
}

# 완전히 무시하는 거래 유형 (원화 입출금, KRW 이자 등 포트폴리오 무관)
# ※ 외부출금은 비KRW 자산이면 매도로 처리하므로 여기서 제외
SKIP_TYPES = {
    "예치금 이용료",
    "입금",
    "출금",
}

# KRW 현금 자산 (가상자산 포트폴리오에 불포함)
KRW_ASSETS = {"원화"}

# 추적할 티커 목록 (빈 set이면 전체 추적)
# 특정 종목만 대시보드에 표시하고 싶을 때 여기에 추가
TRACK_ONLY = {"BTC", "ETH"}


# ── 파싱 헬퍼 ─────────────────────────────────────────────────────────

def parse_qty_ticker(qty_str: str) -> tuple:
    """'5.17119965 BMT' → (5.17119965, 'BMT')"""
    if not qty_str:
        return 0.0, ""
    parts = str(qty_str).strip().split()
    if len(parts) == 2:
        try:
            qty = float(parts[0].replace(",", ""))
            return qty, parts[1]
        except ValueError:
            return 0.0, parts[1]
    return 0.0, ""


def parse_price(price_str: str) -> float:
    """'187.0000 KRW' or '-' → 187.0 or 0.0. 비KRW 단위이면 0.0 반환."""
    if not price_str:
        return 0.0
    s = str(price_str).strip()
    if s in ("-", ""):
        return 0.0
    parts = s.split()
    # 단위가 KRW 이외(BTC 등)이면 KRW 환산 불가 → 0
    if len(parts) == 2 and parts[1] not in ("KRW", ""):
        return 0.0
    try:
        return float(parts[0].replace(",", ""))
    except ValueError:
        return 0.0


def parse_amount(amount_str: str) -> float:
    """'967 KRW' or '- KRW' or '-' → 967.0 or 0.0 (항상 양수). 비KRW 이면 0.0."""
    if not amount_str:
        return 0.0
    s = str(amount_str).strip()
    if s in ("-", "- KRW", ""):
        return 0.0
    parts = s.split()
    # 단위가 KRW 이외(BTC 등)이면 KRW 환산 불가 → 0
    if len(parts) == 2 and parts[1] not in ("KRW", ""):
        return 0.0
    try:
        return abs(float(parts[0].replace(",", "")))
    except ValueError:
        return 0.0


def parse_crypto_amount(amount_str: str) -> tuple:
    """'0.00187200 BTC' → (0.001872, 'BTC'). KRW이거나 '-'이면 (0.0, '')."""
    if not amount_str:
        return 0.0, ""
    s = str(amount_str).strip()
    if s in ("-", "- KRW", "- BTC", "- ETH", ""):
        return 0.0, ""
    parts = s.split()
    if len(parts) == 2 and parts[1] not in ("KRW",):
        try:
            return abs(float(parts[0].replace(",", "").lstrip("+-"))), parts[1]
        except ValueError:
            return 0.0, ""
    return 0.0, ""


# ── 파일 파싱 ─────────────────────────────────────────────────────────

def parse_file(filepath: str) -> list:
    """xlsx 파일 하나를 파싱해 레코드 리스트로 반환."""
    try:
        import openpyxl  # noqa
    except ImportError:
        print("openpyxl이 필요합니다: pip install openpyxl")
        sys.exit(1)

    import openpyxl as xl
    wb = xl.load_workbook(filepath)
    ws = wb["거래내역"]

    records = []
    for row in ws.iter_rows(min_row=4, values_only=True):
        if row[0] is None:
            continue

        거래일시  = str(row[0]).strip() if row[0] else ""
        자산      = str(row[1]).strip() if row[1] else ""
        거래구분  = str(row[2]).strip() if row[2] else ""
        qty_str   = str(row[3]).strip() if row[3] else ""
        price_str = str(row[4]).strip() if row[4] else ""
        amt_str   = str(row[5]).strip() if row[5] else ""

        # 날짜 (YYYY-MM-DD) / 시간 (HH:MM:SS)
        거래일자 = 거래일시[:10] if len(거래일시) >= 10 else 거래일시
        거래시간 = 거래일시[11:19] if len(거래일시) >= 19 else ""

        # 원화 자산 또는 무시 유형 → skip
        if 자산 in KRW_ASSETS or 거래구분 in SKIP_TYPES:
            continue

        # 수량 및 종목 티커
        qty, ticker = parse_qty_ticker(qty_str)

        # 외부출금: 비KRW 자산이면 매도로 기록 (잔고 차감), KRW이면 무시
        if 거래구분 == "외부출금":
            if not ticker or ticker == "KRW":
                continue
            records.append({
                "거래일자": 거래일자,
                "유형":     "매도",
                "종목코드": ticker,
                "수량":     qty,
                "단가":     0.0,
                "금액":     0.0,
                "환율":     0.0,
                "금액KRW":  0.0,
                "통화":     "KRW",
                "증권사":   BROKER,
                "계좌번호": ACCOUNT,
                "비고":     f"외부출금 {거래시간}",
            })
            continue
        if not ticker or ticker == "KRW":
            continue

        # 거래 유형 결정
        if 거래구분 == "매수":
            유형 = "매수"
        elif 거래구분 == "매도":
            유형 = "매도"
        elif 거래구분 in FREE_RECEIVE_TYPES:
            유형 = "매수"
        else:
            continue  # 알 수 없는 유형 무시

        # ── 크립토→크립토 스왑 감지 ──────────────────────────────────
        # 거래금액 단위가 BTC/ETH 등인 경우: 현물 코인으로 결제한 것
        # 예: ETH 매수 시 거래금액 = '0.00187200 BTC'
        swap_qty, swap_currency = parse_crypto_amount(amt_str)
        is_crypto_swap = (
            유형 == "매수"
            and swap_qty > 0
            and swap_currency
            and swap_currency != ticker  # 결제 수단이 구매 대상과 다름
        )

        # 비고: 거래 시간 포함 (같은 날 동일 거래 중복 제거 방지)
        if 거래구분 not in ("매수", "매도"):
            비고 = f"{거래구분} {거래시간}".strip()
        else:
            비고 = 거래시간  # HH:MM:SS

        # KRW 가격/금액 (크립토 스왑이거나 무료 수령이면 0)
        if 거래구분 in FREE_RECEIVE_TYPES or is_crypto_swap:
            단가 = 0.0
            금액 = 0.0
        else:
            단가 = parse_price(price_str)
            금액 = parse_amount(amt_str)

        records.append({
            "거래일자": 거래일자,
            "유형":     유형,
            "종목코드": ticker,
            "수량":     qty,
            "단가":     단가,
            "금액":     금액,
            "환율":     0.0,
            "금액KRW":  금액,
            "통화":     "KRW",
            "증권사":   BROKER,
            "계좌번호": ACCOUNT,
            "비고":     비고,
        })

        # ── 크립토 스왑 시 결제 코인의 매도 기록 추가 ─────────────────
        # 예: BTC로 ETH 구매 → BTC 매도 기록 없으면 BTC 잔고 초과
        if is_crypto_swap:
            records.append({
                "거래일자": 거래일자,
                "유형":     "매도",
                "종목코드": swap_currency,
                "수량":     swap_qty,
                "단가":     0.0,
                "금액":     0.0,
                "환율":     0.0,
                "금액KRW":  0.0,
                "통화":     "KRW",
                "증권사":   BROKER,
                "계좌번호": ACCOUNT,
                "비고":     f"{swap_currency}→{ticker} {거래시간}",
            })

    return records


# ── 파일 탐색 ─────────────────────────────────────────────────────────

def find_xlsx_files(path: str) -> list:
    """폴더 또는 단일 파일 경로를 받아 .xlsx 파일 목록을 반환 (날짜순)."""
    p = Path(path)
    if p.is_file():
        return [str(p)] if p.suffix.lower() == ".xlsx" else []
    files = sorted(glob.glob(str(p / "**" / "빗썸_*.xlsx"), recursive=True))
    if not files:
        files = sorted(glob.glob(str(p / "**" / "*.xlsx"), recursive=True))
    return files


# ── 메인 ─────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(f"사용법: python {Path(__file__).name} <파일 또는 폴더 경로>")
        sys.exit(1)

    path = sys.argv[1]
    files = find_xlsx_files(path)
    if not files:
        print(f"[빗썸] xlsx 파일을 찾을 수 없습니다: {path}")
        sys.exit(1)

    all_records = []
    for f in sorted(files):
        try:
            recs = parse_file(f)
            print(f"  [빗썸] {Path(f).name}: {len(recs)}건 파싱")
            all_records.extend(recs)
        except Exception as e:
            print(f"  [빗썸] {Path(f).name} 파싱 오류: {e}")
            raise

    if not all_records:
        print("[빗썸] 파싱된 거래 없음")
        return

    # ── 잔고 0인 종목 제거 ────────────────────────────────────────────
    # portfolio.js의 당일 처리 순서(getDayOrder)는 동일 날짜 내 매도→매수 순서를
    # 초기 잔고 기준으로 결정하므로, 잔고=0인 종목은 phantom 잔고를 만들 수 있다.
    # 또한 기초잔고(데이터 시작 이전 보유분)가 없으면 초기 매도가 무시되어
    # 이후 매수가 그대로 누적되는 문제도 발생한다.
    # 가장 안정적인 해결책: 최종 순잔고 > 0인 종목만 CSV에 포함한다.
    from collections import defaultdict
    ticker_net: dict = defaultdict(float)
    for rec in all_records:
        if rec["유형"] == "매수":
            ticker_net[rec["종목코드"]] += rec["수량"]
        elif rec["유형"] == "매도":
            ticker_net[rec["종목코드"]] -= rec["수량"]

    MIN_BALANCE = 1e-5
    keep_tickers = {t for t, net in ticker_net.items() if net > MIN_BALANCE}
    if TRACK_ONLY:
        keep_tickers &= TRACK_ONLY
    excluded_tickers = sorted(set(ticker_net.keys()) - keep_tickers)
    for t in excluded_tickers:
        print(f"  [빗썸] {t} 잔고=0 제외 (net={ticker_net[t]:.8f})")

    all_records = [r for r in all_records if r["종목코드"] in keep_tickers]

    if not all_records:
        print("[빗썸] 잔고 있는 종목 없음")
        return

    new_df = pd.DataFrame(all_records, columns=OUTPUT_COLUMNS)
    new_df = new_df.sort_values("거래일자").reset_index(drop=True)

    # 기존 CSV와 병합 또는 신규 생성
    output_path = OUTPUT_CSV
    if os.path.exists(output_path):
        existing_df = pd.read_csv(output_path, encoding="utf-8-sig", dtype=str)
        for col in ["수량", "단가", "금액", "환율", "금액KRW"]:
            if col in new_df.columns:
                new_df[col] = pd.to_numeric(new_df[col], errors="coerce").fillna(0.0)
            if col in existing_df.columns:
                existing_df[col] = pd.to_numeric(existing_df[col], errors="coerce").fillna(0.0)
        merged = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        os.makedirs("output", exist_ok=True)
        merged = new_df

    # 중복 제거 (DEDUP_KEYS에 비고(시간 포함)가 있어 오탐 없음)
    before = len(merged)
    merged = merged.sort_values("거래일자").reset_index(drop=True)
    merged = merged.drop_duplicates(subset=DEDUP_KEYS, keep="first")
    after = len(merged)
    if before != after:
        print(f"  [빗썸] 중복 제거: {before - after}건")

    merged.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"[빗썸] 저장 완료: {output_path} ({after}건 총합)")

    if "증권사" in merged.columns:
        summary = merged.groupby(["증권사", "계좌번호"]).size()
        for (broker, acct), cnt in summary.items():
            print(f"  {broker} / {acct}: {cnt}건")


if __name__ == "__main__":
    main()
