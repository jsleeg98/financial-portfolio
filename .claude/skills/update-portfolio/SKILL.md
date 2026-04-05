---
name: update-portfolio
description: NH나무증권·메리츠증권·토스증권·키움증권·빗썸 새 거래내역 파일 추가 후 CSV 재생성, 종목 매핑 확인, 테스트 검증, 스냅샷 업데이트, Google Sheets 업로드, 커밋/푸시까지 전체 워크플로우를 자동화하는 스킬. 사용자가 새 거래내역 추가, 계좌 업데이트, 파싱 후 검증, 포트폴리오 데이터 갱신을 요청할 때 이 스킬을 사용하라. "/update-portfolio"로도 트리거된다.
---

# 포트폴리오 데이터 업데이트 워크플로우

새 거래내역 파일이 추가되거나 기존 데이터를 갱신할 때 실행하는 표준 절차.
이 스킬은 순서대로 실행하되, 각 단계의 결과를 확인하고 이슈가 있으면 즉시 해결한다.

## 지원 증권사

| 증권사 | 파서 스크립트 | 리소스 경로 | 파일 형식 |
|--------|-------------|-----------|---------|
| NH나무증권 | `.claude/skills/parse-namu/scripts/parse_namu.py` | `resource/NH나무증권/` | XLS (HTML, EUC-KR) |
| 메리츠증권 | `.claude/skills/parse-meritz/scripts/parse_meritz.py` | `resource/메리츠증권/` | XLS (OLE2) |
| 토스증권 | `.claude/skills/parse-toss/scripts/parse_toss.py` | `resource/토스증권/` | PDF |
| 키움증권 | `.claude/skills/parse-kiwoom/scripts/parse_kiwoom.py` | `resource/키움증권/` | XLS (HTML, UTF-8) |
| 빗썸 | `.claude/skills/parse-bithumb/scripts/parse_bithumb.py` | `resource/빗썸/` | XLSX |

## 전제 조건 확인

```bash
# .venv가 없으면 먼저 생성
python3 -m venv .venv && source .venv/bin/activate && pip install pandas beautifulsoup4 xlrd gspread google-auth
```

## Step 1: XLS 파일 배치 확인

사용자가 추가한 XLS 파일이 올바른 위치(연도 폴더)에 있는지 확인한다.

```
resource/NH나무증권/{계좌번호}/{연도}/NH나무증권_{계좌번호}_{YYMMDD-YYMMDD}_종합.xls
resource/메리츠증권/{계좌번호}/{연도}/메리츠증권_{계좌번호}_{YYMMDD-YYMMDD}_종합.xls
```

연도 폴더 미분류 파일은 `--organize`로 자동 정리:
```bash
source .venv/bin/activate
python .claude/skills/parse-namu/scripts/parse_namu.py --organize resource/NH나무증권/{계좌번호}/
python .claude/skills/parse-meritz/scripts/parse_meritz.py --organize resource/메리츠증권/
```

## Step 2: CSV 전체 재생성

기존 CSV를 삭제하고 **모든 증권사를 순서대로** 파싱한다.
**절대로 기존 CSV에 덮어쓰거나 병합하지 마라** — 중복 누적의 원인이 된다.

```bash
rm -f output/종합거래내역.csv
source .venv/bin/activate

# 증권사별 파싱 (순서 중요: 첫 번째 파서가 CSV 생성, 이후는 병합)
python .claude/skills/parse-namu/scripts/parse_namu.py resource/NH나무증권/
python .claude/skills/parse-meritz/scripts/parse_meritz.py resource/메리츠증권/
python .claude/skills/parse-toss/scripts/parse_toss.py resource/토스증권/
python .claude/skills/parse-kiwoom/scripts/parse_kiwoom.py resource/키움증권/
python .claude/skills/parse-bithumb/scripts/parse_bithumb.py resource/빗썸/
```

파싱 완료 후 총 건수와 증권사·계좌별 건수를 확인하라.

**토스증권 특이사항**: PDF 파싱 시 중간 CSV를 `resource/토스증권/{계좌번호}/{연도}/`에 자동 저장한다. 다음 실행부터는 중간 CSV를 바로 읽으므로 PDF 재파싱 없이 빠르게 처리된다.

