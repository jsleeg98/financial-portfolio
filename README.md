# financial-portfolio

NH나무증권·메리츠증권·토스증권·키움증권 거래내역 기반 개인 포트폴리오 추적 대시보드.

거래내역 파일을 증권사별 파서로 CSV로 변환하고, 브라우저에서 바로 열리는 단일 HTML 파일로 포트폴리오 현황을 시각화한다.

**라이브 대시보드**: https://jsleeg98.github.io/financial-portfolio/

## 주요 기능

- **포트폴리오 현황**: 보유 종목별 수량·평균단가·평가손익 테이블 + 종목 비중 도넛 차트
  - **종목별 / 유형별 토글**: 지수·성장주·현금·가상자산 등 자산유형별 비중으로 전환 가능
- **계좌 추세**: 월별 포트폴리오 평가금액 추이 (계좌별 필터)
- **월별 손익**: 과거 월별 종가 기반 월간 미실현 손익 계산
- **월별 실현손익**: 매도·배당 기반 월간 실현손익 + 누적 실현손익
- **수익률 비교**: 현금흐름 반영 TWR 기반 누적 수익률 vs 코스피·S&P500·NASDAQ100
- **거래내역**: 전체 거래 내역 테이블 + 증권사-계좌번호별 필터
- **실시간 시세**: 데이터 로드 시 자동 조회 + 수동 버튼 (Yahoo Finance, CORS 프록시 3개 병렬)
- **과거 시세 캐시**: `web/data/price_history.json`에 월별 종가를 저장, 재조회 없이 재사용

## 프로젝트 구조

```
financial-portfolio/
├── web/
│   ├── index.html              # 포트폴리오 대시보드 (단일 파일)
│   ├── portfolio.js            # 계산 엔진 (computePortfolio, computeCashFlowBenchmarkTWR)
│   └── data/                   # 정적 데이터 파일 (GitHub Pages 배포 포함)
│       ├── sp500_daily.csv
│       ├── nasdaq100_daily.csv
│       ├── kospi_daily.csv
│       ├── usdkrw_daily.csv
│       ├── price_history.json  # 과거 월별 종가 캐시
│       ├── asset_categories.json  # 자산유형 분류 (지수/성장주/현금/가상자산)
│       └── portfolio_config.json  # 대시보드 설정 (제외 종목 등)
├── .github/workflows/
│   └── deploy-pages.yml        # main 브랜치 push 시 web/ → GitHub Pages 자동 배포
├── scripts/
│   ├── fetch_benchmark.py      # S&P500/NASDAQ100/KOSPI/USD-KRW 일별 종가 다운로드
│   ├── fetch_historical_prices.py  # 보유 종목 과거 월별 종가 조회 및 캐시
│   ├── upload_to_sheets.py     # 종합거래내역 CSV → Google Sheets 업로드
│   └── verify_portfolio.py     # 증권앱 현황 vs 계산값 오차 검증
├── tests/
│   ├── test_portfolio.js       # 포트폴리오 계산 엔진 테스트 (25개)
│   └── fixtures/
│       ├── 종합거래내역.csv     # 고정 기준 데이터셋 (갱신 금지)
│       └── app_status.txt      # 증권앱 현황 기준값 (gitignore, verify_portfolio.py 입력)
├── output/                     # 생성된 파일 (gitignore)
│   ├── 종합거래내역.csv
│   ├── price_history.json      # 로컬 과거 시세 캐시
│   ├── known_symbols.json      # KRW 종목명 → Yahoo Finance 심볼 (수동 관리)
│   └── symbol_cache.json       # Yahoo Finance 검색 결과 캐시
├── resource/                   # 원본 파일 (gitignore)
│   ├── NH나무증권/{계좌번호}/{연도}/
│   ├── 메리츠증권/{계좌번호}/{연도}/
│   ├── 토스증권/{계좌번호}/{연도}/
│   └── 키움증권/{계좌번호}/
├── credentials/                # Google 서비스 계정 키 (gitignore)
│   └── service_account.json
└── .claude/skills/
    ├── parse-namu/             # NH나무증권 XLS → CSV 파서 스킬
    ├── parse-meritz/           # 메리츠증권 XLS → CSV 파서 스킬
    ├── parse-toss/             # 토스증권 PDF → CSV 파서 스킬
    ├── parse-kiwoom/           # 키움증권 XLS → CSV 파서 스킬
    └── update-portfolio/       # 거래내역 갱신 자동화 스킬 (파싱→검증→Sheets 업로드)
```

## 시작하기

