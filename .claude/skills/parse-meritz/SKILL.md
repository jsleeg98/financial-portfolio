# 메리츠증권 거래내역 파서

메리츠증권에서 다운로드한 종합거래내역 .xls 파일을 읽어서 종합거래내역 CSV로 변환한다.

## 워크플로우

```
resource/메리츠증권/{계좌번호}/{연도}/*.xls → scripts/parse_meritz.py → output/종합거래내역.csv
```

## 실행 방법

프로젝트 루트에서 실행. 반드시 `.venv` 가상환경을 사용하라.

```bash
# venv 생성 및 의존성 설치 (최초 1회)
python3 -m venv .venv && source .venv/bin/activate && pip install pandas xlrd

# 스크립트 실행 (항상 .venv 활성화 후 실행)
source .venv/bin/activate

# resource 전체 스캔
python .claude/skills/parse-meritz/scripts/parse_meritz.py resource/

# 특정 계좌/연도 폴더만 파싱
python .claude/skills/parse-meritz/scripts/parse_meritz.py resource/메리츠증권/3066-6156-01/2026/

# 단일 파일 파싱
python .claude/skills/parse-meritz/scripts/parse_meritz.py resource/메리츠증권/3066-6156-01/2026/메리츠증권_3066-6156-01_260101-260328_종합.xls

# 새 파일 추가 후 연도별 폴더 정리 (파일이 계좌번호 폴더 바로 아래 있을 때)
python .claude/skills/parse-meritz/scripts/parse_meritz.py --organize resource/메리츠증권/
```

## 입력 파일

### 종합거래내역 파일
- 파일명 포맷: `메리츠증권_{계좌번호}_{YYMMDD-YYMMDD}_종합.xls`
- 형식: OLE2 Microsoft Excel (진짜 .xls 바이너리, EUC-KR 인코딩)
- 구조: 2행 헤더 + 짝수/홀수 행 쌍으로 거래 1건씩
- 시트명: `거래내역조회`
- 위치: `resource/메리츠증권/{계좌번호}/{연도}/`

상세 스펙은 `references/file_spec.md` 참조.

## 출력 파일

- 위치: `output/종합거래내역.csv`
- 12개 컬럼: 거래일자, 유형, 종목코드, 수량, 단가, 금액, 환율, 금액KRW, 통화, 증권사, 계좌번호, 비고
- 통화: USD (해외주식만 지원)
- 날짜 오름차순 정렬, 중복 자동 제거

### 환율/금액KRW 제한

메리츠증권 파일에는 거래별 환율 정보가 없다. 따라서 `환율=0.0`, `금액KRW=0.0` 으로 저장된다.
대시보드에서 평가금액 계산 시 `currentFX`(실시간 또는 샘플 환율)를 사용하므로 표시에는 영향 없다.
단, 역사적 취득단가 KRW 정밀도는 낮아질 수 있다.

## 필터링 규칙

### 포함 거래 유형

| 거래적요 | 유형 | 설명 |
|---------|------|------|
| 해외주식매수대금 | 매수 | 실제 매수금액이 담긴 결제 행 |
| 해외주식매도대금 | 매도 | 실제 매도금액이 담긴 결제 행 |
| 배당금 | 배당 | USD 배당 수령 |
| 종목교체입고 | 입고 | 거래소 이동 입고 (예: SGOV.AX → SGOV.NY) |
| 종목교체출고 | 출고 | 거래소 이동 출고 |

> **주의**: `해외주식매수`/`해외주식매도` 행은 금액=0 이므로 제외하고
> `해외주식매수대금`/`해외주식매도대금` 행(금액 있음)을 사용한다.

### 제외 거래 유형

환전외화매수(자체), 해외주식매수, 해외주식매도, 배당세금출금(원화),
전자계좌입금, 오픈뱅킹출금/입금, 그 외 모든 미분류 유형

## 종목코드 → 티커 매핑

메리츠증권은 종목코드에 거래소 suffix를 붙인다 (SGOV.AX, IREN.OQ 등).
suffix 제거 후 `CODE_TO_TICKER` 딕셔너리로 조회.

| 종목코드 (suffix 제거 후) | 티커 |
|--------------------------|------|
| IREN | IREN |
| SGOV | SGOV |
| CRCL | CRCL |
| INFQ | INFQ |

새 종목 추가 시 `parse_meritz.py` → `CODE_TO_TICKER` 딕셔너리에 추가하라.

## 새 거래내역 추가 체크리스트

1. XLS 파일을 `resource/메리츠증권/` 아래에 배치
2. `--organize` 로 연도 폴더 정리:
   ```bash
   python .claude/skills/parse-meritz/scripts/parse_meritz.py --organize resource/메리츠증권/
   ```
3. 기존 CSV 삭제 후 전체 재생성:
   ```bash
   rm -f output/종합거래내역.csv
   python .claude/skills/parse-namu/scripts/parse_namu.py resource/NH나무증권/
   python .claude/skills/parse-meritz/scripts/parse_meritz.py resource/메리츠증권/
   ```
4. 테스트 실행: `node tests/test_portfolio.js`
5. 새 종목 있으면 `CODE_TO_TICKER`에 추가 후 재생성