## Step 3: 종목 매핑 확인

파싱 결과 CSV에서 종목코드 컬럼을 검사한다. 아래 패턴이 보이면 매핑이 누락된 것이다:

- **ISIN 형태** (`US1725731079`, `AU0000185993` 등): `ISIN_TO_TICKER` 누락 (parse_namu.py)
- **한국어 종목명** (`써클 인터넷 그룹` 등): `ISIN_TO_TICKER` 누락 (parse_namu.py)
- **영문 긴 이름** (`ISHARES 0 TO 3 MNTH TREASURY BND ETF` 등): `STOCK_NAME_TO_TICKER` 누락 (parse_namu.py)
- **거래소 suffix** (`NEWSTOCK.NY` 등): `CODE_TO_TICKER` 누락 (parse_meritz.py)

```bash
# 종목코드 목록 확인 (비정상적으로 긴 값 있으면 매핑 필요)
python3 -c "
import csv
codes = set()
with open('output/종합거래내역.csv', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        if row['종목코드']:
            codes.add(row['종목코드'])
for c in sorted(codes):
    print(c)
"
```

매핑 누락 발견 시:
1. 해당 파서 스크립트의 매핑 딕셔너리에 추가
2. Step 2로 돌아가 CSV 재생성

## Step 4: 테스트 실행

```bash
node tests/test_portfolio.js
```

### 실패 유형별 해결

**테스트 15 실패 (중복 거래)**
- 원인: CSV 재생성이 아닌 병합으로 인한 중복 누적
- 해결: `rm -f output/종합거래내역.csv` 후 Step 2 재실행

**테스트 16 실패 (음수 잔고)**
- 원인: 파싱 오류로 매도가 매수보다 먼저 처리됨
- 해결: 해당 종목 거래내역을 날짜순으로 검토하여 파싱 이슈 파악

**테스트 17-19 실패 (스냅샷 불일치)**
- 원인 A: 새 거래 추가로 정상적으로 보유수량이 바뀐 경우 → 기대값 업데이트 필요
- 원인 B: 중복 버그로 수량이 N배로 급증한 경우 → 테스트 15도 동시에 실패하므로 먼저 해결

스냅샷 기대값 업데이트 시 나무증권 앱에서 실제 보유수량을 확인하여 일치시켜라.

## Step 5: 새 종목 발견 시 추가 작업

테스트는 통과했지만 대시보드에서 현재가를 알 수 없는 종목이 있으면:

- `web/index.html`의 `SAMPLE_PRICES`에 해당 티커와 임시 현재가 추가
- 이후 "시세" 버튼으로 실시간 업데이트 가능

## Step 6: Google Sheets 업로드

CSV를 Google Sheets에 업로드한다. 탭 구조:
- `transactions` : 전체 합산 (대시보드가 이 탭을 읽음)
- `{증권사}-{계좌번호}` : 계좌별 거래내역 (예: `NH나무증권-202-01-292788`)

```bash
source .venv/bin/activate
python scripts/upload_to_sheets.py
```

업로드 후 각 탭의 건수가 올바른지 확인하라.

## Step 7: 커밋 및 푸시

변경된 파일을 확인하고 논리적 단위로 커밋한다.

커밋 순서 예시:
1. 파서 스크립트 변경 (종목 매핑 추가): `feat: NEWSTOCK 종목 티커 매핑 추가`
2. `test_portfolio.js` 변경 (스냅샷 업데이트): `test: 계좌별 보유수량 스냅샷 업데이트`
3. `web/index.html` 변경 (SAMPLE_PRICES): `feat: NEWSTOCK 샘플 현재가 추가`

커밋 후 즉시 push하라.

## 체크리스트 요약

- [ ] 파일 올바른 위치(연도 폴더)에 배치
- [ ] 기존 CSV 삭제 후 전체 재생성 (NH나무증권 → 메리츠증권 → 토스증권 → 키움증권 순)
- [ ] 종목코드 컬럼에 ISIN/한국명/거래소코드 없음 확인
- [ ] 19개 테스트 모두 통과
- [ ] 새 종목 있으면 SAMPLE_PRICES 업데이트
- [ ] Google Sheets 업로드 및 탭별 건수 확인
- [ ] 변경사항 커밋 및 푸시
