---
name: parse-toss
description: 토스증권 거래내역서 PDF 파일을 파싱하여 종합거래내역 CSV로 변환하는 스킬. 사용자가 토스증권 거래내역 파싱, PDF 파일 변환, 토스증권 계좌 데이터 정리, 종합거래내역 갱신을 요청할 때 이 스킬을 사용하라. "/parse-toss"로도 트리거된다.
---

# 토스증권 거래내역 파서

토스증권에서 발급한 거래내역서 PDF 파일을 읽어 종합거래내역 CSV로 변환한다.
**PDF 특이사항**: PDF 파싱 시 중간 CSV를 PDF 옆에 저장한다. 이후 실행 시 CSV가 있으면 PDF 파싱을 건너뛰고 CSV를 바로 읽는다.

## 워크플로우

```
resource/토스증권/{계좌번호}/{연도}/*.pdf
  → scripts/parse_toss.py
  → (중간 CSV: resource/토스증권/{계좌번호}/{연도}/*.csv)
  → output/종합거래내역.csv
```

## 실행 방법

프로젝트 루트에서 실행. 반드시 `.venv` 가상환경을 활성화하라.

```bash
source .venv/bin/activate

# resource 전체 스캔 (PDF 또는 중간 CSV 자동 감지)
python .claude/skills/parse-toss/scripts/parse_toss.py resource/토스증권/

# 특정 계좌/연도 폴더
python .claude/skills/parse-toss/scripts/parse_toss.py resource/토스증권/159-01-510195/2026/

# 단일 PDF 파일
python .claude/skills/parse-toss/scripts/parse_toss.py resource/토스증권/159-01-510195/2026/토스증권_159-01-510195_260222-260324_종합.pdf

# 연도별 폴더 정리 (연도 폴더 없이 계좌 폴더에 바로 있는 파일 정리)
python .claude/skills/parse-toss/scripts/parse_toss.py --organize resource/토스증권/
```

## 입력 파일

- **파일 형식**: PDF 거래내역서
- **파일명 포맷**: `토스증권_{계좌번호}_{YYMMDD-YYMMDD}_종합.pdf`
- **위치**: `resource/토스증권/{계좌번호}/{연도}/`

PDF 구조:
- Pages 1-N: 원화 거래내역 (이체입금, 환전 등 — 모두 제외됨)
- Pages N+1-M: 달러 거래내역 (구매/판매/배당 — 추출 대상)
- 거래 본문행 + 달러 금액 보조행이 쌍으로 구성

## 중간 CSV

PDF 파싱 시 같은 폴더에 `.csv` 파일을 자동 저장한다:
```
토스증권_159-01-510195_260222-260324_종합.csv  ← 자동 생성
토스증권_159-01-510195_260222-260324_종합.pdf
```

- 포맷: 종합거래내역과 동일한 12개 컬럼
- 사람이 검토·편집 가능 (Excel로 열 수 있음)
- CSV가 있으면 다음 실행 시 PDF 재파싱 건너뜀
- CSV 편집 후 재파싱: `python parse_toss.py resource/토스증권/{경로}/파일.csv`

## 출력 파일

- **위치**: `output/종합거래내역.csv`
- **12개 컬럼**: 거래일자, 유형, 종목코드, 수량, 단가, 금액, 환율, 금액KRW, 통화, 증권사, 계좌번호, 비고
- `금액`: USD 거래대금, `단가`: USD 단가 (보조행에서 추출)
- `금액KRW`: KRW 환산 거래대금 (PDF 본문행의 거래대금)
- `환율`: PDF 본문행의 환율 (거래 시점 실제 환율)
- `통화`: USD (해외주식 전용 계좌)
- 날짜 오름차순 정렬

## 병합 전략

기존 `output/종합거래내역.csv`에 병합 시 **날짜 범위 교체** 방식을 사용한다:
- 처리 파일의 날짜 범위 내 기존 토스증권 레코드를 삭제 후 새 레코드로 교체
- DEDUP_KEYS 기반 중복 제거 대신 이 방식으로 동일 가격 분할 체결 거래도 정확히 보존

## 필터링 규칙

| 거래구분 | 유형 | 포함 여부 |
|---------|------|---------|
| 구매 | 매수 | ✅ |
| 판매 | 매도 | ✅ |
| 외화증권배당금입금 | 배당 | ✅ |
| 이체입금(토스증권) | - | ❌ 제외 |
| 이체입금(KEB하나은행) | - | ❌ 제외 |
| 환전원화출금/입금 | - | ❌ 제외 |
| 환전외화출금/입금 | - | ❌ 제외 |
| 외화이자입금/세금출금 | - | ❌ 제외 |
| 배당세출금 | - | ❌ 제외 |

## 종목 매핑 (ISIN → 티커)

토스증권은 ISIN 코드로 종목을 식별한다. 새 종목 거래 시 `parse_toss.py`의 `ISIN_TO_TICKER`에 추가하라.

| ISIN | 티커 | 종목명 |
|------|------|--------|
| US46436E7186 | SGOV | 아이셰어즈 초단기 미국 국고채 ETF |
| AU0000185993 | IREN | 아이렌 (IREN Limited) |

**ISIN 위치**: 종목명 안 (`아이렌(AU0000185993)`) 또는 보조행 첫 토큰 (`(US46436E7186)`)

## 새 종목 추가 시

1. `parse_toss.py` → `ISIN_TO_TICKER`에 추가
2. 중간 CSV 재생성 필요: `rm -f resource/토스증권/.../파일.csv` 후 재실행
3. `web/index.html` → `SAMPLE_PRICES`에 티커 추가
4. `tests/test_portfolio.js` → 계좌 스냅샷 테스트 추가 (해당 시)

## 지원 계좌

| 계좌번호 | 통화 |
|---------|------|
| 159-01-510195 | USD |
