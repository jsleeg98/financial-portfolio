#!/usr/bin/env python3
"""메리츠증권 거래내역 .xls 파서

메리츠증권에서 다운로드한 종합거래내역 .xls 파일을 읽어 종합거래내역 CSV로 변환한다.

사용법:
    python parse_meritz.py <파일 또는 폴더 경로>
    python parse_meritz.py --organize <계좌 폴더 경로>

예시:
    python parse_meritz.py resource/
    python parse_meritz.py resource/메리츠증권/3066-6156-01/2026/
    python parse_meritz.py --organize resource/메리츠증권/  # 미정리 파일 연도별 정리
"""

import os
import sys
import glob
import re
from pathlib import Path

import pandas as pd
import xlrd

# ── 상수 ─────────────────────────────────────────────────────────────
BROKER = "메리츠증권"

OUTPUT_COLUMNS = [
    "거래일자", "유형", "종목코드", "수량", "단가",
    "금액", "환율", "금액KRW", "통화", "증권사", "계좌번호", "비고",
]

DEDUP_KEYS = [
    "거래일자", "유형", "종목코드", "수량", "단가", "금액", "통화", "증권사", "계좌번호"
]

# ── 종목코드 → 티커 매핑 ─────────────────────────────────────────────
# 메리츠증권은 종목코드에 거래소 suffix 사용 (IREN.OQ, SGOV.AX, SGOV.NY 등)
# suffix 제거 후 아래 딕셔너리로 조회. 없으면 코드 그대로 사용.
CODE_TO_TICKER = {
    "IREN": "IREN",     # IronNet / IREN Limited
    "SGOV": "SGOV",     # iShares 0-3M Treasury Bond ETF
    "CRCL": "CRCL",     # Circle Internet Group
    "INFQ": "INFQ",     # Inflection
}

# ── 거래적요 → 유형 매핑 ─────────────────────────────────────────────
# 주의: 해외주식매수/매도는 금액=0 이므로 제외하고 매수대금/매도대금을 사용한다.
TYPE_MAP = {
    "해외주식매수대금": "매수",
    "해외주식매도대금": "매도",
    "배당금": "배당",
    "종목교체입고": "입고",
    "종목교체출고": "출고",
}

# ── 파일명 패턴 ──────────────────────────────────────────────────────
# 정규화된 파일명: 메리츠증권_{계좌번호}_{YYMMDD-YYMMDD}_종합.xls
NORMALIZED_PATTERN = re.compile(
    r"^메리츠증권_([^_]+)_(\d{6})-(\d{6})(?:_종합)?\.xls$",
    re.IGNORECASE,
)

# 정리 대상 (연도 폴더 미분류 파일): 계좌번호 폴더 바로 아래 위치한 정규화 파일
ORGANIZE_PATTERN = re.compile(
    r"^메리츠증권_[^_]+_\d{6}-\d{6}(?:_종합)?\.xls$",
    re.IGNORECASE,
)


# ── 헬퍼 ─────────────────────────────────────────────────────────────

def strip_exchange_suffix(code: str) -> str:
    """거래소 suffix 제거: SGOV.AX → SGOV, IREN.OQ → IREN"""
    return re.sub(r"\.[A-Z]{2,3}$", "", code.strip())


def resolve_ticker(code: str) -> str:
    """종목코드를 티커로 변환. 매핑 없으면 suffix 제거한 코드 그대로 반환."""
    if not code:
        return ""
    base = strip_exchange_suffix(code)
    return CODE_TO_TICKER.get(base, base)


def parse_float(value) -> float:
    """쉼표가 포함된 숫자 문자열 또는 float → float 변환."""
    if value is None or value == "":
        return 0.0
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def parse_date(value: str) -> str:
    """날짜 문자열 정규화: '2026/01/27' → '2026-01-27'"""
    return str(value).strip().replace("/", "-")


def extract_account(filepath: str) -> str:
    """파일명에서 계좌번호 추출: 메리츠증권_3066-6156-01_... → '3066-6156-01'"""
    name = Path(filepath).stem
    m = NORMALIZED_PATTERN.match(Path(filepath).name)
    if m:
        return m.group(1)
    # fallback: _ 구분자 두 번째 토큰
    parts = name.split("_")
    return parts[1] if len(parts) >= 2 else ""


# ── 파싱 ─────────────────────────────────────────────────────────────

