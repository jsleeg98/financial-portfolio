#!/usr/bin/env python3
"""NH나무증권 거래내역 .xls 파서

해외주식거래내역 및 종합거래내역 .xls 파일을 읽어 종합거래내역 CSV로 변환한다.

사용법:
    python parse_namu.py <파일 또는 폴더 경로>
    python parse_namu.py --organize <계좌 폴더 경로>

예시:
    python parse_namu.py resource/
    python parse_namu.py resource/NH나무증권/202-01-292788/2025/
    python parse_namu.py --organize resource/NH나무증권/202-02-292788/  # 미정리 파일 연도별 정리

참고: 종합거래내역 파일 파싱 시 거래내역메모 내용을 항상 자동으로 제거한다.
"""

import os
import sys
import glob
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

# ── 종목명 → 티커 매핑 (해외주식거래내역 파일용) ─────────────────────
STOCK_NAME_TO_TICKER = {
    "APPLE INC": "AAPL",
    "MICROSOFT CP": "MSFT",
    "NVIDIA CORP": "NVDA",
    "IONQ INC ORD": "IONQ",
    "IREN LIMITED ORD": "IREN",
    "ISHARES 0 TO 3 MNTH TREASURY BND ETF": "SGOV",
    "META PLTFORM ORD": "META",
    "RCKT LAB CRP ORD": "RKLB",
    "STATE STREET SPDR PORTFL S&P 500 ETF": "SPYM",
    "VANGUARD S&P 500 ETF": "VOO",
    "DELTA AIR LIN": "DAL",
}

# ── ISIN → 티커 매핑 (종합거래내역 파일용) ───────────────────────────
ISIN_TO_TICKER = {
    "US0378331005": "AAPL",     # 애플
    "US5949181045": "MSFT",     # 마이크로소프트
    "US67066G1040": "NVDA",     # 엔비디아
    "US46222L1089": "IONQ",     # 아이온큐
    "AU0000185993": "IREN",     # 아이렌
    "US46436E7186": "SGOV",     # 아이셰어즈 0-3개월 미국 국채 ETF
    "US30303M1027": "META",     # 메타
    "US7731211089": "RKLB",     # 로켓 랩
    "US78464A8541": "SPYM",     # SPDR S&P500 포트폴리오 ETF
    "US9229083632": "VOO",      # 뱅가드 S&P500 ETF
    "US2473617023": "DAL",      # 델타 에어라인스
    "US8552441094": "SBUX",     # 스타벅스
    "US74347X8314": "TQQQ",     # 프로셰어즈 QQQ 3배 ETF
    "US1725731079": "CRCL",     # 써클 인터넷 그룹 (Circle Internet Group)
}

# 종합파일 ISIN 추출 패턴
ISIN_PATTERN = re.compile(r"([A-Z]{2}[A-Z0-9]{9,10})$")

# ── 제외 대상 ────────────────────────────────────────────────────────
EXCLUDE_TRADE_TYPES = {"환전", "출금", "출고"}

EXCLUDE_SUB_DETAILS = {
    "이체입금", "이체출금",
    "대체입금", "대체출금", "외화대체입금", "외화대체출금",
    "공모주입고", "공모청약출금", "공모주청약수수료출금",
}

EXCLUDE_STOCK_NAMES = {"CMA NOTE PAYABLE"}

# 국내 종목코드 패턴 (6자리 숫자)
DOMESTIC_CODE_PATTERN = re.compile(r"^\d{6}$")

# 종합파일 종목명+코드 분리 패턴 (예: "KT&G033780" → "KT&G", "033780")
DOMESTIC_STOCK_FIELD = re.compile(r"^(.+?)(\d{6})$")

# 종합파일 국내 주식 거래 상세내용 패턴
DOMESTIC_TRADE_PATTERN = re.compile(r"코스피|코스닥|KOSPI|KOSDAQ", re.IGNORECASE)

# ── 출력 컬럼 ────────────────────────────────────────────────────────
OUTPUT_COLUMNS = [
    "거래일자", "유형", "종목코드", "수량", "단가",
    "금액", "환율", "금액KRW", "통화", "증권사", "계좌번호", "비고",
]

