## Git Workflow

### 커밋 규칙
- 하나의 작업 단위(기능 구현, 버그 수정, 리팩토링 등)가 완료되면 반드시 커밋하라.
- 여러 작업을 하나의 커밋에 섞지 마라. 논리적 단위별로 분리하여 커밋하라.
- 커밋 메시지는 **Conventional Commits** 형식을 따르며, **한국어**로 작성하라.

### 커밋 메시지 형식
```
<type>: <한국어 요약>

<본문 (선택, 변경 이유나 상세 내용)>
```

**type 종류:**
- `feat`: 새로운 기능 추가
- `fix`: 버그 수정
- `refactor`: 리팩토링 (기능 변경 없음)
- `docs`: 문서 수정
- `style`: 코드 스타일 변경 (포맷팅, 세미콜론 등)
- `test`: 테스트 추가/수정
- `chore`: 빌드, 설정, 의존성 등 기타 작업

**예시:**
```
feat: 계좌별 pill 선택 UI 및 per-account 추세 차트 추가
```

### 브랜치 전략

- **main**: 완성된 기능만 존재하는 안정 브랜치. 직접 커밋하지 마라.
- **feat/{기능명}**: 새 기능 작업 브랜치. 기능 완료 후 PR을 열어 main에 merge한다.

브랜치 워크플로우:
```bash
# 새 기능 시작
git checkout main && git pull
git checkout -b feat/{기능명}

# 작업 중 커밋 (논리적 단위별)
git add ... && git commit -m "feat: ..."
git push -u origin feat/{기능명}

# 기능 완료 후 PR 생성 (merge는 사용자가 직접 확인 후 수행)
gh pr create --title "{기능명}" --body "## Summary\n- ...\n\n## Test plan\n- [ ] ..."
```

### 커밋 및 푸시 절차
1. 작업 완료 후 `git add`로 변경 파일을 스테이징하라.
2. 위 형식에 맞는 커밋 메시지를 작성하여 `git commit`하라.
3. 커밋 직후 현재 브랜치에 `git push`하라.
4. push 실패 시 원인을 보고하고, 강제 push는 절대 하지 마라.

### 주의사항
- `git push --force` 또는 `git push -f`는 사용하지 마라.
- `main` 브랜치에 직접 커밋하지 마라. 반드시 feature 브랜치에서 작업 후 merge하라.
- 커밋 전 `git diff --staged`로 변경 내용을 확인하라.
- `.env`, 시크릿 키, 인증 정보가 포함된 파일은 절대 커밋하지 마라.

---

## Issue 관리

작업 중 발견한 버그, 데이터 불일치, 파서 오류는 GitHub Issue로 기록하라.

```bash
# 이슈 생성
gh issue create --title "제목" --body "본문" --label "bug"

# 이슈 닫기 (해결 커밋 SHA 포함)
gh issue close 번호 --comment "해결 내용 + 커밋 SHA"
```

이슈 본문에는 **문제 / 원인 / 해결** 섹션을 포함하고, 커밋 메시지에 `Fixes #이슈번호`를 포함하라.

---

## 배포

### GitHub Pages 자동 배포

`main` 브랜치에 push 되면 `.github/workflows/deploy-pages.yml`이 `web/` 폴더를 GitHub Pages에 자동 배포한다.

- **라이브 URL**: https://jsleeg98.github.io/financial-portfolio/
- 배포 범위: `web/` 디렉토리만 (거래내역·원본 XLS 미포함)
- 벤치마크 CSV는 `web/data/`에 위치해야 Pages에서 로드 가능

### 벤치마크 CSV 갱신

```bash
source .venv/bin/activate
python scripts/fetch_benchmark.py
```

출력 경로: `web/data/` (sp500_daily.csv, nasdaq100_daily.csv, kospi_daily.csv, usdkrw_daily.csv)
기존 파일이 있으면 마지막 날짜 이후분만 추가된다.

---

## 데이터 관리

