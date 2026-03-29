#!/usr/bin/env python3
"""토스증권 거래내역서 PDF 파서

토스증권에서 발급한 거래내역서 PDF 파일을 읽어 종합거래내역 CSV로 변환한다.
PDF 파싱 시 중간 CSV를 PDF 옆에 저장하여 사람이 검토·편집하기 쉽게 한다.
이후 실행 시 CSV가 이미 있으면 PDF 파싱을 건너뛰고 CSV를 직접 읽는다.

사용법:
    python parse_toss.py <파일 또는 폴더 경로>
    python parse_toss.py --organize <계좌 폴더 경로>

예시:
    python parse_toss.py resource/
    python parse_toss.py resource/토스증권/159-01-510195/2026/
    python parse_toss.py --organize resource/토스증권/  # 미정리 파일 연도별 정리
"""

import glob
import re
import sys
from pathlib import Path

import pandas as pd

# ── 상수 ─────────────────────────────────────────────────────────────
BROKER = "토스증권"

OUTPUT_COLUMNS = [
    "거래일자", "유형", "종목코드", "수량", "단가",
    "금액", "환율", "금액KRW", "통화", "증권사", "계좌번호", "비고",
]

DEDUP_KEYS = [
    "거래일자", "유형", "종목코드", "수량", "단가", "금액", "통화", "증권사", "계좌번호"
]

# ── ISIN → 티커 매핑 ─────────────────────────────────────────────────
# 새 종목 거래 시 여기에 추가하라.
ISIN_TO_TICKER = {
    "US46436E7186": "SGOV",   # iShares 0-3M Treasury Bond ETF
    "AU0000185993": "IREN",   # IREN Limited (Australian)
}

# ── 거래구분 → 유형 매핑 ─────────────────────────────────────────────
# 매핑에 없는 항목(이체입금, 환전, 이자 등)은 모두 제외된다.
TYPE_MAP = {
    "구매": "매수",
    "판매": "매도",
    "외화증권배당금입금": "배당",
}

# ── 파일명 패턴 ──────────────────────────────────────────────────────
# 정규화된 파일명: 토스증권_{계좌번호}_{YYMMDD-YYMMDD}_종합.pdf
NORMALIZED_PATTERN = re.compile(
    r"^토스증권_([^_]+)_(\d{6})-(\d{6})_종합\.(pdf|csv)$",
    re.IGNORECASE,
)


# ── 헬퍼 ─────────────────────────────────────────────────────────────

def parse_float(s) -> float:
    if s is None or s == "":
        return 0.0
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def extract_account(filepath: str) -> str:
    """파일명에서 계좌번호 추출: 토스증권_159-01-510195_... → '159-01-510195'"""
    m = NORMALIZED_PATTERN.match(Path(filepath).name)
    if m:
        return m.group(1)
    parts = Path(filepath).stem.split("_")
    return parts[1] if len(parts) >= 2 else ""


def extract_year_from_filename(filename: str) -> str | None:
    """파일명 날짜 부분에서 연도 추출: 토스증권_..._260101-... → '2026'"""
    m = NORMALIZED_PATTERN.match(filename)
    if not m:
        return None
    yy = int(m.group(2)[:2])
    return str(2000 + yy)


def resolve_ticker(isin: str) -> str:
    """ISIN → 티커 변환. 매핑 없으면 ISIN 그대로 반환."""
    return ISIN_TO_TICKER.get(isin, isin) if isin else ""


def _parse_dollar_amounts(text: str) -> list[float]:
    """텍스트에서 ($ X.XX) 형태의 달러 금액 목록을 추출한다."""
    return [parse_float(v) for v in re.findall(r'\(\$ ([\d,\.]+)\)', text)]


# ── 현금잔고 행 생성 ──────────────────────────────────────────────────