DEDUP_KEYS = ["거래일자", "유형", "종목코드", "수량", "단가", "금액", "통화"]

# ── 깨진 인코딩 fallback 매핑 ────────────────────────────────────────
BROKEN_ENCODING_MAP = {
    "\xC5\xB5": "매도",
    "\xC5\xBC": "매수",
    "\xC8\xAF": "환전",
    "\xD4\xB1": "입금",
}


def parse_filename(filepath: str) -> tuple[str, str]:
    """파일명에서 증권사명과 계좌번호를 추출한다."""
    stem = Path(filepath).stem
    parts = stem.split("_")
    broker = parts[0] if len(parts) >= 1 else "unknown"
    account = parts[1] if len(parts) >= 2 else "unknown"
    return broker, account


def identify_trade_type(raw_text: str) -> str | None:
    """거래유형 텍스트를 정규화한다. 인식 불가시 None 반환."""
    text = raw_text.strip()

    known = {"매도", "매수", "입금", "출금", "환전", "입고", "출고"}
    if text in known:
        return text

    for pattern, mapped in BROKEN_ENCODING_MAP.items():
        if pattern in text:
            return mapped
    if "ŵ" in text:
        return "매도"
    if "ż" in text:
        return "매수"
    if "ȯ" in text:
        return "환전"
    if "Ա" in text:
        return "입금"
    if "뱄" in text or "킹" in text:
        return "이체"

    print(f"  [WARNING] 인식 불가 거래유형: {repr(text)}")
    return None


def resolve_ticker(stock_name: str, stock_code: str) -> str | None:
    """종목명→티커 매핑. 국내주식이면 None 반환."""
    name = stock_name.strip()

    if name in EXCLUDE_STOCK_NAMES:
        return None

    code = stock_code.strip()
    if DOMESTIC_CODE_PATTERN.match(code):
        return None

    if name in STOCK_NAME_TO_TICKER:
        return STOCK_NAME_TO_TICKER[name]

    if name:
        print(f"  [WARNING] 종목 매핑 없음: '{name}' (코드: {code}) — STOCK_NAME_TO_TICKER에 추가 필요")
        return name

    return None


def parse_domestic_stock_field(text: str) -> tuple[str, str]:
    """종합파일의 종목명+코드 필드를 분리한다.

    예: 'KT&G033780' → ('KT&G', '033780')
        '삼성전자우005935' → ('삼성전자우', '005935')
    """
    m = DOMESTIC_STOCK_FIELD.match(text.strip())
    if m:
        return m.group(1), m.group(2)
    return text.strip(), ""


def parse_number(text: str) -> float:
    """숫자 문자열을 float으로 변환한다. 콤마 제거, 빈 값은 0."""
    s = text.strip().replace(",", "")
    if not s:
        return 0.0
    return float(s)


def is_jonghap_file(filepath: str) -> bool:
    """종합거래내역 파일 여부를 파일명으로 판별한다."""
    return "종합" in Path(filepath).name


# ── 해외주식거래내역 파서 (메인행 15td + 서브행 13td) ─────────────────