### 지원 증권사 및 파서

| 증권사 | 파서 스크립트 | 파일 형식 | 리소스 경로 |
|--------|-------------|---------|-----------|
| NH나무증권 | `.claude/skills/parse-namu/scripts/parse_namu.py` | HTML-based XLS (EUC-KR) | `resource/NH나무증권/{계좌번호}/{연도}/` |
| 메리츠증권 | `.claude/skills/parse-meritz/scripts/parse_meritz.py` | OLE2 Excel XLS (EUC-KR) | `resource/메리츠증권/{계좌번호}/{연도}/` |
| 토스증권 | `.claude/skills/parse-toss/scripts/parse_toss.py` | PDF 거래내역 | `resource/토스증권/{계좌번호}/{연도}/` |

### 새 거래 내역 추가 워크플로우

`/update-portfolio` 스킬을 사용하면 아래 절차를 자동화한다.

1. XLS 파일을 증권사별 리소스 경로에 배치
2. 연도 폴더 미분류 파일 정리 (필요 시):
   ```bash
   source .venv/bin/activate
   python .claude/skills/parse-namu/scripts/parse_namu.py --organize resource/NH나무증권/{계좌번호}/
   python .claude/skills/parse-meritz/scripts/parse_meritz.py --organize resource/메리츠증권/
   ```
3. 기존 CSV 삭제 후 전체 재생성 (순서 중요 — 첫 번째 파서가 CSV 생성, 이후는 병합):
   ```bash
   rm -f output/종합거래내역.csv
   source .venv/bin/activate
   python .claude/skills/parse-namu/scripts/parse_namu.py resource/NH나무증권/
   python .claude/skills/parse-meritz/scripts/parse_meritz.py resource/메리츠증권/
   ```
4. 테스트 실행: `node tests/test_portfolio.js`
5. 테스트 결과에 따른 후속 조치 (아래 체크리스트 참조)
6. Google Sheets 업로드:
   ```bash
   python scripts/upload_to_sheets.py
   ```
7. 커밋 및 푸시

### Google Sheets 업로드

`scripts/upload_to_sheets.py` 실행 조건:
- `.env`에 `SPREADSHEET_ID` 설정
- `credentials/service_account.json` 존재 (gitignore)

탭 구조:
- `transactions`: 전체 합산 (대시보드 Google Sheet URL 로드 시 이 탭을 읽음)
- `{증권사}-{계좌번호}`: 계좌별 거래내역 (예: `NH나무증권-202-01-292788`, `메리츠증권-3066-6156-01`)

### 포트폴리오 검증

증권앱 현황을 `tests/fixtures/app_status.txt`(gitignore)에 기록해두고 계산값과 비교:

```bash
source .venv/bin/activate
python scripts/verify_portfolio.py          # 202-07 계좌 기준 환율 자동 역산
python scripts/verify_portfolio.py --fx 1506  # 환율 수동 지정
```

`app_status.txt` 형식:
```
[계좌번호]
매입금액: 35,466,541원
평가금액: 39,104,596원
평가손익: 3,638,055원
수익률: 10.25%

[YYYY-MM-DD 기준 현재가]
IREN: 34.89$
SGOV: 100.65$
```

판정 기준: 평가금액 오차 ±1.5% 이내 ✅ (매입금액 오차는 취득환율 차이로 별도 허용)

### 새 종목 추가 체크리스트

새 종목이 거래내역에 등장하면 반드시 아래를 모두 업데이트하라.

**NH나무증권 신규 종목:**
- [ ] `parse_namu.py` → `ISIN_TO_TICKER` (ISIN → 티커, 종합파일용)
- [ ] `parse_namu.py` → `STOCK_NAME_TO_TICKER` (영문명 → 티커, 해외주식파일용)

**메리츠증권 신규 종목:**
- [ ] `parse_meritz.py` → `CODE_TO_TICKER` (거래소코드 suffix 제거 후 → 티커, 예: `NEWT.NY` → `NEWT`)

