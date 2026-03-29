#!/usr/bin/env python3
"""키움증권 거래내역 .xls 파서

종합거래내역 .xls 파일을 읽어 종합거래내역 CSV로 변환한다.

사용법:
    python parse_kiwoom.py <파일 또는 폴더 경로>

예시:
    python parse_kiwoom.py resource/키움증권/
    python parse_kiwoom.py resource/키움증권/6265-5774/
    python parse_kiwoom.py resource/키움증권/6265-5774/키움증권_6265-5774_250101-251231_종합.xls
"""

import os
import sys
import glob
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

# ── 출력 컬럼 ────────────────────────────────────────────────────────
OUTPUT_COLUMNS = [
    "거래일자", "유형", "종목코드", "수량", "단가",
    "금액", "환율", "금액KRW", "통화", "증권사", "계좌번호", "비고",
]

DEDUP_KEYS = ["거래일자", "유형", "종목코드", "수량", "단가", "금액", "통화", "증권사", "계좌번호"]

# ── 거래구분 → 유형 매핑 ─────────────────────────────────────────────
# 포함할 거래구분만 정의. 나머지는 자동으로 제외된다.
TRADE_TYPE_MAP = {
    "장내매수": "매수",
    "장내매도": "매도",
    "KOSDAQ매수": "매수",
    "KOSDAQ매도": "매도",
    "배당금입금": "배당",
    "수익분배금입금": "배당",
}


def parse_filename(filepath: str) -> tuple[str, str]:
    """파일명에서 증권사명과 계좌번호를 추출한다.

    예: 키움증권_6265-5774_240101-241231_종합.xls → ('키움증권', '6265-5774')
    """
    stem = Path(filepath).stem
    parts = stem.split("_")
    broker = parts[0] if len(parts) >= 1 else "unknown"
    account = parts[1] if len(parts) >= 2 else "unknown"
    return broker, account