def parse_meritz_file(filepath: str) -> list[dict]:
    """메리츠증권 종합거래내역 .xls 파일을 파싱하여 레코드 목록을 반환한다.

    파일 구조:
      - 행 0: 주 헤더 (거래일자, 종목코드, 수량, ..., 통화구분)
      - 행 1: 보조 헤더 (거래적요, 종목명, 단가, ..., 외화예수금잔고)
      - 행 2+: 데이터 (짝수 인덱스=주 데이터, 홀수 인덱스=상세 데이터)

    열 인덱스 (0-based):
      주 데이터:  [0] 거래일자  [1] 종목코드  [2] 수량  [5] 거래금액  [14] 통화구분
      상세 데이터: [0] 거래적요  [1] 종목명    [2] 단가  [5] 반영금액
    """
    account = extract_account(filepath)
    print(f"파싱: {Path(filepath).name}  (증권사: {BROKER}, 계좌: {account})")

    try:
        wb = xlrd.open_workbook(filepath, encoding_override="euc-kr")
    except Exception as e:
        print(f"  [ERROR] 파일 열기 실패: {e}")
        return []

    ws = wb.sheet_by_index(0)
    if ws.nrows < 3:
        print(f"  [WARN] 데이터 없음 (행수={ws.nrows})")
        return []

    records = []
    skipped = 0

    # 현금잔고 추적: main_row[10]=예수금잔고(KRW), detail_row[14]=외화예수금잔고(USD)
    last_usd_cash = 0.0
    last_krw_cash = 0.0
    last_date = ""

    # 헤더 2행 건너뛰고 2행씩 쌍으로 처리
    i = 2
    while i + 1 < ws.nrows:
        main_row = ws.row_values(i)
        detail_row = ws.row_values(i + 1)
        i += 2

        # 모든 행에서 잔고 추적 (TYPE_MAP 필터 전)
        krw_cash = parse_float(main_row[10]) if len(main_row) > 10 else 0.0
        usd_cash = parse_float(detail_row[14]) if len(detail_row) > 14 else 0.0
        row_date = parse_date(str(main_row[0]))
        if krw_cash > 0:
            last_krw_cash = krw_cash
            last_date = row_date
        if usd_cash > 0:
            last_usd_cash = usd_cash
            last_date = row_date

        trade_type_raw = str(detail_row[0]).strip()
        mapped_type = TYPE_MAP.get(trade_type_raw)
        if not mapped_type:
            skipped += 1
            continue

        date_str = parse_date(str(main_row[0]))
        stock_code_raw = str(main_row[1]).strip()
        stock_name = str(detail_row[1]).strip()
        qty = parse_float(main_row[2])
        unit_price = parse_float(detail_row[2])
        amount = parse_float(main_row[5])  # 거래금액 (상세의 반영금액과 동일)
        currency_raw = str(main_row[14]).strip()
        currency = "USD" if currency_raw == "USD" else "KRW"

        # 배당금: 거래금액이 비어 있으면 반영금액 사용
        if amount == 0.0 and mapped_type == "배당":
            amount = parse_float(detail_row[5])

        ticker = resolve_ticker(stock_code_raw) if stock_code_raw else ""

        records.append({
            "거래일자": date_str,
            "유형": mapped_type,
            "종목코드": ticker,
            "수량": qty,
            "단가": unit_price,
            "금액": amount,
            "환율": 0.0,    # 파일에 환율 정보 없음 — 대시보드 currentFX 사용
            "금액KRW": 0.0,
            "통화": currency,
            "증권사": BROKER,
            "계좌번호": account,
            "비고": stock_name,
        })

    # 현금잔고 행 추가
    if last_usd_cash > 0:
        records.append({
            "거래일자": last_date,
            "유형": "현금잔고",
            "종목코드": "",
            "수량": 0.0,
            "단가": 0.0,
            "금액": last_usd_cash,
            "환율": 0.0,
            "금액KRW": 0.0,
            "통화": "USD",
            "증권사": BROKER,
            "계좌번호": account,
            "비고": "현금잔고",
        })
    if last_krw_cash > 0:
        records.append({
            "거래일자": last_date,
            "유형": "현금잔고",
            "종목코드": "",
            "수량": 0.0,
            "단가": 0.0,
            "금액": 0.0,
            "환율": 0.0,
            "금액KRW": last_krw_cash,
            "통화": "KRW",
            "증권사": BROKER,
            "계좌번호": account,
            "비고": "현금잔고",
        })

    print(f"  → {len([r for r in records if r['유형'] != '현금잔고'])}건 추출 (제외: {skipped}건)")
    return records


# ── 파일 정리 ─────────────────────────────────────────────────────────

def extract_year_from_filename(filename: str) -> str | None:
    """파일명 날짜 부분에서 연도 추출: 메리츠증권_..._260101-... → '2026'"""
    m = NORMALIZED_PATTERN.match(filename)
    if not m:
        return None
    date_start = m.group(2)  # YYMMDD
    yy = int(date_start[:2])
    year = str(2000 + yy)
    return year


