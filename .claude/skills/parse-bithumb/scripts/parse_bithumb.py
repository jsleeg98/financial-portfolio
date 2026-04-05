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

DEDUP_KEYS = [
    "거래일자", "유형", "종목코드", "수량", "단가",
    "금액", "통화", "증권사", "계좌번호", "비고",
]

# 무료 수령 거래 유형 → 매수 with price=0, amount=0
# (qty 추적을 위해 매수로 기록, 비고에 원래 유형 보존)
FREE_RECEIVE_TYPES = {
    "가상자산 이벤트 입금",
    "스테이킹(자유형)",
    "이벤트 혜택 지급",
    "이벤트쿠폰입금",
    "친구초대 추천 리워드",
    "포인트샵 입금",
    "외부입금",
}

# 완전히 무시하는 거래 유형 (원화 입출금, KRW 이자 등)
SKIP_TYPES = {
    "예치금 이용료",
    "외부출금",
    "입금",
    "출금",
}

# 원화로 거래되는 자산 (KRW 거래이므로 가상자산 포트폴리오에 불포함)
KRW_ASSETS = {"원화"}


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
    """'187.0000 KRW' or '-' → 187.0 or 0.0"""
    if not price_str:
        return 0.0
    s = str(price_str).strip()
    if s in ("-", ""):
        return 0.0
    # Remove trailing unit (e.g. ' KRW')
    s = s.split()[0].replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_amount(amount_str: str) -> float:
    """'967 KRW' or '- KRW' or '-' → 967.0 or 0.0 (항상 양수)"""
    if not amount_str:
        return 0.0
    s = str(amount_str).strip()
    if s in ("-", "- KRW", ""):
        return 0.0
    # Remove unit, commas, sign
    token = s.split()[0].replace(",", "").lstrip("+-")
    try:
        return float(token)
    except ValueError:
        return 0.0


# ── 파일 파싱 ─────────────────────────────────────────────────────────

def parse_file(filepath: str) -> list:
    """xlsx 파일 하나를 파싱해 레코드 리스트로 반환."""
    try:
        import openpyxl
    except ImportError:
        print("openpyxl이 필요합니다: pip install openpyxl")
        sys.exit(1)

    import openpyxl as xl
    wb = xl.load_workbook(filepath)
    ws = wb["거래내역"]

    records = []
    for row in ws.iter_rows(min_row=4, values_only=True):
        # 빈 행 스킵
        if row[0] is None:
            continue

        거래일시 = str(row[0]).strip() if row[0] else ""
        자산     = str(row[1]).strip() if row[1] else ""
        거래구분 = str(row[2]).strip() if row[2] else ""
        qty_str  = str(row[3]).strip() if row[3] else ""
        price_str = str(row[4]).strip() if row[4] else ""
        amt_str  = str(row[5]).strip() if row[5] else ""
        fee_str  = str(row[6]).strip() if row[6] else ""

        # 날짜 추출 (YYYY-MM-DD)
        거래일자 = 거래일시[:10] if len(거래일시) >= 10 else 거래일시

        # 원화 자산 또는 완전 무시 유형 → skip
        if 자산 in KRW_ASSETS or 거래구분 in SKIP_TYPES:
            continue

        # 수량 및 티커 파싱
        qty, ticker = parse_qty_ticker(qty_str)
        if not ticker or ticker == "KRW":
            continue

        # 거래 유형 결정
        if 거래구분 == "매수":
            유형 = "매수"
        elif 거래구분 == "매도":
            유형 = "매도"
        elif 거래구분 in FREE_RECEIVE_TYPES:
            # 무료 수령 → 매수(수량=qty, 단가=0, 금액=0)로 기록
            유형 = "매수"
        else:
            # 미분류 거래 유형은 skip (안전하게)
            continue

        단가  = parse_price(price_str)
        금액  = parse_amount(amt_str)
        수수료 = parse_amount(fee_str)

        # 무료 수령의 경우 금액=0, 단가=0
        if 거래구분 in FREE_RECEIVE_TYPES:
            단가 = 0.0
            금액 = 0.0

        비고 = f"{거래구분}" if 거래구분 not in ("매수", "매도") else ""

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

    return records


# ── 파일 탐색 ─────────────────────────────────────────────────────────

def find_xlsx_files(path: str) -> list:
    """폴더 또는 단일 파일 경로를 받아 .xlsx 파일 목록을 반환 (날짜순)."""
    p = Path(path)
    if p.is_file():
        return [str(p)] if p.suffix.lower() == ".xlsx" else []
    # 폴더: 빗썸_*.xlsx 패턴 탐색
    files = sorted(glob.glob(str(p / "**" / "빗썸_*.xlsx"), recursive=True))
    if not files:
        # fallback: 모든 .xlsx
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

    new_df = pd.DataFrame(all_records, columns=OUTPUT_COLUMNS)
    new_df = new_df.sort_values("거래일자").reset_index(drop=True)

    # 기존 CSV와 병합 또는 신규 생성
    output_path = OUTPUT_CSV
    if os.path.exists(output_path):
        existing_df = pd.read_csv(output_path, encoding="utf-8-sig", dtype=str)
        # 숫자 컬럼 float 변환
        for col in ["수량", "단가", "금액", "환율", "금액KRW"]:
            if col in new_df.columns:
                new_df[col] = pd.to_numeric(new_df[col], errors="coerce").fillna(0.0)
            if col in existing_df.columns:
                existing_df[col] = pd.to_numeric(existing_df[col], errors="coerce").fillna(0.0)
        merged = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        os.makedirs("output", exist_ok=True)
        merged = new_df

    # 중복 제거
    before = len(merged)
    merged = merged.sort_values("거래일자").reset_index(drop=True)
    merged = merged.drop_duplicates(subset=DEDUP_KEYS, keep="first")
    after = len(merged)
    if before != after:
        print(f"  [빗썸] 중복 제거: {before - after}건")

    merged.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"[빗썸] 저장 완료: {output_path} ({after}건 총합)")

    # 증권사별 건수 요약
    if "증권사" in merged.columns:
        summary = merged.groupby(["증권사", "계좌번호"]).size()
        for (broker, acct), cnt in summary.items():
            print(f"  {broker} / {acct}: {cnt}건")


if __name__ == "__main__":
    main()
