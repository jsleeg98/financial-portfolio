---
name: parse-kiwoom
description: 키움증권 거래내역 .xls 파일을 파싱하여 종합거래내역 CSV로 변환하는 스킬. 사용자가 키움증권 거래내역 파싱, .xls 파일 변환, 키움증권 계좌 데이터 정리, 종합거래내역 갱신을 요청할 때 이 스킬을 사용하라. "/parse-kiwoom"로도 트리거된다.
---

# 키움증권 거래내역 파서

키움증권에서 다운로드한 종합거래내역 .xls 파일을 읽어서 종합거래내역 CSV로 변환한다.

## 워크플로우

```
resource/키움증권/{계좌번호}/*.xls → scripts/parse_kiwoom.py → output/종합거래내역.csv
```

## 실행 방법

프로젝트 루트에서 실행. 반드시 `.venv` 가상환경을 사용하라.

```bash
# venv 생성 및 의존성 설치 (최초 1회)
python3 -m venv .venv && source .venv/bin/activate && pip install pandas beautifulsoup4

# 스크립트 실행 (항상 .venv 활성화 후 실행)
source .venv/bin/activate

# resource 전체 스캔
python .claude/skills/parse-kiwoom/scripts/parse_kiwoom.py resource/키움증권/

# 특정 계좌 폴더 파싱
python .claude/skills/parse-kiwoom/scripts/parse_kiwoom.py resource/키움증권/6265-5774/

# 단일 파일 파싱
python .claude/skills/parse-kiwoom/scripts/parse_kiwoom.py resource/키움증권/6265-5774/키움증권_6265-5774_250101-251231_종합.xls
```

## 입력 파일

- 파일명 포맷: `키움증권_{계좌번호}_{YYMMDD}-{YYMMDD}_종합.xls`
- 위치: `resource/키움증권/{계좌번호}/`
- 실제 포맷: UTF-8 인코딩된 HTML 테이블 (확장자만 .xls)
- 구조: 단일 행 구조 (NH나무증권과 달리 메인/서브 행 분리 없음), 22개 컬럼

### 컬럼 구조

| 인덱스 | 컬럼명 | 설명 |
|--------|--------|------|
| 0 | 거래일자 | YYYY.MM.DD 형식 |
| 1 | 종목명 | 한국어 종목/ETF명 |
| 2 | 거래수량 | 매수/매도 수량 |
| 3 | 거래금액 | 거래 금액 (KRW) |
| 7 | 예수금 | 거래 후 현금잔고 |
| 11 | 거래소 | KRX 등 |
| 12 | 거래구분 | 장내매수, 장내매도, 배당금입금 등 |
| 13 | 거래단가 | 단가 |

## 출력 파일

- 위치: `output/종합거래내역.csv`
- 12개 컬럼: 거래일자, 유형, 종목코드, 수량, 단가, 금액, 환율, 금액KRW, 통화, 증권사, 계좌번호, 비고
- 통화: KRW (국내 전용 계좌)
- 날짜 오름차순 정렬, 중복 자동 제거

## 필터링 규칙

### 포함 거래구분

| 거래구분 | 출력 유형 |
|---------|---------|
| 장내매수 | 매수 |
| 장내매도 | 매도 |
| KOSDAQ매수 | 매수 |
| KOSDAQ매도 | 매도 |
| 배당금입금 | 배당 |
| 수익분배금입금 | 배당 |

### 제외 거래구분

이체입금, 대체입금, 대체출금, ISA가입인증입금, ISA이벤트입금, 예탁금이용료(이자)입금 등

## 현금잔고

파일당 마지막 행의 `예수금` 값을 현금잔고(KRW) 스냅샷으로 기록한다.
재파싱 시 기존 현금잔고 행을 교체한다.

## 종목코드

키움증권은 국내주식/ETF 전용 계좌이므로 종목코드에 한국어 종목명을 그대로 사용한다.
(예: `TIGER미국S&P500`, `KODEX미국나스닥100`, `RISE미국S&P500`)
별도의 티커 매핑 딕셔너리는 없다.