def organize_folder(folder: str) -> int:
    """폴더 내 정규화된 파일을 계좌번호/연도 서브폴더로 이동한다.

    resource/메리츠증권/파일.xls
      → resource/메리츠증권/3066-6156-01/2026/파일.xls
    """
    folder_path = Path(folder)
    moved = 0
    for xls in sorted(folder_path.rglob("*.xls")):
        # 이미 계좌번호/연도 구조 안에 있으면 스킵
        if len(xls.relative_to(folder_path).parts) >= 3:
            continue
        if not ORGANIZE_PATTERN.match(xls.name):
            continue
        m = NORMALIZED_PATTERN.match(xls.name)
        if not m:
            continue
        account = m.group(1)
        year = extract_year_from_filename(xls.name)
        if not year:
            continue
        target_dir = folder_path / account / year
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / xls.name
        if target.exists():
            print(f"  [SKIP] 이미 존재: {target}")
            continue
        xls.rename(target)
        print(f"  {xls.name} → {account}/{year}/{xls.name}")
        moved += 1
    return moved


# ── 파일 스캔 ────────────────────────────────────────────────────────

def scan_files(path: str) -> list[str]:
    """경로에서 메리츠증권 .xls 파일 목록을 반환한다."""
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


# ── 메인 ─────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("사용법: python parse_meritz.py [--organize] <파일 또는 폴더 경로>")
        print("예시:")
        print("  python parse_meritz.py resource/")
        print("  python parse_meritz.py resource/메리츠증권/3066-6156-01/2026/")
        print("  python parse_meritz.py --organize resource/메리츠증권/")
        sys.exit(1)

    args = sys.argv[1:]

    # --organize: 연도별 폴더 정리
    if args[0] == "--organize":
        if len(args) < 2:
            print("[ERROR] --organize 옵션에는 폴더 경로가 필요합니다.")
            sys.exit(1)
        folder = args[1]
        if not Path(folder).is_dir():
            print(f"[ERROR] 폴더를 찾을 수 없습니다: {folder}")
            sys.exit(1)
        print(f"\n=== 파일 정리: {folder} ===\n")
        moved = organize_folder(folder)
        print(f"\n정리 완료: {moved}개 파일 이동")
        sys.exit(0)

    input_path = args[0]
    files = scan_files(input_path)
    if not files:
        print("처리할 .xls 파일이 없습니다.")
        sys.exit(1)

    print(f"\n=== 메리츠증권 거래내역 파서 ===")
    print(f"대상: {len(files)}개 파일\n")

    all_records = []
    for f in files:
        records = parse_meritz_file(f)
        all_records.extend(records)

    if not all_records:
        print("\n추출된 거래가 없습니다.")
        sys.exit(0)

    df = pd.DataFrame(all_records, columns=OUTPUT_COLUMNS)

    # 기존 CSV와 병합
    output_dir = Path.cwd() / "output"
    output_path = output_dir / "종합거래내역.csv"

    if output_path.exists():
        print(f"\n기존 파일 병합: {output_path}")
        existing = pd.read_csv(output_path, dtype=str).fillna("")

        # 이번 파싱 결과에 현금잔고 행이 있으면 기존 CSV의 해당 계좌 현금잔고 행 제거
        # (재실행 시 잔고 변경을 올바르게 반영)
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
            removed_cash = mask_to_remove.sum()
            if removed_cash:
                print(f"  기존 현금잔고 행 교체: {removed_cash}건 제거")
            existing = existing[~mask_to_remove]

        df = pd.concat([existing, df], ignore_index=True)

    # 숫자 컬럼 타입 보정
    for col in ["수량", "단가", "금액", "환율", "금액KRW"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # 문자열 컬럼 NaN → 빈 문자열
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
    print(f"파일: {len(files)}개 처리")
    print(f"거래: {len(df)}건")
    print(f"출력: {output_path}")

    if len(df) > 0:
        print(f"\n통화별 건수:")
        for c, cnt in df["통화"].value_counts().items():
            print(f"  {c}: {cnt}건")
        print(f"\n유형별 건수:")
        for t, cnt in df["유형"].value_counts().items():
            print(f"  {t}: {cnt}건")
        print(f"\n종목별 건수:")
        stock_counts = df[df["종목코드"] != ""]["종목코드"].value_counts()
        for s, cnt in stock_counts.items():
            print(f"  {s}: {cnt}건")


if __name__ == "__main__":
    main()