def parse_overseas_file(filepath: str) -> list[dict]:
    """해외주식거래내역 .xls 파일을 파싱하여 거래 레코드 리스트를 반환한다."""
    broker, account = parse_filename(filepath)
    print(f"  파싱 [해외]: {Path(filepath).name} (증권사: {broker}, 계좌: {account})")

    with open(filepath, "rb") as f:
        raw = f.read()

    soup = BeautifulSoup(raw, "html.parser", from_encoding="euc-kr")
    tbody = soup.find("tbody")
    if not tbody:
        print(f"  [ERROR] <tbody> 없음: {filepath}")
        return []

    rows = tbody.find_all("tr")
    records = []

    i = 0
    while i < len(rows) - 1:
        main_tds = rows[i].find_all("td")
        sub_tds = rows[i + 1].find_all("td")

        if len(main_tds) != 15 or len(sub_tds) != 13:
            i += 1
            continue

        i += 2

        trade_date_raw = main_tds[0].get_text(strip=True)
        trade_type_raw = main_tds[1].get_text(strip=True)
        stock_name = main_tds[2].get_text(strip=True)
        quantity_raw = main_tds[3].get_text(strip=True)
        amount_usd_raw = main_tds[4].get_text(strip=True)
        settlement_usd_raw = main_tds[6].get_text(strip=True)

        sub_detail = sub_tds[0].get_text(strip=True)
        stock_code = sub_tds[1].get_text(strip=True)
        unit_price_raw = sub_tds[2].get_text(strip=True)
        amount_krw_raw = sub_tds[3].get_text(strip=True)
        exchange_rate_raw = sub_tds[12].get_text(strip=True)

        trade_type = identify_trade_type(trade_type_raw)
        if trade_type is None:
            continue

        if trade_type in EXCLUDE_TRADE_TYPES:
            continue
        if trade_type == "이체":
            continue
        if sub_detail in EXCLUDE_SUB_DETAILS:
            continue
        if stock_name in EXCLUDE_STOCK_NAMES:
            continue

        ticker = resolve_ticker(stock_name, stock_code)
        if ticker is None and stock_name and stock_name not in EXCLUDE_STOCK_NAMES:
            continue

        output_type = trade_type
        remark = ""
        if trade_type == "입금":
            if "배당" in sub_detail:
                output_type = "배당"
                remark = sub_detail
            else:
                remark = sub_detail

        trade_date = trade_date_raw.replace(".", "-")

        quantity = parse_number(quantity_raw)
        unit_price = parse_number(unit_price_raw)
        amount_usd = parse_number(amount_usd_raw)
        exchange_rate = parse_number(exchange_rate_raw)
        amount_krw = parse_number(amount_krw_raw)

        if output_type in ("배당", "입금") and amount_usd == 0:
            amount_usd = parse_number(settlement_usd_raw)

        if amount_krw == 0 and amount_usd > 0 and exchange_rate > 0:
            amount_krw = round(amount_usd * exchange_rate, 0)

        record = {
            "거래일자": trade_date,
            "유형": output_type,
            "종목코드": ticker or "",
            "수량": quantity,
            "단가": unit_price,
            "금액": amount_usd,
            "환율": exchange_rate,
            "금액KRW": amount_krw,
            "통화": "USD",
            "증권사": broker,
            "계좌번호": account,
            "비고": remark,
        }
        records.append(record)

    print(f"  → {len(records)}건 추출")
    return records


# ── 종합거래내역 파서 (메인행 13td + 서브행 8td) ─────────────────────
# 헤더:
#   메인: 실거래일자, 거래유형, 상세내용, 종목명, 수량, 거래금액,
#         잔고, 이율, 수수료, 연체료, 받는통장표시내용, 투자위험도, 거래일자
#   서브: 단가, 정산금액, 잔고금액, 이자, 세금, 변제금, 거래내역메모, 비고

def resolve_isin_ticker(stock_field: str) -> tuple[str | None, str]:
    """종합파일 종목필드에서 ISIN을 추출하고 티커로 변환한다.

    반환: (ticker, isin). 매핑 없으면 ticker=None.
    """
    m = ISIN_PATTERN.search(stock_field.strip())
    if not m:
        return None, ""
    isin = m.group(1)
    ticker = ISIN_TO_TICKER.get(isin)
    if ticker is None:
        kr_name = stock_field[:m.start()].strip()
        print(f"  [WARNING] ISIN 매핑 없음: '{kr_name}' (ISIN: {isin}) — ISIN_TO_TICKER에 추가 필요")
        return kr_name, isin
    return ticker, isin


# 종합파일 해외 거래 상세내용
FOREIGN_TRADE_SUB_DETAILS = {"외화증권매수", "외화증권매도", "외화배당금입금"}
# 종합파일 해외 액면분할
FOREIGN_SPLIT_SUB_DETAILS = {"외화주식액면분할입고", "외화주식액면분할출고"}