### 1. 의존성 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pandas beautifulsoup4 xlrd yfinance gspread google-auth requests pdfplumber
```

### 2. 거래내역 파싱

XLS/PDF 파일을 증권사별 폴더에 배치한 뒤 파서를 실행한다.

**NH나무증권** (`resource/NH나무증권/{계좌번호}/{연도}/`):
```bash
source .venv/bin/activate
python .claude/skills/parse-namu/scripts/parse_namu.py resource/NH나무증권/
```

**메리츠증권** (`resource/메리츠증권/{계좌번호}/{연도}/`):
```bash
python .claude/skills/parse-meritz/scripts/parse_meritz.py resource/메리츠증권/
```

**토스증권** (`resource/토스증권/{계좌번호}/{연도}/`):
```bash
python .claude/skills/parse-toss/scripts/parse_toss.py resource/토스증권/
```

**키움증권** (`resource/키움증권/{계좌번호}/`):
```bash
python .claude/skills/parse-kiwoom/scripts/parse_kiwoom.py resource/키움증권/
```

- 정규화되지 않은 파일명은 `--organize` 옵션으로 연도별 폴더 자동 정리
- 모든 파서가 `output/종합거래내역.csv`에 병합 출력

### 3. 벤치마크 데이터 다운로드

```bash
python scripts/fetch_benchmark.py
```

출력: `web/data/sp500_daily.csv`, `web/data/nasdaq100_daily.csv`, `web/data/kospi_daily.csv`, `web/data/usdkrw_daily.csv`

### 4. 과거 시세 갱신 (선택)

```bash
python scripts/fetch_historical_prices.py
```

- 월별 손익 차트에 사용할 과거 종가를 yfinance로 조회
- KRW 종목은 `output/known_symbols.json`에서 Yahoo Finance 심볼을 읽음
- 결과를 `web/data/price_history.json`에 저장 → 커밋하면 GitHub Pages에서 활용 가능

### 5. 대시보드 열기

```bash
# Linux
xdg-open web/index.html
# macOS
open web/index.html
```

또는 파일 탐색기에서 `web/index.html`을 더블클릭해 브라우저로 열어도 된다.

- CSV 파일 업로드 또는 Google Sheet URL 입력으로 데이터 로드 → 시세 자동 조회
- **시세** 버튼으로 현재가 수동 업데이트

### 6. Google Sheets 업로드 (선택)

`.env`에 `SPREADSHEET_ID`를 설정하고 서비스 계정 키를 `credentials/service_account.json`에 배치:

```bash
python scripts/upload_to_sheets.py
```

탭 구조:
- `transactions`: 전체 합산 (대시보드에서 Google Sheet URL로 로드 시 사용)
- `{증권사}-{계좌번호}`: 계좌별 거래내역

## 거래내역 갱신 워크플로우

새 파일 추가 후 전체 갱신:

```bash
rm -f output/종합거래내역.csv
source .venv/bin/activate
python .claude/skills/parse-namu/scripts/parse_namu.py resource/NH나무증권/
python .claude/skills/parse-meritz/scripts/parse_meritz.py resource/메리츠증권/
python .claude/skills/parse-toss/scripts/parse_toss.py resource/토스증권/
python .claude/skills/parse-kiwoom/scripts/parse_kiwoom.py resource/키움증권/
node tests/test_portfolio.js
python scripts/upload_to_sheets.py
python scripts/fetch_historical_prices.py
```

또는 `/update-portfolio` 스킬로 위 과정을 자동화.

## 포트폴리오 검증

증권앱 현황을 `tests/fixtures/app_status.txt`에 기록해두면 계산값과 자동 비교:

```bash
python scripts/verify_portfolio.py
```

- 202-07 계좌(순수 USD)를 기준으로 USD/KRW 환율을 자동 역산
- 평가금액 오차 ±1.5% 이내이면 정상 판정
- `--fx 1500`으로 환율 수동 지정 가능

## 테스트

```bash
node tests/test_portfolio.js
```

| 계층 | 범위 | 목적 |
|------|------|------|
| 단위 (1-8) | 인라인 픽스처 | 계산 로직 회귀 방지 |
| 고정 데이터 (9-14) | `tests/fixtures/종합거래내역.csv` | 실제 데이터 기반 검증 |
| 라이브 CSV (15-19) | `output/종합거래내역.csv` | CSV 무결성 + 계좌별 보유수량 스냅샷 |
| 현금잔고 단위 (20-25) | 인라인 픽스처 | 현금잔고 SET/합산/weight 계산 로직 회귀 방지 |

## 지원 계좌

| 증권사 | 파서 |
|--------|------|
| NH나무증권 | parse-namu |
| 메리츠증권 | parse-meritz |
| 토스증권 | parse-toss |
| 키움증권 | parse-kiwoom |

## 지원 종목 (해외)

| 티커 | 종목명 | 유형 |
|------|--------|------|
| NVDA | 엔비디아 | 성장주 |
| IREN | 아이렌 | 성장주 |
| RKLB | 로켓 랩 | 성장주 |
| CRCL | 써클 인터넷 그룹 | 성장주 |
| INFQ | 인플렉션 | 성장주 |
| IONQ | 아이온큐 | 성장주 |
| SGOV | 아이셰어즈 0-3개월 미국 국채 ETF | 현금 |
| VOO | 뱅가드 S&P500 ETF | 지수 |
| SPYM | SPDR S&P500 포트폴리오 ETF | 지수 |
| TQQQ | 프로셰어즈 QQQ 3배 ETF | 지수 |
| AAPL | 애플 | - |
| MSFT | 마이크로소프트 | - |
| GOOGL | 알파벳 Class A | - |
| META | 메타 | - |
| DAL | 델타 에어라인스 | - |
| SBUX | 스타벅스 | - |
