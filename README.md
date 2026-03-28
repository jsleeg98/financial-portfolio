# financial-portfolio

NH나무증권 거래내역 기반 개인 포트폴리오 추적 대시보드.

거래내역 XLS 파일을 파싱해 CSV로 변환하고, 브라우저에서 바로 열리는 단일 HTML 파일로 포트폴리오 현황을 시각화한다.

## 주요 기능

- **포트폴리오 현황**: 보유 종목별 수량·평균단가·평가손익 테이블
- **계좌 추세**: 월별 포트폴리오 평가금액 추이 (계좌별 필터)
- **수익률 비교**: TWR 기반 누적 수익률 vs 코스피·S&P500·NASDAQ100
- **거래내역**: 전체 거래 내역 테이블 (종목·유형 필터)
- **실시간 시세**: Yahoo Finance API 연동 (CORS 프록시 경유)

## 프로젝트 구조

```
financial-portfolio/
├── web/
│   ├── index.html          # 포트폴리오 대시보드 (단일 파일)
│   └── portfolio.js        # 계산 엔진 (computePortfolio)
├── scripts/
│   └── fetch_benchmark.py  # S&P500/NASDAQ100/KOSPI/USD-KRW 일별 종가 다운로드
├── tests/
│   ├── test_portfolio.js   # 포트폴리오 계산 엔진 테스트 (19개)
│   └── fixtures/
│       └── 종합거래내역.csv  # 고정 기준 데이터셋 (갱신 금지)
├── output/                 # 생성된 CSV (gitignore)
│   ├── 종합거래내역.csv
│   ├── sp500_daily.csv
│   ├── nasdaq100_daily.csv
│   ├── kospi_daily.csv
│   └── usdkrw_daily.csv
├── resource/               # 원본 XLS 파일 (gitignore)
│   └── NH나무증권/
│       └── {계좌번호}/
│           └── {연도}/
│               └── NH나무증권_{계좌번호}_{YYMMDD}-{YYMMDD}_종합.xls
└── .claude/skills/
    ├── parse-namu/         # XLS → CSV 파서 스킬
    └── update-portfolio/   # 거래내역 갱신 자동화 스킬
```

## 시작하기

### 1. 의존성 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pandas beautifulsoup4 yfinance
```

### 2. 거래내역 파싱

NH나무증권에서 다운로드한 종합거래내역 XLS 파일을 `resource/NH나무증권/{계좌번호}/{연도}/`에 배치한 뒤:

```bash
source .venv/bin/activate
python .claude/skills/parse-namu/scripts/parse_namu.py resource/
```

- 정규화되지 않은 파일명(`종합거래내역(상세)_이름_YYYY.MM.DD_...xls`)은 자동으로 정규화 후 연도별 폴더로 이동
- 출력: `output/종합거래내역.csv`

### 3. 벤치마크 데이터 다운로드

```bash
python scripts/fetch_benchmark.py
```

- 출력: `output/sp500_daily.csv`, `output/nasdaq100_daily.csv`, `output/kospi_daily.csv`, `output/usdkrw_daily.csv`
- 기존 CSV가 있으면 마지막 날짜 이후분만 추가

### 4. 대시보드 열기

```bash
open web/index.html   # macOS
# 또는 브라우저에서 직접 파일 열기
```

- CSV 파일 업로드 또는 Google Sheets URL 입력으로 데이터 로드
- **시세** 버튼으로 현재가 업데이트 (Yahoo Finance)

## 거래내역 갱신 워크플로우

새 XLS 파일 추가 후 전체 갱신:

```bash
rm -f output/종합거래내역.csv
source .venv/bin/activate
python .claude/skills/parse-namu/scripts/parse_namu.py resource/
node tests/test_portfolio.js
```

또는 `/update-portfolio` 스킬로 위 과정을 자동화.

## 테스트

```bash
node tests/test_portfolio.js
```

| 계층 | 범위 | 목적 |
|------|------|------|
| 단위 (1-8) | 인라인 픽스처 | 계산 로직 회귀 방지 |
| 고정 데이터 (9-14) | `tests/fixtures/종합거래내역.csv` | 실제 데이터 기반 검증 |
| 라이브 CSV (15-19) | `output/종합거래내역.csv` | CSV 무결성 + 계좌별 보유수량 스냅샷 |

## 지원 계좌

| 증권사 | 계좌번호 |
|--------|---------|
| NH나무증권 | 202-01-****** |
| NH나무증권 | 202-02-****** |
| NH나무증권 | 202-07-****** |
| NH나무증권 | 209-02-****** |

## 지원 종목 (해외)

| 티커 | 종목명 |
|------|--------|
| AAPL | 애플 |
| MSFT | 마이크로소프트 |
| NVDA | 엔비디아 |
| GOOGL | 알파벳 Class A |
| META | 메타 |
| DAL | 델타 에어라인스 |
| IONQ | 아이온큐 |
| IREN | 아이렌 |
| RKLB | 로켓 랩 |
| CRCL | 써클 인터넷 그룹 |
| SBUX | 스타벅스 |
| VOO | 뱅가드 S&P500 ETF |
| SGOV | 아이셰어즈 0-3개월 미국 국채 ETF |
| SPYM | SPDR S&P500 포트폴리오 ETF |
| TQQQ | 프로셰어즈 QQQ 3배 ETF |