def _build_cash_record(account: str, last_usd: float, last_fx: float, last_date: str) -> dict | None:
    """마지막 USD 현금 잔액으로 현금잔고 행을 반환한다.

    토스증권 보조행(secondary line)의 마지막 ($ X) 금액이 거래 후 USD 현금 잔고.
    환전외화입금 등 비거래 라인의 보조행도 포함하여 추적한다.
    """
    if last_usd <= 0 or last_fx <= 0 or not last_date:
        return None

    return {
        "거래일자": last_date,
        "유형": "현금잔고",
        "종목코드": "",
        "수량": 0.0,
        "단가": 0.0,
        "금액": round(last_usd, 6),
        "환율": last_fx,
        "금액KRW": round(last_usd * last_fx, 0),
        "통화": "USD",
        "증권사": BROKER,
        "계좌번호": account,
        "비고": "현금잔고",
    }


# ── PDF 파싱 ─────────────────────────────────────────────────────────

def _merge_duplicate_fills(records: list[dict]) -> list[dict]:
    """같은 날 동일 조건(가격·유형·종목)으로 분할 체결된 복수 거래를 합산한다.

    DEDUP_KEYS 값이 모두 같은 레코드는 수량·금액·금액KRW를 합산하여 하나로 합친다.
    이렇게 하면 중복 감지 테스트를 통과하면서도 보유수량을 정확히 계산한다.
    """
    from collections import defaultdict

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        key = tuple(str(r.get(k, '')) for k in DEDUP_KEYS)
        groups[key].append(r)

    merged = []
    for group in groups.values():
        if len(group) == 1:
            merged.append(group[0])
        else:
            base = dict(group[0])
            for r in group[1:]:
                base["수량"] = base.get("수량", 0) + r.get("수량", 0)
                base["금액"] = round(base.get("금액", 0) + r.get("금액", 0), 6)
                base["금액KRW"] = base.get("금액KRW", 0) + r.get("금액KRW", 0)
            merged.append(base)

    return merged

def _parse_main_line(line: str, account: str, in_dollar_section: bool) -> dict | None:
    """거래 본문행을 파싱하여 레코드 딕셔너리를 반환한다.

    달러 섹션 열 구조 (공백 구분):
      tokens[0]  = 거래일자
      tokens[1]  = 거래구분
      tokens[2:-9] = 종목명 (복수 토큰 가능)
      tokens[-9] = 환율
      tokens[-8] = 거래수량
      tokens[-7] = 거래대금 (원)
      tokens[-6] = 단가 (원)
      tokens[-5] = 수수료 (원)
      tokens[-4] = 제세금 (원)
      tokens[-3] = 변제/연체합 (원)
      tokens[-2] = 잔고 (주)
      tokens[-1] = 잔액 (원)
    """
    tokens = line.split()
    # 최소 토큰 수: 날짜 + 거래구분 + 종목명1개 + 9개 숫자 = 12
    if len(tokens) < 12:
        return None
    # 날짜 형식 확인
    if not re.match(r'^\d{4}\.\d{2}\.\d{2}$', tokens[0]):
        return None
    # 거래구분 필터
    trade_type_raw = tokens[1]
    mapped_type = TYPE_MAP.get(trade_type_raw)
    if not mapped_type:
        return None

    date = tokens[0].replace('.', '-')
    fx = parse_float(tokens[-9])
    qty = parse_float(tokens[-8])
    amount_krw = parse_float(tokens[-7])
    balance_krw = parse_float(tokens[-1])  # 잔액(원): 이 거래 후 KRW 현금 잔고

    # 종목명: tokens[2:-9] 합치기
    name_raw = ' '.join(tokens[2:-9])

    # 종목명 안에 ISIN이 포함된 경우: 아이렌(AU0000185993)
    isin = None
    isin_in_name = re.search(r'\(([A-Z]{2}[A-Z0-9]{10})\)$', name_raw)
    if isin_in_name:
        isin = isin_in_name.group(1)
        name = name_raw[:isin_in_name.start()].strip()
    else:
        name = name_raw

    ticker = resolve_ticker(isin) if isin else ""
    currency = "USD" if in_dollar_section else "KRW"

    # 배당: 수량 컬럼은 보유 주수이므로 0으로 처리
    record_qty = 0.0 if mapped_type == "배당" else qty

    return {
        "거래일자": date,
        "유형": mapped_type,
        "종목코드": ticker,
        "수량": record_qty,
        "단가": 0.0,          # 보조행에서 USD 단가로 갱신
        "금액": 0.0,          # 보조행에서 USD 거래대금으로 갱신
        "환율": fx,
        "금액KRW": amount_krw,
        "통화": currency,
        "증권사": BROKER,
        "계좌번호": account,
        "비고": name,
        "_isin": isin,        # 내부 추적용 (CSV 저장 시 제외)
        "_balance_krw": balance_krw,  # 내부 추적용: 이 거래 후 잔액(원)
        "_fx": fx,            # 내부 추적용: 이 거래의 환율
    }