def parse_number(text: str) -> float:
    """숫자 문자열을 float으로 변환한다. 콤마 제거, 빈 값은 0."""
    s = text.strip().replace(",", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_kiwoom_file(filepath: str) -> list[dict]:
    """키움증권 종합거래내역 .xls 파일을 파싱하여 거래 레코드 리스트를 반환한다.

    파일 형식: UTF-8 인코딩된 HTML 테이블, 22개 컬럼, 단일 행 구조
    컬럼: [0]거래일자 [1]종목명 [2]거래수량 [3]거래금액 [7]예수금
           [11]거래소 [12]거래구분 [13]거래단가
    """
    broker, account = parse_filename(filepath)
    print(f"  파싱: {Path(filepath).name} (증권사: {broker}, 계좌: {account})")

    with open(filepath, "rb") as f:
        raw = f.read()

    soup = BeautifulSoup(raw, "html.parser", from_encoding="utf-8")
    table = soup.find("table")
    if not table:
        print(f"  [ERROR] <table> 없음: {filepath}")
        return []

    rows = table.find_all("tr")
    if len(rows) < 3:
        print(f"  [ERROR] 데이터 행 없음: {filepath}")
        return []

    records = []
    last_cash_krw = 0.0
    last_date = ""

    # rows[0]: 제목행 ("[키움증권]주식 거래내역")
    # rows[1]: 헤더행
    # rows[2:]: 데이터행
    for row in rows[2:]:
        tds = row.find_all(["td", "th"])
        if len(tds) < 14:
            continue

        trade_date_raw = tds[0].get_text(strip=True)
        stock_name = tds[1].get_text(strip=True)
        quantity_raw = tds[2].get_text(strip=True)
        amount_raw = tds[3].get_text(strip=True)
        cash_raw = tds[7].get_text(strip=True)
        trade_type_raw = tds[12].get_text(strip=True)
        unit_price_raw = tds[13].get_text(strip=True)

        # 날짜 형식 변환: YYYY.MM.DD → YYYY-MM-DD
        trade_date = trade_date_raw.replace(".", "-")
        if trade_date:
            last_date = trade_date

        # 예수금(현금잔고) 추적
        cash = parse_number(cash_raw)
        if cash > 0:
            last_cash_krw = cash

        # 포함 여부 판별
        output_type = TRADE_TYPE_MAP.get(trade_type_raw)
        if output_type is None:
            continue

        # 배당 거래는 종목명이 있어야 유효
        if not stock_name:
            continue

        quantity = parse_number(quantity_raw)
        unit_price = parse_number(unit_price_raw)
        amount = parse_number(amount_raw)

        # 배당: 수량·단가는 0으로 처리
        if output_type == "배당":
            quantity = 0.0
            unit_price = 0.0

        records.append({
            "거래일자": trade_date,
            "유형": output_type,
            "종목코드": stock_name,
            "수량": quantity,
            "단가": unit_price,
            "금액": amount,
            "환율": 0.0,
            "금액KRW": amount,
            "통화": "KRW",
            "증권사": broker,
            "계좌번호": account,
            "비고": "",
        })

    # 현금잔고 행 추가: 마지막 예수금을 스냅샷으로 기록
    if last_date:
        records.append({
            "거래일자": last_date,
            "유형": "현금잔고",
            "종목코드": "",
            "수량": 0.0,
            "단가": 0.0,
            "금액": 0.0,
            "환율": 0.0,
            "금액KRW": last_cash_krw,
            "통화": "KRW",
            "증권사": broker,
            "계좌번호": account,
            "비고": "현금잔고",
        })

    trade_count = len(records) - (1 if last_date else 0)
    print(f"  → {trade_count}건 추출 (현금잔고: {last_cash_krw:,.0f}원)")
    return records


def scan_files(path: str) -> list[str]:
    """경로에서 키움증권 .xls 파일 목록을 반환한다."""
    p = Path(path)
    if p.is_file() and p.suffix.lower() == ".xls":
        return [str(p)]
    if p.is_dir():
        files = sorted(glob.glob(str(p / "**" / "*.xls"), recursive=True))
        return files
    print(f"[ERROR] 유효하지 않은 경로: {path}")
    return []


def sort_records(df: pd.DataFrame) -> pd.DataFrame:
    """날짜순 정렬. 같은 날은 원본 순서 유지 (stable sort)."""
    return df.sort_values("거래일자", kind="stable").reset_index(drop=True)


def main():
    if len(sys.argv) < 2:
        print("사용법: python parse_kiwoom.py <파일 또는 폴더 경로>")
        print("예시:")
        print("  python parse_kiwoom.py resource/키움증권/")
        print("  python parse_kiwoom.py resource/키움증권/6265-5774/")
        sys.exit(1)

    input_path = sys.argv[1]
    files = scan_files(input_path)

    # 키움증권 파일만 필터링
    kiwoom_files = [f for f in files if "키움증권" in Path(f).name or "키움증권" in str(Path(f).parent)]
    if not kiwoom_files:
        # 필터 없이 전체 파일 사용
        kiwoom_files = files

    if not kiwoom_files:
        print("처리할 .xls 파일이 없습니다.")
        sys.exit(1)

    print(f"\n=== 키움증권 거래내역 파서 ===")
    print(f"대상: {len(kiwoom_files)}개 파일\n")

    all_records = []
    for f in kiwoom_files:
        records = parse_kiwoom_file(f)
        all_records.extend(records)

    if not all_records:
        print("\n추출된 거래가 없습니다.")
        sys.exit(0)

    df = pd.DataFrame(all_records, columns=OUTPUT_COLUMNS)

    # 기존 CSV가 있으면 병합
    output_dir = Path.cwd() / "output"
    output_path = output_dir / "종합거래내역.csv"

    if output_path.exists():
        print(f"\n기존 파일 병합: {output_path}")
        existing = pd.read_csv(output_path, dtype=str).fillna("")

        # 새 파싱 결과의 현금잔고가 있으면 기존 CSV의 해당 계좌 현금잔고 제거 (최신 스냅샷으로 교체)
        new_cash_keys = set()
        for r in all_records:
            if r.get("유형") == "현금잔고":
                new_cash_keys.add((r["증권사"], r["계좌번호"], r["통화"]))
        if new_cash_keys:
            mask_to_remove = (
                (existing["유형"] == "현금잔고") &
                existing.apply(
                    lambda row: (row["증권사"], row["계좌번호"], row["통화"]) in new_cash_keys,
                    axis=1
                )
            )
            removed = mask_to_remove.sum()
            if removed:
                print(f"  기존 현금잔고 행 교체: {removed}건 제거")
            existing = existing[~mask_to_remove]

        df = pd.concat([existing, df], ignore_index=True)

    # 숫자 컬럼 타입 보정
    for col in ["수량", "단가", "금액", "환율", "금액KRW"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # 문자열 컬럼 NaN→빈 문자열 통일
    for col in ["종목코드", "통화", "비고"]:
        df[col] = df[col].fillna("")

    df = sort_records(df)

    # 중복 제거
    before = len(df)
    df = df.drop_duplicates(subset=DEDUP_KEYS, keep="last")
    removed = before - len(df)
    if removed > 0:
        print(f"\n중복 제거: {removed}건 제거 ({before} → {len(df)}건)")

    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")

    print(f"\n=== 완료 ===")
    print(f"파일: {len(kiwoom_files)}개 처리")
    print(f"거래: {len(df)}건")
    print(f"출력: {output_path}")

    if len(df) > 0:
        print(f"\n유형별 건수:")
        for t, cnt in df["유형"].value_counts().items():
            print(f"  {t}: {cnt}건")
        print(f"\n종목별 건수:")
        stock_counts = df[df["종목코드"] != ""]["종목코드"].value_counts()
        for s, cnt in stock_counts.head(20).items():
            print(f"  {s}: {cnt}건")


if __name__ == "__main__":
    main()
