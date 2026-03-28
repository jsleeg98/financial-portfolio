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

# 기능 완료 후 PR 생성
gh pr create --title "{기능명}" --body "## Summary\n- ...\n\n## Test plan\n- [ ] ..."

# PR merge (사용자가 직접 또는 승인 후)
gh pr merge {번호} --merge
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

## 데이터 관리

### 새 거래 내역 추가 워크플로우

`/update-portfolio` 스킬을 사용하면 아래 절차를 자동화한다.

1. XLS 파일을 `resource/NH나무증권/{계좌번호}/{연도}/`에 배치
2. 기존 CSV 삭제 후 전체 재생성:
   ```bash
   rm -f output/종합거래내역.csv
   source .venv/bin/activate
   python .claude/skills/parse-namu/scripts/parse_namu.py resource/
   ```
3. 테스트 실행: `node tests/test_portfolio.js`
4. 테스트 결과에 따른 후속 조치 (아래 체크리스트 참조)
5. 커밋 및 푸시

### 새 종목 추가 체크리스트

새 종목이 거래내역에 등장하면 반드시 아래를 모두 업데이트하라. 하나라도 빠지면 종목코드가 ISIN 또는 한국명으로 저장된다.

- [ ] `parse_namu.py` → `ISIN_TO_TICKER` (ISIN → 티커, 종합파일용)
- [ ] `parse_namu.py` → `STOCK_NAME_TO_TICKER` (영문명 → 티커, 해외주식파일용)
- [ ] `web/index.html` → `SAMPLE_PRICES` (기본 현재가)
- [ ] `tests/test_portfolio.js` → 스냅샷 기대값 (보유 수량 포함 시)

### 새 계좌 추가 체크리스트

- [ ] XLS 파일 정규화: `python parse_namu.py --organize resource/NH나무증권/{계좌번호}/`
- [ ] 전체 CSV 재생성 및 테스트
- [ ] `tests/test_portfolio.js` → 새 계좌 스냅샷 테스트 추가 (라이브 CSV 테스트 17번 이후)
- [ ] `web/index.html` → `SAMPLE_PRICES`에 새 종목 추가 (해당 시)

### 알려진 허용 오차

나무증권 앱 수치와 HTML 대시보드 수치 사이에는 아래 수준의 차이가 발생할 수 있으며, 이는 정상이다.

| 항목 | 원인 | 허용 범위 |
|------|------|-----------|
| 매입금액 | Yahoo Finance 현물환율 vs 나무증권 TTB 환율 차이 | 0.1–0.7% |
| 평가금액 | 대시보드에서 사용하는 환율(SAMPLE_FX 또는 "시세" 조회값) 차이 | FX 1원 당 ~0.07% |
| 손익률 | 위 두 오차의 복합 효과 | ±1% 수준 |

"시세" 버튼으로 실시간 환율을 조회하면 평가금액 오차가 0.01% 이내로 줄어든다.

### 알려진 버그 패턴

아래 패턴이 발생하면 즉시 대응하라.

**중복 거래 누적 (테스트 15번 실패)**
- 증상: 같은 행이 N배로 나타남, 보유수량이 N배로 급증
- 원인: `parse_namu.py` 재실행 시 기존 CSV와 merge 후 `drop_duplicates` 미동작
- 해결: `rm -f output/종합거래내역.csv` 후 전체 재생성. 재발 방지: DEDUP_KEYS 기반 중복 제거 로직이 `main()` 내 sort 직후에 있는지 확인.

**종목코드가 ISIN 또는 한국명으로 저장**
- 증상: CSV에서 종목코드 컬럼에 `US1725731079` 또는 `써클 인터넷 그룹` 같은 값이 보임
- 원인: `ISIN_TO_TICKER`에 해당 ISIN이 없음
- 해결: XLS 파일에서 ISIN 확인 후 딕셔너리에 추가, CSV 재생성

**음수 잔고 (테스트 16번 실패)**
- 증상: 특정 종목 보유수량이 음수
- 원인: 거래 시간순 정렬 오류, 또는 파싱 누락으로 매도가 먼저 처리됨
- 해결: 해당 종목 거래내역을 날짜순으로 검토하여 원인 파악

---

## 테스트

### 포트폴리오 계산 엔진 테스트

```bash
node tests/test_portfolio.js
```

- 외부 의존성 없음 (Node.js 18+ 내장 `node:test` 사용)
- 총 19개 테스트

#### 테스트 계층

| 계층 | 데이터 소스 | 목적 |
|------|-------------|------|
| 단위 (1-8) | 인라인 픽스처 | `computePortfolio` 계산 로직 회귀 방지 |
| 고정 데이터 (9-14) | `tests/fixtures/종합거래내역.csv` | 실제 데이터 기반 로직 검증 (불변) |
| 라이브 CSV (15-19) | `output/종합거래내역.csv` | CSV 무결성 + 계좌별 보유수량 스냅샷 |

### 테스트 실행 시점

- `computePortfolio` 또는 `web/portfolio.js` 로직 변경 시
- `parse_namu.py` 변경 또는 CSV 재생성 후
- **새 계좌/종목 추가 시** (라이브 CSV 테스트로 데이터 오염 조기 감지)

### 라이브 CSV 테스트 관리

- **중복 없음 (15번)**: 동일 행이 2번 이상이면 즉시 실패 → CSV 재생성으로 해결
- **음수 잔고 없음 (16번)**: 파싱 오류나 데이터 손상 감지
- **계좌별 보유수량 스냅샷 (17-19번)**: 새 거래 추가로 수량이 바뀌면 기대값을 함께 갱신하라. 중복 버그 발생 시 수량이 N배로 급증하여 실패한다.

새 계좌가 추가되면 해당 계좌의 스냅샷 테스트를 `tests/test_portfolio.js`에 추가하라.

### 고정 데이터셋

`tests/fixtures/종합거래내역.csv`는 갱신하지 않는다. 고정 기준 데이터셋으로 유지하라.