**공통:**
- [ ] `web/index.html` → `SAMPLE_PRICES` (기본 현재가)
- [ ] `tests/test_portfolio.js` → 스냅샷 기대값 (보유 수량 포함 시)

### 새 계좌 추가 체크리스트

**NH나무증권:**
- [ ] XLS 파일 정규화: `python parse_namu.py --organize resource/NH나무증권/{계좌번호}/`
- [ ] 전체 CSV 재생성 및 테스트
- [ ] `tests/test_portfolio.js` → 새 계좌 스냅샷 테스트 추가 (라이브 CSV 테스트 17번 이후)
- [ ] `web/index.html` → `SAMPLE_PRICES`에 새 종목 추가 (해당 시)

**메리츠증권:**
- [ ] XLS 파일 정규화: `python parse_meritz.py --organize resource/메리츠증권/`
- [ ] 전체 CSV 재생성 및 테스트
- [ ] `tests/test_portfolio.js` → 새 계좌 스냅샷 테스트 추가
- [ ] `web/index.html` → `SAMPLE_PRICES`에 새 종목 추가 (해당 시)

### 알려진 허용 오차

증권앱 수치와 HTML 대시보드 수치 사이에는 아래 수준의 차이가 발생할 수 있으며, 이는 정상이다.

| 항목 | 원인 | 허용 범위 |
|------|------|-----------|
| 매입금액 | Yahoo Finance 현물환율 vs 증권사 TTB 환율 차이 | 0.1–3% |
| 매입금액 (메리츠증권) | CSV에 환율 미저장 → 현재 FX로 역산 | 최대 ~3% |
| 평가금액 | 대시보드 환율(SAMPLE_FX 또는 "시세" 조회값) 차이 | FX 1원 당 ~0.07% |
| 손익률 | 위 두 오차의 복합 효과 | ±1.5% 수준 |

"시세" 버튼으로 실시간 환율을 조회하면 평가금액 오차가 0.01% 이내로 줄어든다.

### 알려진 버그 패턴

아래 패턴이 발생하면 즉시 대응하라.

**중복 거래 누적 (테스트 15번 실패)**
- 증상: 같은 행이 N배로 나타남, 보유수량이 N배로 급증
- 원인: 파서 재실행 시 기존 CSV와 merge 후 `drop_duplicates` 미동작
- 해결: `rm -f output/종합거래내역.csv` 후 전체 재생성. 재발 방지: DEDUP_KEYS 기반 중복 제거 로직이 `main()` 내 sort 직후에 있는지 확인.

**종목코드가 ISIN 또는 한국명으로 저장 (NH나무증권)**
- 증상: CSV에서 종목코드 컬럼에 `US1725731079` 또는 `써클 인터넷 그룹` 같은 값이 보임
- 원인: `ISIN_TO_TICKER`에 해당 ISIN이 없음
- 해결: XLS 파일에서 ISIN 확인 후 딕셔너리에 추가, CSV 재생성

**종목코드가 거래소 suffix 포함 (메리츠증권)**
- 증상: CSV에서 종목코드 컬럼에 `NEWT.NY` 같은 값이 보임
- 원인: `CODE_TO_TICKER`에 해당 코드(suffix 제거 후)가 없음
- 해결: `parse_meritz.py`의 `CODE_TO_TICKER`에 추가, CSV 재생성

**음수 잔고 (테스트 16번 실패)**
- 증상: 특정 종목 보유수량이 음수
- 원인: 거래 시간순 정렬 오류, 또는 파싱 누락으로 매도가 먼저 처리됨
- 해결: 해당 종목 거래내역을 날짜순으로 검토하여 원인 파악