def parse_jonghap_file(filepath: str) -> list[dict]:
    """종합거래내역 .xls 파일에서 국내+해외 주식 거래를 추출한다."""
    broker, account = parse_filename(filepath)
    print(f"  파싱 [종합]: {Path(filepath).name} (증권사: {broker}, 계좌: {account})")

    with open(filepath, "rb") as f:
        raw = f.read()

    soup = BeautifulSoup(raw, "html.parser", from_encoding="euc-kr")
    tbody = soup.find("tbody")
    if not tbody:
        print(f"  [ERROR] <tbody> 없음: {filepath}")
        return []

    rows = tbody.find_all("tr")
    domestic_records = []
    foreign_records = []

    i = 0
    while i < len(rows) - 1:
        main_tds = rows[i].find_all("td")
        sub_tds = rows[i + 1].find_all("td")

        if len(main_tds) != 13 or len(sub_tds) != 8:
            i += 1
            continue

        i += 2

        trade_date_raw = main_tds[0].get_text(strip=True)
        trade_type = main_tds[1].get_text(strip=True)
        sub_detail = main_tds[2].get_text(strip=True)
        stock_field = main_tds[3].get_text(strip=True)
        quantity_raw = main_tds[4].get_text(strip=True)
        amount_raw = main_tds[5].get_text(strip=True)

        unit_price_raw = sub_tds[0].get_text(strip=True)
        settlement_raw = sub_tds[1].get_text(strip=True)

        trade_date = trade_date_raw.replace(".", "-")

        # ── 해외주식 거래 ──
        if sub_detail in FOREIGN_TRADE_SUB_DETAILS and stock_field:
            ticker, isin = resolve_isin_ticker(stock_field)
            if ticker is None:
                continue

            quantity = parse_number(quantity_raw)
            unit_price = parse_number(unit_price_raw)
            amount_usd = parse_number(amount_raw)

            # 유형 분류
            if sub_detail == "외화배당금입금":
                output_type = "배당"
                # 배당은 정산금액 사용
                if amount_usd == 0:
                    amount_usd = parse_number(settlement_raw)
            elif sub_detail == "외화증권매수":
                output_type = "매수"
            else:
                output_type = "매도"

            foreign_records.append({
                "거래일자": trade_date,
                "유형": output_type,
                "종목코드": ticker,
                "수량": quantity,
                "단가": unit_price,
                "금액": amount_usd,
                "환율": 0.0,
                "금액KRW": 0.0,
                "통화": "USD",
                "증권사": broker,
                "계좌번호": account,
                "비고": "",
            })
            continue

        # ── 해외주식 액면분할 ──
        if sub_detail in FOREIGN_SPLIT_SUB_DETAILS and stock_field:
            ticker, isin = resolve_isin_ticker(stock_field)
            if ticker is None:
                continue

            quantity = parse_number(quantity_raw)
            split_type = "입고" if "입고" in sub_detail else "출고"

            foreign_records.append({
                "거래일자": trade_date,
                "유형": split_type,
                "종목코드": ticker,
                "수량": quantity,
                "단가": 0.0,
                "금액": 0.0,
                "환율": 0.0,
                "금액KRW": 0.0,
                "통화": "USD",
                "증권사": broker,
                "계좌번호": account,
                "비고": sub_detail,
            })
            continue

        # ── 국내주식 기업 이벤트 (입고/출고) ──
        domestic_event_types = {
            "감자출고": "감자출고",
            "감자입고": "입고",
            "공모주입고": "입고",
            "회사분할입고": "입고",
            "액면분할입고": "입고",
            "액면분할출고": "출고",
        }
        if sub_detail in domestic_event_types and stock_field:
            stock_name, stock_code = parse_domestic_stock_field(stock_field)
            if stock_name:
                domestic_records.append({
                    "거래일자": trade_date,
                    "유형": domestic_event_types[sub_detail],
                    "종목코드": stock_name,
                    "수량": parse_number(quantity_raw),
                    "단가": parse_number(unit_price_raw),
                    "금액": 0.0,
                    "환율": 0.0,
                    "금액KRW": 0.0,
                    "통화": "KRW",
                    "증권사": broker,
                    "계좌번호": account,
                    "비고": sub_detail,
                })
            continue

        # ── 국내주식 거래 (코스피/코스닥 매수·매도) ──
        if trade_type not in ("매수", "매도"):
            continue
        if not DOMESTIC_TRADE_PATTERN.search(sub_detail):
            continue
        if not stock_field:
            continue

        stock_name, stock_code = parse_domestic_stock_field(stock_field)
        if not stock_name:
            continue

        quantity = parse_number(quantity_raw)
        unit_price = parse_number(unit_price_raw)
        amount = parse_number(amount_raw)

        domestic_records.append({
            "거래일자": trade_date,
            "유형": trade_type,
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

    records = domestic_records + foreign_records
    print(f"  → {len(domestic_records)}건 (국내) + {len(foreign_records)}건 (해외) 추출")
    return records


# ── 입력 파일 살균 (거래내역메모 내용 제거) ──────────────────────────

def sanitize_jonghap_file(filepath: str) -> bool:
    """종합거래내역 .xls에서 거래내역메모 열의 내용을 제거한다.

    헤더는 유지하고 본문 내용만 비운다.
    반환: 변경이 있었으면 True.
    """
    with open(filepath, "rb") as f:
        raw = f.read()

    soup = BeautifulSoup(raw, "html.parser", from_encoding="euc-kr")

    modified = False

    # tbody: 서브행(8td)의 index 6 (거래내역메모) 비우기
    tbody = soup.find("tbody")
    if tbody:
        for tr in tbody.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) == 8:
                content = tds[6].get_text(strip=True)
                if content:
                    tds[6].string = ""
                    modified = True

    if modified:
        with open(filepath, "wb") as f:
            f.write(soup.encode("euc-kr"))
        print(f"  살균 완료: {Path(filepath).name}")

    return modified


# ── 공통 유틸 ────────────────────────────────────────────────────────

# 정리가 필요한 파일명 패턴: 날짜가 YYYY.MM.DD 형식인 파일
# 예: 종합거래내역(상세)_이동현_2020.01.01_2020.03.31.xls
ORGANIZE_FILENAME_PATTERN = re.compile(
    r".*_(\d{4})\.(\d{2})\.(\d{2})_(\d{4})\.(\d{2})\.(\d{2})\.xls$"
)

# 이미 정규화된 파일명 패턴: NH나무증권_{계좌번호}_{YYMMDD}-{YYMMDD}_종합.xls
NORMALIZED_FILENAME_PATTERN = re.compile(
    r"NH나무증권_[\d-]+_\d{6}-\d{6}_종합\.xls$"
)


def organize_account_folder(account_dir: Path, broker: str = "NH나무증권") -> int:
    """계좌 폴더 내 미정리 파일을 연도별 폴더로 이동하고 파일명을 정규화한다.

    정규화 규칙:
    - 파일명: {broker}_{계좌번호}_{YYMMDD}-{YYMMDD}_종합.xls
    - 위치: {account_dir}/{연도}/

    이미 연도 하위 폴더에 있거나 정규화된 파일은 건너뛴다.
    반환: 정리한 파일 수.
    """
    account = account_dir.name
    moved = 0

    for f in sorted(account_dir.glob("*.xls")):
        m = ORGANIZE_FILENAME_PATTERN.match(f.name)
        if not m:
            print(f"  [SKIP] 패턴 불일치: {f.name}")
            continue
        y1, mo1, d1, y2, mo2, d2 = m.groups()
        start = f"{y1[2:]}{mo1}{d1}"
        end = f"{y2[2:]}{mo2}{d2}"
        year = y1
        new_name = f"{broker}_{account}_{start}-{end}_종합.xls"
        year_dir = account_dir / year
        year_dir.mkdir(exist_ok=True)
        target = year_dir / new_name
        f.rename(target)
        print(f"  {f.name} → {year}/{new_name}")
        moved += 1

    return moved


def auto_organize_if_needed(input_path: str) -> None:
    """입력 경로 내에서 정규화되지 않은 .xls 파일을 감지하면 자동으로 정리한다.

    ORGANIZE_FILENAME_PATTERN에 매칭되는 파일이 있는 폴더를 찾아
    organize_account_folder()를 자동 호출한다.
    """
    p = Path(input_path)
    if p.is_file():
        return  # 단일 파일은 정리 불필요

    dirs_to_organize: set[Path] = set()
    for xls in p.rglob("*.xls"):
        if ORGANIZE_FILENAME_PATTERN.match(xls.name):
            dirs_to_organize.add(xls.parent)

    for dir_path in sorted(dirs_to_organize):
        print(f"\n[자동 정리] 정규화되지 않은 파일 감지: {dir_path}")
        moved = organize_account_folder(dir_path)
        print(f"  → {moved}개 파일 정리 완료")


def scan_files(path: str) -> list[str]:
    """경로에서 .xls 파일 목록을 반환한다."""
    p = Path(path)
    if p.is_file() and p.suffix.lower() == ".xls":
        return [str(p)]
    if p.is_dir():
        files = sorted(glob.glob(str(p / "**" / "*.xls"), recursive=True))
        return files
    print(f"[ERROR] 유효하지 않은 경로: {path}")
    return []


def sort_records(df: pd.DataFrame) -> pd.DataFrame:
    """날짜순 정렬한다. 같은 날은 원본 파일 순서를 유지 (stable sort)."""
    df = df.sort_values("거래일자", kind="stable").reset_index(drop=True)
    return df


def main():
    if len(sys.argv) < 2:
        print("사용법: python parse_namu.py [--organize] <파일 또는 폴더 경로>")
        print("예시:")
        print("  python parse_namu.py resource/")
        print("  python parse_namu.py resource/NH나무증권/202-01-292788/2025/")
        print("  python parse_namu.py --organize resource/NH나무증권/202-02-292788/  # 미정리 파일 연도별 정리")
        sys.exit(1)

    args = sys.argv[1:]

    # --organize: 계좌 폴더 내 파일명 정규화 및 연도별 이동
    if args[0] == "--organize":
        if len(args) < 2:
            print("[ERROR] --organize 옵션에는 계좌 폴더 경로가 필요합니다.")
            sys.exit(1)
        account_dir = Path(args[1])
        if not account_dir.is_dir():
            print(f"[ERROR] 폴더를 찾을 수 없습니다: {account_dir}")
            sys.exit(1)
        print(f"\n=== 파일 정리: {account_dir} ===\n")
        moved = organize_account_folder(account_dir)
        print(f"\n정리 완료: {moved}개 파일 이동")
        sys.exit(0)

    # --sanitize: 살균만 수행 (파싱/CSV 출력 없음)
    if args[0] == "--sanitize":
        if len(args) < 2:
            print("[ERROR] --sanitize 옵션에는 경로가 필요합니다.")
            sys.exit(1)
        files = scan_files(args[1])
        jonghap_files = [f for f in files if is_jonghap_file(f)]
        print(f"\n=== 살균 모드: {len(jonghap_files)}개 종합 파일 ===\n")
        for f in jonghap_files:
            sanitize_jonghap_file(f)
        print("\n살균 완료")
        sys.exit(0)

    input_path = args[0]
    auto_organize_if_needed(input_path)
    files = scan_files(input_path)
    if not files:
        print("처리할 .xls 파일이 없습니다.")
        sys.exit(1)

    overseas_files = [f for f in files if not is_jonghap_file(f)]
    jonghap_files = [f for f in files if is_jonghap_file(f)]

    total = len(overseas_files) + len(jonghap_files)
    print(f"\n=== NH나무증권 거래내역 파서 ===")
    print(f"대상: {total}개 파일 (해외: {len(overseas_files)}, 종합: {len(jonghap_files)})\n")

    # 종합 파일 살균 (거래내역메모 제거) — 항상 실행
    for f in jonghap_files:
        sanitize_jonghap_file(f)

    all_records = []
    for f in overseas_files:
        records = parse_overseas_file(f)
        all_records.extend(records)
    for f in jonghap_files:
        records = parse_jonghap_file(f)
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
        df = pd.concat([existing, df], ignore_index=True)

    # 숫자 컬럼 타입 보정
    for col in ["수량", "단가", "금액", "환율", "금액KRW"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # 문자열 컬럼 NaN→빈 문자열 통일
    for col in ["종목코드", "통화", "비고"]:
        df[col] = df[col].fillna("")

    df = sort_records(df)

    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")

    print(f"\n=== 완료 ===")
    print(f"파일: {total}개 처리")
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
