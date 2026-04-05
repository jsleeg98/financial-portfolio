#!/usr/bin/env python3
"""증권사 XLS 잔고 검증 스크립트

각 증권사 거래내역 XLS 파일의 종목별 잔고(유가잔고/유가증권잔고)를
output/종합거래내역.csv의 계산 잔고와 비교하여 불일치를 보고한다.

사용법:
    python scripts/verify_balances.py
    python scripts/verify_balances.py --broker 메리츠증권
"""

import sys
import csv
import glob
import re
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / ".claude/skills/parse-namu/scripts"))
sys.path.insert(0, str(PROJECT_ROOT / ".claude/skills/parse-meritz/scripts"))
sys.path.insert(0, str(PROJECT_ROOT / ".claude/skills/parse-kiwoom/scripts"))


# ── CSV 잔고 계산 ────────────────────────────────────────────────────

def get_csv_balances() -> dict:
    """output/종합거래내역.csv에서 (증권사, 계좌, 종목) → 보유수량 계산."""
    path = PROJECT_ROOT / "output" / "종합거래내역.csv"
    balances: dict[tuple, float] = defaultdict(float)
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            유형 = row["유형"]
            ticker = row["종목코드"]
            if not ticker:
                continue
            key = (row["증권사"], row["계좌번호"], ticker)
            qty = float(row["수량"] or 0)
            if 유형 in ("매수", "입고"):
                balances[key] += qty
            elif 유형 in ("매도", "출고", "감자출고"):
                balances[key] -= qty
    return dict(balances)


# ── 메리츠증권 ───────────────────────────────────────────────────────

def get_meritz_balances() -> dict:
    """메리츠증권 XLS의 상세행[10] (유가증권잔고)에서 잔고 추출.

    '해외주식매수' / '해외주식매도' 적요 행(거래금액=0)의
    detail_row[10]이 거래 후 남은 주식 수량이다.
    """
    try:
        import xlrd
        from parse_meritz import resolve_ticker, parse_float
    except ImportError as e:
        print(f"[WARN] 메리츠증권 검증 생략: {e}")
        return {}

    BROKER = "메리츠증권"
    STOCK_TYPES = {"해외주식매수", "해외주식매도"}
    FILE_PAT = re.compile(r"메리츠증권_([^_]+)_")

    # 파일을 날짜 오름차순으로 처리하여 최신 잔고가 마지막에 기록됨
    files = sorted(glob.glob(str(PROJECT_ROOT / "resource/메리츠증권/**/*.xls"), recursive=True))
    balances: dict[tuple, float] = {}

    for filepath in files:
        m = FILE_PAT.search(Path(filepath).name)
        if not m:
            continue
        account = m.group(1)
        try:
            wb = xlrd.open_workbook(filepath)
            ws = wb.sheet_by_index(0)
        except Exception as e:
            print(f"  [WARN] {Path(filepath).name} 열기 실패: {e}")
            continue

        i = 2
        while i + 1 < ws.nrows:
            main_row = ws.row_values(i)
            detail_row = ws.row_values(i + 1)
            i += 2

            trade_type = str(detail_row[0]).strip()
            if trade_type not in STOCK_TYPES:
                continue

            code = str(main_row[1]).strip()
            ticker = resolve_ticker(code)
            if not ticker:
                continue

            try:
                qty = float(str(detail_row[10]).strip())
            except (ValueError, IndexError):
                continue

            balances[(BROKER, account, ticker)] = qty

    return balances


# ── 키움증권 ─────────────────────────────────────────────────────────