def _process_secondary_line(line: str, record: dict) -> None:
    """보조행에서 ISIN과 달러 금액을 추출하여 record를 갱신한다.

    패턴 1 (ISIN 포함): (US46436E7186) ($ 100.62) ($ 100.62) ($ 0.10) ...
    패턴 2 (ISIN 없음): ($ 11,200.00) ($ 40.00) ($ 11.20) ...
    """
    # ISIN이 첫 토큰에 있는 경우: (US46436E7186)
    isin_match = re.match(r'^\(([A-Z]{2}[A-Z0-9]{10})\)', line)
    if isin_match:
        isin = isin_match.group(1)
        if not record.get("종목코드"):
            record["종목코드"] = resolve_ticker(isin)
        rest = line[isin_match.end():].strip()
    else:
        rest = line

    # 달러 금액 추출: 첫 번째 = 거래대금, 두 번째 = 단가
    amounts = _parse_dollar_amounts(rest)
    if amounts:
        record["금액"] = amounts[0]     # 거래대금 (USD)
    if len(amounts) >= 2:
        record["단가"] = amounts[1]     # 단가 (USD)


def parse_toss_pdf(pdf_path: str) -> list[dict]:
    """토스증권 거래내역서 PDF를 파싱하여 거래 레코드 목록을 반환한다.

    파싱 결과를 PDF와 같은 폴더에 중간 CSV로 저장한다.
    다음 실행 시 CSV가 있으면 scan_files()가 CSV를 우선하여 PDF 파싱을 건너뛴다.
    """
    try:
        import pdfplumber
    except ImportError:
        print("[ERROR] pdfplumber가 설치되지 않았습니다: pip install pdfplumber")
        return []

    account = extract_account(pdf_path)
    print(f"PDF 파싱: {Path(pdf_path).name}  (증권사: {BROKER}, 계좌: {account})")

    records = []
    current_record = None
    in_dollar_section = False

    # 현금잔고 추적: 보조행의 마지막 ($ X) = 해당 거래 후 USD 현금 잔고.
    # 환전외화입금 등 비거래 라인도 포함하여 모든 보조행에서 추적한다.
    last_usd_balance = 0.0
    last_usd_fx = 0.0
    last_usd_date = ""
    current_line_date = ""
    current_line_fx = 0.0

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue

                for line in text.split('\n'):
                    line = line.strip()
                    if not line:
                        continue

                    # 페이지 마커 (NNNNNN ////// 666666) 건너뜀
                    if re.match(r'^\d{6}\s+/', line):
                        continue

                    # 섹션 헤더
                    if '달러 거래내역' in line:
                        in_dollar_section = True
                        continue
                    if '원화 거래내역' in line:
                        in_dollar_section = False
                        continue

                    # 문서 메타데이터·헤더 건너뜀
                    if re.match(r'^(거래내역서|발급번호|요청|성명|계좌|거래구분|조회|수량단위|거래일자|발급일자)', line):
                        continue

                    # 보조행 (달러 금액): ($ ...) 또는 (ISIN) ($ ...) 형태
                    if line.startswith('('):
                        if current_record is not None:
                            _process_secondary_line(line, current_record)
                        # 달러 섹션의 모든 보조행에서 마지막 달러 금액(USD 현금 잔고)을 추적
                        if in_dollar_section and current_line_fx > 0:
                            amounts = _parse_dollar_amounts(line)
                            if amounts:
                                last_usd_balance = amounts[-1]  # 마지막 금액 = USD 잔액
                                last_usd_fx = current_line_fx
                                last_usd_date = current_line_date
                        continue

                    # 거래 본문행
                    record = _parse_main_line(line, account, in_dollar_section)
                    if record:
                        records.append(record)
                        current_record = record
                        current_line_date = record["거래일자"]
                        current_line_fx = record["환율"]
                    else:
                        current_record = None
                        # 비거래 본문행에서도 날짜·환율 추출 (환전외화입금 등)
                        if in_dollar_section:
                            tokens = line.split()
                            if (len(tokens) >= 3
                                    and re.match(r'^\d{4}\.\d{2}\.\d{2}$', tokens[0])):
                                current_line_date = tokens[0].replace('.', '-')
                                current_line_fx = parse_float(tokens[2])

    except Exception as e:
        print(f"  [ERROR] PDF 읽기 실패: {e}")
        return []

    print(f"  → {len(records)}건 추출")

    # 동일 조건 복수 거래 합산 (같은 날 같은 가격에 여러 번 분할 체결된 경우)
    records = _merge_duplicate_fills(records)

    # 보조행에서 추적한 마지막 USD 현금 잔고로 현금잔고 행 생성
    cash_record = _build_cash_record(account, last_usd_balance, last_usd_fx, last_usd_date)
    if cash_record:
        records.append(cash_record)

    # 중간 CSV 저장 (OUTPUT_COLUMNS만 포함, _isin 등 내부 키 제외)
    if records:
        csv_path = Path(pdf_path).with_suffix('.csv')
        clean = [{k: v for k, v in r.items() if k in OUTPUT_COLUMNS} for r in records]
        pd.DataFrame(clean, columns=OUTPUT_COLUMNS).to_csv(
            csv_path, index=False, encoding="utf-8-sig"
        )
        print(f"  → 중간 CSV 저장: {csv_path.name}")

    return records


