---
name: parse-bithumb
description: 빗썸 거래내역 .xlsx 파일을 파싱하여 종합거래내역 CSV로 변환하는 스킬. 사용자가 빗썸 거래내역 파싱, 가상자산 거래내역 변환, 빗썸 계좌 데이터 정리, 종합거래내역 갱신을 요청할 때 이 스킬을 사용하라. "/parse-bithumb"로도 트리거된다.
---

# 빗썸 거래내역 파서

빗썸에서 다운로드한 `.xlsx` 형식의 기간별 거래내역을 `output/종합거래내역.csv`에 병합한다.

## 파일 형식

- **형식**: `.xlsx` (openpyxl)
- **위치**: `resource/빗썸/`
- **파일명 패턴**: `빗썸_{YYMMDD}-{YYMMDD}_종합.xlsx`
- **시트**: `거래내역`
- **컬럼**: 거래일시, 자산(한국어), 거래구분, 거래수량(`qty TICKER`), 체결가격, 거래금액, 수수료, 정산금액

## 거래 유형 처리

| 거래구분 | 처리 방식 | 비고 |
|---------|---------|------|
| 매수 | 매수 | 단가·금액 그대로 |
| 매도 | 매도 | 단가·금액 그대로 |
| 가상자산 이벤트 입금 | 매수 (단가=0, 금액=0) | 수량만 추적 |
| 스테이킹(자유형) | 매수 (단가=0, 금액=0) | 스테이킹 리워드 |
| 외부입금 | 매수 (단가=0, 금액=0) | 외부 지갑 이전 |
| 이벤트 혜택 지급·쿠폰입금·리워드 | 매수 (단가=0, 금액=0) | 무료 수령 |
| 원화 입금·출금·예치금 이용료 | 스킵 | KRW 거래 |
| 외부출금 (비KRW) | 매도 (단가=0, 금액=0) | 외부 지갑 이전 → 잔고 차감 |
| 외부출금 (KRW) | 스킵 | KRW 출금, 포트폴리오 무관 |

무료 수령 항목은 `비고` 컬럼에 원래 거래구분이 기록된다.

## 실행 방법

```bash
source .venv/bin/activate
# openpyxl 필요 (없으면 자동 안내)
pip install openpyxl  # 최초 1회만

python .claude/skills/parse-bithumb/scripts/parse_bithumb.py resource/빗썸/
```

## 전체 CSV 재생성 순서 (parse-bithumb 포함)

```bash
rm -f output/종합거래내역.csv
source .venv/bin/activate
python .claude/skills/parse-namu/scripts/parse_namu.py resource/NH나무증권/
python .claude/skills/parse-meritz/scripts/parse_meritz.py resource/메리츠증권/
python .claude/skills/parse-toss/scripts/parse_toss.py resource/토스증권/
python .claude/skills/parse-kiwoom/scripts/parse_kiwoom.py resource/키움증권/
python .claude/skills/parse-bithumb/scripts/parse_bithumb.py resource/빗썸/
```

## 새 종목 추가 체크리스트

빗썸에서 새 가상자산이 등장하면:

- [ ] `web/data/asset_categories.json` → `가상자산` 배열에 티커 추가
- [ ] `web/index.html` → `SAMPLE_PRICES`에 임시 현재가 추가 (선택)
- [ ] `tests/test_portfolio.js` → 빗썸 스냅샷 테스트 갱신 (필요 시)

## 잔고=0 종목 자동 제외

파싱 후 **최종 순잔고 > 0인 종목만 CSV에 포함**된다.

- **scalp trade** (당일 매수→매도, 순잔고≈0): 제외
- **기초잔고 매도** (데이터 시작 이전 보유분 전량 매도): 순잔고 < 0이므로 제외
- **외부출금 후 잔고=0**: 외부출금을 매도로 처리 후 순잔고=0이면 제외

이유: portfolio.js의 같은날 처리 순서(getDayOrder)는 초기 잔고 기준으로 매도를 앞에 배치한다.
데이터 시작 이전 보유분이나 scalp trade가 포함되면 phantom 잔고가 발생할 수 있으므로,
잔고가 없는 종목은 애초에 CSV에 넣지 않는 것이 가장 안전하다.

> **데이터 공백 주의**: 최신 파일이 없으면 외부입금된 종목이 잔고>0으로 남을 수 있다.
> 예: XPL이 외부입금 후 나중에 외부출금됐으나 해당 분기 파일이 없으면 XPL 잔고가 남아 보인다.
> 해결: 해당 분기 xlsx 파일 추가 후 CSV 재생성.

## 참고 사항

- 증권사/계좌번호 컬럼: 모두 `빗썸`으로 고정 (계좌번호 없음)
- 모든 거래는 KRW 기준 (환율=0.0)
- 타 증권사와 동일한 DEDUP_KEYS로 중복 제거 적용