def get_kiwoom_balances() -> dict:
    """키움증권 XLS의 tds[18] (유가잔고)에서 잔고 추출.

    거래마다 업데이트되는 누적 잔고이므로 마지막 등장 값이 최종 잔고다.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:
        print(f"[WARN] 키움증권 검증 생략: {e}")
        return {}

    BROKER = "키움증권"
    FILE_PAT = re.compile(r"키움증권_([^_]+)_")

    files = sorted(glob.glob(str(PROJECT_ROOT / "resource/키움증권/**/*.xls"), recursive=True))
    balances: dict[tuple, float] = {}

    for filepath in files:
        m = FILE_PAT.search(Path(filepath).name)
        if not m:
            continue
        account = m.group(1)

        try:
            with open(filepath, encoding="utf-8") as f:
                soup = BeautifulSoup(f.read(), "html.parser")
        except Exception:
            try:
                with open(filepath, encoding="euc-kr") as f:
                    soup = BeautifulSoup(f.read(), "html.parser")
            except Exception as e:
                print(f"  [WARN] {Path(filepath).name} 열기 실패: {e}")
                continue

        rows = soup.find_all("tr")
        for tr in rows[2:]:  # 헤더 2행 건너뜀
            tds = tr.find_all(["td", "th"])
            if len(tds) < 19:
                continue

            stock_name = tds[1].get_text(strip=True)
            if not stock_name:
                continue

            trade_type = tds[12].get_text(strip=True) if len(tds) > 12 else ""
            # 주식 거래 유형만 처리 (배당/분배금 등 제외)
            is_stock_trade = "매수" in trade_type or "매도" in trade_type
            if not is_stock_trade:
                continue

            balance_raw = tds[18].get_text(strip=True).replace(",", "")
            if balance_raw:
                try:
                    balance = float(balance_raw)
                except ValueError:
                    continue
            else:
                # 잔고 공백 = 전량 매도로 0이 된 경우
                balance = 0.0

            balances[(BROKER, account, stock_name)] = balance

    return balances


# ── NH나무증권 ───────────────────────────────────────────────────────

def get_namu_balances() -> dict:
    """NH나무증권 XLS의 메인행[6] (잔고)에서 종목별 잔고 추출.

    '매수' / '매도' 거래유형 행에서 메인행[6]이 거래 후 남은 주식 수량이다.
    종목명은 {한국명}{ISIN} 형식이며, ISIN으로 티커를 조회한다.
    """
    try:
        from bs4 import BeautifulSoup
        from parse_namu import ISIN_TO_TICKER
    except ImportError as e:
        print(f"[WARN] NH나무증권 검증 생략: {e}")
        return {}

    BROKER = "NH나무증권"
    ISIN_RE = re.compile(r"([A-Z]{2}[A-Z0-9]{10})$")
    FILE_PAT = re.compile(r"NH나무증권_([^_]+)_")
    STOCK_TYPES = {"매수", "매도"}

    files = sorted(glob.glob(str(PROJECT_ROOT / "resource/NH나무증권/**/*.xls"), recursive=True))
    balances: dict[tuple, float] = {}

    for filepath in files:
        m = FILE_PAT.search(Path(filepath).name)
        if not m:
            continue
        account = m.group(1)

        try:
            with open(filepath, encoding="euc-kr") as f:
                soup = BeautifulSoup(f.read(), "html.parser")
        except Exception as e:
            print(f"  [WARN] {Path(filepath).name} 열기 실패: {e}")
            continue

        rows = soup.find_all("tr")
        # 메인행(짝수)과 서브행(홀수)이 쌍으로 구성됨
        i = 2  # 헤더 2행 이후
        while i + 1 < len(rows):
            main_tds = rows[i].find_all(["td", "th"])
            i += 2

            if len(main_tds) < 7:
                continue

            trade_type = main_tds[1].get_text(strip=True)
            if trade_type not in STOCK_TYPES:
                continue

            stock_name_raw = main_tds[3].get_text(strip=True)
            balance_raw = main_tds[6].get_text(strip=True).replace(",", "")
            if not stock_name_raw or not balance_raw:
                continue

            try:
                balance = float(balance_raw)
            except ValueError:
                continue

            # ISIN 추출 → 티커 매핑
            isin_m = ISIN_RE.search(stock_name_raw)
            if not isin_m:
                continue
            isin = isin_m.group(1)
            ticker = ISIN_TO_TICKER.get(isin)
            if not ticker:
                # 매핑 누락 - 경고만 출력
                continue

            balances[(BROKER, account, ticker)] = balance

    return balances


# ── 토스증권 ─────────────────────────────────────────────────────────

def get_toss_balances() -> dict:
    """토스증권 중간 CSV의 잔고_주 컬럼에서 종목별 최종 잔고 추출.

    parse_toss.py가 PDF에서 추출한 '잔고(주)' (tokens[-2]) 값을 중간 CSV의
    잔고_주 컬럼에 저장한다. 파일을 날짜순으로 읽어 마지막 등장 값이 최종 잔고다.
    """
    BROKER = "토스증권"
    FILE_PAT = re.compile(r"토스증권_([^_]+)_")

    files = sorted(glob.glob(str(PROJECT_ROOT / "resource/토스증권/**/*.csv"), recursive=True))
    balances: dict[tuple, float] = {}
    found_balance_col = False

    for filepath in files:
        m = FILE_PAT.search(Path(filepath).name)
        if not m:
            continue
        account = m.group(1)

        try:
            with open(filepath, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                if "잔고_주" not in (reader.fieldnames or []):
                    continue  # 구버전 CSV — 잔고_주 컬럼 없음 (PDF 재파싱 필요)
                found_balance_col = True
                for row in reader:
                    유형 = row.get("유형", "").strip()
                    if 유형 not in ("매수", "매도"):
                        continue
                    ticker = row.get("종목코드", "").strip()
                    if not ticker:
                        continue
                    balance_raw = row.get("잔고_주", "").strip()
                    if not balance_raw:
                        continue
                    try:
                        balance = float(balance_raw)
                    except ValueError:
                        continue
                    balances[(BROKER, account, ticker)] = balance
        except Exception as e:
            print(f"  [WARN] {Path(filepath).name} 읽기 실패: {e}")

    if not found_balance_col and files:
        print("[WARN] 토스증권 CSV에 잔고_주 컬럼이 없습니다. "
              "PDF를 재파싱하면 자동 생성됩니다: "
              "python .claude/skills/parse-toss/scripts/parse_toss.py resource/토스증권/")

    return balances


# ── 메인 ─────────────────────────────────────────────────────────────

def verify_all(broker_filter: str | None = None) -> bool:
    print("=== 증권사 잔고 검증 ===\n")

    csv_balances = get_csv_balances()

    # 증권사별 XLS 잔고 수집
    xls_balances: dict[tuple, float] = {}

    brokers = {
        "메리츠증권": get_meritz_balances,
        "키움증권": get_kiwoom_balances,
        "NH나무증권": get_namu_balances,
        "토스증권": get_toss_balances,
    }
    for broker, fn in brokers.items():
        if broker_filter and broker != broker_filter:
            continue
        xls_balances.update(fn())

    if not xls_balances:
        print("검증 가능한 XLS 잔고 데이터가 없습니다.")
        return True

    ok_count = 0
    errors: list[tuple] = []
    pre_csv: list[tuple] = []  # CSV 추적 이전 보유 종목 (거래 기록 없음)

    # XLS에 잔고가 기록된 항목만 검증
    for key, xls_qty in sorted(xls_balances.items()):
        xls_qty_r = round(xls_qty, 6)

        # CSV에 거래 기록이 전혀 없는 종목 = CSV 추적 이전 보유 → 별도 표시
        if key not in csv_balances:
            if xls_qty_r > 0:
                pre_csv.append((key, xls_qty_r))
            else:
                ok_count += 1  # XLS=0, CSV=0 → 일치
            continue

        csv_qty = round(csv_balances[key], 6)

        if abs(xls_qty_r - csv_qty) < 0.001:
            ok_count += 1
        else:
            errors.append((key, xls_qty_r, csv_qty))

    if errors:
        print("불일치 목록 (파서 버그 또는 데이터 누락):")
        for (broker, account, ticker), xls_qty, csv_qty in errors:
            diff = csv_qty - xls_qty
            sign = "+" if diff > 0 else ""
            print(f"  ❌ [{broker} {account}] {ticker}: "
                  f"XLS={xls_qty:.4g}주  CSV계산={csv_qty:.4g}주  "
                  f"차이={sign}{diff:.4g}")
        print()

    if pre_csv:
        print(f"[참고] CSV 추적 이전 보유 종목 ({len(pre_csv)}개) — 매수 파일 없어서 검증 불가:")
        for (broker, account, ticker), xls_qty in pre_csv:
            print(f"  ⚠️  [{broker} {account}] {ticker}: XLS={xls_qty:.4g}주")
        print()

    total = ok_count + len(errors)
    if errors:
        print(f"결과: {len(errors)}개 불일치 / {total}개 검증됨  (추적불가: {len(pre_csv)}개)")
    else:
        print(f"✅ 모든 종목 잔고 일치 ({ok_count}개 검증됨)  (추적불가: {len(pre_csv)}개)")

    return len(errors) == 0


def main():
    broker_filter = None
    if "--broker" in sys.argv:
        idx = sys.argv.index("--broker")
        if idx + 1 < len(sys.argv):
            broker_filter = sys.argv[idx + 1]

    ok = verify_all(broker_filter)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
