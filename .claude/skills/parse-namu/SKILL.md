---
name: parse-namu
description: NH나무증권 거래내역(해외주식+국내주식) .xls 파일을 파싱하여 종합거래내역 CSV로 변환하는 스킬. 사용자가 NH나무증권 거래내역 파싱, .xls 파일 변환, 종합거래내역 생성, 해외주식/국내주식 거래 데이터 정리, 증권사 거래내역 CSV 변환을 요청할 때 반드시 이 스킬을 사용하라. "/parse-namu"로도 트리거된다.
---

# NH나무증권 거래내역 파서

NH나무증권에서 다운로드한 해외주식거래내역 및 종합거래내역 .xls 파일을 읽어서 종합거래내역 CSV로 변환한다.

## 워크플로우

```
resource/NH나무증권/{연도}/*.xls → scripts/parse_namu.py → output/종합거래내역.csv
```

## 실행 방법

프로젝트 루트에서 실행. 반드시 `.venv` 가상환경을 사용하라.

```bash
# venv 생성 및 의존성 설치 (최초 1회)
python3 -m venv .venv && source .venv/bin/activate && pip install pandas beautifulsoup4

# 스크립트 실행 (항상 .venv 활성화 후 실행)
source .venv/bin/activate

# resource 전체 스캔 (해외주식 + 종합 파일 자동 감지)
python .claude/skills/parse-namu/scripts/parse_namu.py resource/

# 특정 계좌/연도 폴더 내 전체 파싱
python .claude/skills/parse-namu/scripts/parse_namu.py resource/NH나무증권/202-01-292788/2025/

# 단일 파일 파싱
python .claude/skills/parse-namu/scripts/parse_namu.py resource/NH나무증권/202-01-292788/2024/NH나무증권_202-01-292788_240101-240331_종합.xls

# 새 계좌 파일 정리 (파일명 정규화 + 연도별 폴더 이동)
python .claude/skills/parse-namu/scripts/parse_namu.py --organize resource/NH나무증권/202-02-292788/
```

**주의:** `pip install`을 시스템 Python에 직접 실행하면 `externally-managed-environment` 오류가 발생한다. 반드시 `.venv`를 활성화한 후 실행하라.

## 입력 파일

두 종류의 .xls 파일을 지원한다. 파일명에 "종합"이 포함되면 종합 파일로 인식한다.

### 해외주식거래내역 파일
- 파일명 포맷: `NH나무증권_{계좌번호}_{YYMMDD-YYMMDD}.xls`
- 구조: 메인행(15 td) + 서브행(13 td)이 교차 반복
- 추출 대상: 해외주식 매수/매도/배당/입금

### 종합거래내역 파일
- 파일명 포맷: `NH나무증권_{계좌번호}_{YYMMDD-YYMMDD}_종합.xls`
- 구조: 메인행(13 td) + 서브행(8 td)이 교차 반복
- 추출 대상: 국내주식 매수/매도 (코스피/코스닥) + 해외주식 매수/매도/배당 (외화증권)

공통:
- 위치: `resource/NH나무증권/{연도}/`
- 실제 포맷: EUC-KR 인코딩된 HTML 테이블 (확장자만 .xls)

상세 스펙은 `references/file_spec.md` 참조.

## 출력 파일

- 위치: `output/종합거래내역.csv`
- 12개 컬럼: 거래일자, 유형, 종목코드, 수량, 단가, 금액, 환율, 금액KRW, 통화, 증권사, 계좌번호, 비고
- 통화: USD(해외) 또는 KRW(국내)
- 날짜 오름차순 정렬, 중복 자동 제거

## 필터링 규칙

### 해외주식 (USD)
포함: 매수, 매도, 입금(이체 제외), 배당
제외: 환전, 출금, 출고(액면분할 등), 계좌 간 이체, CMA NOTE PAYABLE, 국내주식, 공모주입고

### 국내주식 (KRW)
포함: 코스피/코스닥 매수, 매도, 감자출고
제외: 그 외 모든 거래(환전, 이체, 입출금 등)

## 자동 살균 (항상 수행)

종합거래내역 파일 파싱 시 **거래내역메모 열의 내용을 항상 자동으로 제거**한다. 헤더는 유지하고 본문만 비운다. 별도 옵션 없이 파싱할 때마다 실행된다.

## 종목 매핑 (해외주식)

해외주식거래내역 파일은 `STOCK_NAME_TO_TICKER`(영문명→티커), 종합거래내역 파일은 `ISIN_TO_TICKER`(ISIN→티커)를 사용한다.
새 종목이 추가되면 두 딕셔너리 모두에 추가한다.

| 종목명 (해외주식파일) | 한국명 (종합파일) | ISIN | 티커 |
|----------------------|-----------------|------|------|
| APPLE INC | 애플 | US0378331005 | AAPL |
| MICROSOFT CP | 마이크로소프트 | US5949181045 | MSFT |
| NVIDIA CORP | 엔비디아 | US67066G1040 | NVDA |
| IONQ INC ORD | 아이온큐 | US46222L1089 | IONQ |
| IREN LIMITED ORD | 아이렌 | AU0000185993 | IREN |
| ISHARES 0 TO 3 MNTH TREASURY BND ETF | 아이셰어즈 0-3개월 미국 국채 ETF | US46436E7186 | SGOV |
| META PLTFORM ORD | 메타 | US30303M1027 | META |
| RCKT LAB CRP ORD | 로켓 랩 | US7731211089 | RKLB |
| STATE STREET SPDR PORTFL S&P 500 ETF | SPDR S&P500 포트폴리오 ETF | US78464A8541 | SPYM |
| VANGUARD S&P 500 ETF | 뱅가드 S&P500 ETF | US9229083632 | VOO |
| DELTA AIR LIN | 델타 에어라인스 | US2473617023 | DAL |
| — | 스타벅스 | US8552441094 | SBUX |
| — | 프로셰어즈 QQQ 3배 ETF | US74347X8314 | TQQQ |