**시세 조회 후 "시세 조회 중..." 영구 잔류**
- 증상: 시세 버튼 클릭 또는 자동 시세 조회 후 현재가 컬럼에 로딩 텍스트가 계속 표시됨
- 원인: `isPriceFetching = false`가 `renderAll()` 호출 *이후*에 실행되어, `renderAll` 내부 렌더링 시 여전히 `true` 상태
- 해결: `isPriceFetching = false`를 `renderAll()` 호출 직전(finally 블록 맨 앞)으로 이동. `renderAll`은 fetch 성공/실패 무관하게 항상 실행되어야 함

**ChartDataLabels CDN 로드 실패 시 전체 버튼 먹통**
- 증상: 시세 버튼을 포함한 모든 버튼이 반응 없음
- 원인: `Chart.register(ChartDataLabels)`가 스크립트 최상위에 있어 CDN 실패 시 ReferenceError → 이하 이벤트 리스너 등록 코드 미실행
- 해결: `typeof ChartDataLabels !== 'undefined'` 가드로 보호

**NH나무증권 계좌 필터링 시 현금(USD) 비중 비정상 급등**
- 증상: NH나무증권 계좌만 선택 시 현금(USD)이 포트폴리오의 70%+ 점유
- 원인: `portfolio.js`에서 매도 시 cashUSD를 누적하지만 매수 시 차감하지 않음. NH나무증권은 `현금잔고 USD` 스냅샷을 CSV에 기록하지 않으므로, 스냅샷 override가 발동하지 않아 2020년 이후 전체 매도 누적액이 그대로 cashUSD로 잔류
- 해결: `portfolio.js`의 스냅샷 override 로직에 `else { cashUSD = 0; }` 추가. NH나무증권은 환전→즉시매수 패턴이므로 스냅샷 없으면 USD 현금은 0으로 처리
- 주의: 새 증권사 파서 추가 시, USD 현금잔고를 파서에서 스냅샷(`유형: 현금잔고, 통화: USD`)으로 출력하지 않으면 동일 증상 재발. 반드시 파서에서 `현금잔고 USD` 레코드를 생성하거나, 환전→즉시매수 패턴임을 확인 후 0 처리가 맞는지 검토하라.

---

## 테스트

### 포트폴리오 계산 엔진 테스트

```bash
node tests/test_portfolio.js
```

- 외부 의존성 없음 (Node.js 18+ 내장 `node:test` 사용)
- 총 25개 테스트

#### 테스트 계층

| 계층 | 데이터 소스 | 목적 |
|------|-------------|------|
| 단위 (1-8) | 인라인 픽스처 | `computePortfolio` 계산 로직 회귀 방지 |
| 고정 데이터 (9-14) | `tests/fixtures/종합거래내역.csv` | 실제 데이터 기반 로직 검증 (불변) |
| 라이브 CSV (15-19) | `output/종합거래내역.csv` | CSV 무결성 + 계좌별 보유수량 스냅샷 |
| 현금잔고 단위 (20-25) | 인라인 픽스처 | 현금잔고 SET/합산/weight 계산 로직 회귀 방지 |

### 테스트 실행 시점

- `computePortfolio` 또는 `web/portfolio.js` 로직 변경 시
- 파서 스크립트 변경 또는 CSV 재생성 후
- **새 계좌/종목 추가 시** (라이브 CSV 테스트로 데이터 오염 조기 감지)

### 라이브 CSV 테스트 관리

- **중복 없음 (15번)**: 동일 행이 2번 이상이면 즉시 실패 → CSV 재생성으로 해결
- **음수 잔고 없음 (16번)**: 파싱 오류나 데이터 손상 감지
- **계좌별 보유수량 스냅샷 (17-19번)**: 새 거래 추가로 수량이 바뀌면 기대값을 함께 갱신하라. 중복 버그 발생 시 수량이 N배로 급증하여 실패한다.

새 계좌가 추가되면 해당 계좌의 스냅샷 테스트를 `tests/test_portfolio.js`에 추가하라.

### 고정 데이터셋

`tests/fixtures/종합거래내역.csv`는 갱신하지 않는다. 고정 기준 데이터셋으로 유지하라.