def parse_toss_csv(csv_path: str) -> list[dict]:
    """중간 CSV를 읽어 레코드 목록을 반환한다.

    CSV를 직접 편집 후 재파싱할 때 사용한다.
    """
    account = extract_account(csv_path)
    print(f"CSV 로드: {Path(csv_path).name}  (증권사: {BROKER}, 계좌: {account})")
    try:
        df = pd.read_csv(csv_path, dtype=str).fillna("")
        for col in ["수량", "단가", "금액", "환율", "금액KRW"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        # OUTPUT_COLUMNS에 없는 열은 무시
        cols = [c for c in OUTPUT_COLUMNS if c in df.columns]
        records = df[cols].to_dict(orient="records")
        print(f"  → {len(records)}건 로드")
        return records
    except Exception as e:
        print(f"  [ERROR] CSV 읽기 실패: {e}")
        return []


# ── 파일 스캔 ────────────────────────────────────────────────────────

def scan_files(path: str) -> list[tuple[str, str]]:
    """경로에서 토스증권 PDF/CSV 파일 목록을 반환한다.

    같은 이름의 PDF와 CSV가 공존하면 CSV를 우선한다.
    Returns: [(filepath, 'pdf'|'csv'), ...]
    """
    p = Path(path)

    if p.is_file():
        ext = p.suffix.lower()
        if ext == '.pdf':
            csv_sibling = p.with_suffix('.csv')
            if csv_sibling.exists():
                return [(str(csv_sibling), 'csv')]
            return [(str(p), 'pdf')]
        if ext == '.csv' and NORMALIZED_PATTERN.match(p.name):
            return [(str(p), 'csv')]
        return []

    if not p.is_dir():
        print(f"[ERROR] 유효하지 않은 경로: {path}")
        return []

    # stem → (path, type) — PDF 먼저 등록, CSV가 있으면 덮어씀
    result: dict[str, tuple[str, str]] = {}
    for pdf in sorted(p.rglob("토스증권_*.pdf")):
        if NORMALIZED_PATTERN.match(pdf.name):
            result[pdf.stem] = (str(pdf), 'pdf')
    for csv in sorted(p.rglob("토스증권_*.csv")):
        if NORMALIZED_PATTERN.match(csv.name):
            result[csv.stem] = (str(csv), 'csv')

    return list(result.values())


# ── 파일 정리 ─────────────────────────────────────────────────────────

def organize_folder(folder: str) -> int:
    """폴더 내 파일을 계좌번호/연도 서브폴더로 이동한다.

    resource/토스증권/159-01-510195/토스증권_..._종합.pdf
      → resource/토스증권/159-01-510195/2026/토스증권_..._종합.pdf
    """
    folder_path = Path(folder)
    moved = 0
    for f in sorted(folder_path.rglob("토스증권_*")):
        if f.suffix.lower() not in ('.pdf', '.csv'):
            continue
        if not NORMALIZED_PATTERN.match(f.name):
            continue
        # 이미 계좌번호/연도 구조(3단계 이상)에 있으면 스킵
        if len(f.relative_to(folder_path).parts) >= 3:
            continue
        m = NORMALIZED_PATTERN.match(f.name)
        if not m:
            continue
        account = m.group(1)
        year = extract_year_from_filename(f.name)
        if not year:
            continue
        target_dir = folder_path / account / year
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f.name
        if target.exists():
            print(f"  [SKIP] 이미 존재: {target}")
            continue
        f.rename(target)
        print(f"  {f.name} → {account}/{year}/{f.name}")
        moved += 1
    return moved


# ── 메인 ─────────────────────────────────────────────────────────────

def sort_records(df: pd.DataFrame) -> pd.DataFrame:
    """날짜순 정렬 (stable — 같은 날은 원본 순서 유지)."""
    return df.sort_values("거래일자", kind="stable").reset_index(drop=True)


def main():
    if len(sys.argv) < 2:
        print("사용법: python parse_toss.py [--organize] <파일 또는 폴더 경로>")
        print("예시:")
        print("  python parse_toss.py resource/")
        print("  python parse_toss.py resource/토스증권/159-01-510195/2026/")
        print("  python parse_toss.py --organize resource/토스증권/")
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
        print("처리할 토스증권 PDF/CSV 파일이 없습니다.")
        sys.exit(1)

    print(f"\n=== 토스증권 거래내역 파서 ===")
    print(f"대상: {len(files)}개 파일\n")

    all_records = []
    date_ranges: list[tuple[str, str, str, str]] = []  # (broker, account, min_date, max_date)

    for filepath, ftype in files:
        account = extract_account(filepath)
        if ftype == 'pdf':
            records = parse_toss_pdf(filepath)
        else:
            records = parse_toss_csv(filepath)
        all_records.extend(records)
        if records:
            dates = [r["거래일자"] for r in records]
            date_ranges.append((BROKER, account, min(dates), max(dates)))

    if not all_records:
        print("\n추출된 거래가 없습니다.")
        sys.exit(0)

    # 내부 추적 키(_isin 등) 제거 후 DataFrame 생성
    clean_records = [{k: v for k, v in r.items() if k in OUTPUT_COLUMNS} for r in all_records]
    df_new = pd.DataFrame(clean_records, columns=OUTPUT_COLUMNS)

    # 기존 CSV와 병합:
    # 처리한 파일의 날짜 범위 내 기존 토스증권 레코드를 삭제 후 새 레코드 추가.
    # 이 방식으로 재실행 시 중복 누적 없이, 같은 날 동일 금액의 복수 거래도 정확하게 보존.
    output_dir = Path.cwd() / "output"
    output_path = output_dir / "종합거래내역.csv"

    if output_path.exists():
        print(f"\n기존 파일 병합: {output_path}")
        existing = pd.read_csv(output_path, dtype=str).fillna("")
        for broker, account, min_d, max_d in date_ranges:
            keep = ~(
                (existing["증권사"] == broker) &
                (existing["계좌번호"] == account) &
                (existing["거래일자"] >= min_d) &
                (existing["거래일자"] <= max_d)
            )
            removed_existing = (~keep).sum()
            if removed_existing:
                print(f"  기존 레코드 교체: {broker}/{account} {min_d}~{max_d} ({removed_existing}건 삭제)")
            existing = existing[keep]
        df = pd.concat([existing, df_new], ignore_index=True)
    else:
        df = df_new

    # 숫자 컬럼 타입 보정
    for col in ["수량", "단가", "금액", "환율", "금액KRW"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    for col in ["종목코드", "통화", "비고"]:
        df[col] = df[col].fillna("")

    df = sort_records(df)

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
