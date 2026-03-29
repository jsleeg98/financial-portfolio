/**
 * 포트폴리오 계산 엔진 테스트
 * 실행: node tests/test_portfolio.js
 *
 * Node.js 18+ 내장 test runner 사용 (외부 의존성 없음)
 */
'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { computePortfolio } = require('../web/portfolio.js');

// ── 헬퍼 ────────────────────────────────────────────────────────

/** CSV 파싱 (output/종합거래내역.csv 포맷) */
function parseCSV(text) {
  const lines = text.replace(/^\uFEFF/, '').trim().split('\n');
  const headers = lines[0].split(',');
  return lines.slice(1).map(line => {
    const cols = line.split(',');
    const row = {};
    headers.forEach((h, i) => { row[h.trim()] = cols[i]?.trim() ?? ''; });
    return {
      거래일자: row['거래일자'],
      유형: row['유형'],
      종목코드: row['종목코드'] || null,
      수량: parseFloat(row['수량']) || 0,
      단가: parseFloat(row['단가']) || 0,
      금액: parseFloat(row['금액']) || 0,
      환율: parseFloat(row['환율']) || 0,
      금액KRW: parseFloat(row['금액KRW']) || 0,
      통화: row['통화'] || '',
      증권사: row['증권사'],
      계좌번호: row['계좌번호'],
      비고: row['비고'] || '',
    };
  });
}

/** 거래 객체 생성 단축 함수 */
function tx(거래일자, 유형, 종목코드, 수량, 단가, { 금액 = 0, 환율 = 0, 금액KRW = 0, 통화 = 'USD' } = {}) {
  return { 거래일자, 유형, 종목코드, 수량, 단가, 금액: 금액 || 단가 * 수량, 환율, 금액KRW, 통화, 증권사: 'TEST', 계좌번호: '000', 비고: '' };
}

/** avgCost 반올림 비교 (소수점 4자리) */
function assertAvgCost(actual, expected, ticker) {
  assert.ok(
    Math.abs(actual - expected) < 0.001,
    `${ticker} avgCost: 예상 ${expected}, 실제 ${actual.toFixed(4)}`
  );
}

// ── 실제 CSV 로드 ───────────────────────────────────────────────

const CSV_PATH = path.join(__dirname, 'fixtures/종합거래내역.csv');
const realTxns = fs.existsSync(CSV_PATH) ? parseCSV(fs.readFileSync(CSV_PATH, 'utf8')) : null;

function requireRealData(t) {
  if (!realTxns) {
    t.skip('output/종합거래내역.csv 없음');
    return false;
  }
  return true;
}

// ── 단위 테스트 ─────────────────────────────────────────────────

test('기본 매수: 수량/avgCost 정확성', () => {
  const txns = [
    tx('2024-01-10', '매수', 'AAPL', 5, 100),
    tx('2024-01-15', '매수', 'AAPL', 5, 200),
  ];
  const result = computePortfolio(txns, {}, 1300);
  const h = result.currentHoldings.find(h => h.ticker === 'AAPL');
  assert.ok(h, 'AAPL 보유 종목 존재');
  assert.equal(h.qty, 10);
  assertAvgCost(h.avgCost, 150, 'AAPL'); // (500+1000)/10 = 150
});

test('부분 매도 후 avgCost 유지', () => {
  const txns = [
    tx('2024-01-10', '매수', 'AAPL', 10, 100),
    tx('2024-01-20', '매도', 'AAPL', 4, 120, { 금액: 480 }),
  ];
  const result = computePortfolio(txns, {}, 1300);
  const h = result.currentHoldings.find(h => h.ticker === 'AAPL');
  assert.equal(h.qty, 6);
  assertAvgCost(h.avgCost, 100, 'AAPL'); // 매도 후 avgCost 변화 없음
});

test('전량 매도 후 보유 종목 없음', () => {
  const txns = [
    tx('2024-01-10', '매수', 'AAPL', 5, 100),
    tx('2024-01-20', '매도', 'AAPL', 5, 120, { 금액: 600 }),
  ];
  const result = computePortfolio(txns, {}, 1300);
  const h = result.currentHoldings.find(h => h.ticker === 'AAPL');
  assert.equal(h, undefined, '전량 매도 후 보유 종목 없어야 함');
});

test('액면분할: 출고→입고 시 원가 보존, 수량 교체', () => {
  // 10주 매수 @100 → 총원가 1000
  // 출고 10주 → 수량 0 (원가 보존)
  // 입고 40주 (4:1 분할) → 수량 40, 원가 1000 유지
  // avgCost = 1000/40 = 25
  const txns = [
    tx('2024-01-10', '매수', 'NVDA', 10, 100),
    tx('2024-06-10', '출고', 'NVDA', 10, 0),
    tx('2024-06-10', '입고', 'NVDA', 40, 0),
  ];
  const result = computePortfolio(txns, {}, 1300);
  const h = result.currentHoldings.find(h => h.ticker === 'NVDA');
  assert.ok(h, 'NVDA 보유 종목 존재');
  assert.equal(h.qty, 40);
  assertAvgCost(h.avgCost, 25, 'NVDA'); // 1000 / 40 = 25
});

test('감자출고: 수량 0, 원가 보존 → 감자입고로 수량 교체', () => {
  const txns = [
    tx('2024-01-10', '매수', '삼성전자', 100, 70000, { 통화: 'KRW', 금액: 7000000 }),
    tx('2024-03-01', '감자출고', '삼성전자', 100, 0, { 통화: 'KRW' }),
    tx('2024-03-01', '입고', '삼성전자', 20, 0, { 통화: 'KRW' }), // 5:1 감자
  ];
  const result = computePortfolio(txns, {}, 1300);
  const h = result.currentHoldings.find(h => h.ticker === '삼성전자');
  assert.ok(h, '삼성전자 보유 종목 존재');
  assert.equal(h.qty, 20);
  assertAvgCost(h.avgCost, 350000, '삼성전자'); // 7000000 / 20 = 350000
});

test('같은 날 매수→매도: 당일 매수 후 매도 가능 (restBuys 먼저)', () => {
  // TIGER처럼 같은 날 매수 후 즉시 매도하는 케이스
  const txns = [
    tx('2024-01-10', '매수', 'TIGER', 10, 10000, { 통화: 'KRW', 금액: 100000 }),
    tx('2024-01-10', '매도', 'TIGER', 10, 10100, { 통화: 'KRW', 금액: 101000 }),
  ];
  const result = computePortfolio(txns, {}, 1300);
  const h = result.currentHoldings.find(h => h.ticker === 'TIGER');
  assert.equal(h, undefined, '당일 매수→매도 후 잔고 없어야 함');
});

test('같은 날 기존 보유 매도 → 새 종목 매수: 순서 무관하게 처리', () => {
  // 기존 AAPL 보유, 같은 날 AAPL 매도 + MSFT 매수
  const txns = [
    tx('2024-01-05', '매수', 'AAPL', 5, 200),
    tx('2024-01-10', '매도', 'AAPL', 5, 220, { 금액: 1100 }),
    tx('2024-01-10', '매수', 'MSFT', 3, 400),
  ];
  const result = computePortfolio(txns, {}, 1300);
  const aapl = result.currentHoldings.find(h => h.ticker === 'AAPL');
  const msft = result.currentHoldings.find(h => h.ticker === 'MSFT');
  assert.equal(aapl, undefined, 'AAPL 매도 후 잔고 없어야 함');
  assert.ok(msft, 'MSFT 매수 후 잔고 있어야 함');
  assert.equal(msft.qty, 3);
});

test('음수 잔고 없음: 모든 종목 qty >= 0', () => {
  const txns = [
    tx('2024-01-05', '매수', 'AAPL', 5, 200),
    tx('2024-01-10', '매도', 'AAPL', 3, 220, { 금액: 660 }),
    tx('2024-01-15', '매도', 'AAPL', 2, 230, { 금액: 460 }),
  ];
  const result = computePortfolio(txns, {}, 1300);
  result.currentHoldings.forEach(h => {
    assert.ok(h.qty >= 0, `${h.ticker} qty 음수: ${h.qty}`);
  });
});

// ── 실제 데이터 통합 테스트 ─────────────────────────────────────

test('실제 데이터: 음수 잔고 없음', (t) => {
  if (!requireRealData(t)) return;
  const result = computePortfolio(realTxns, {}, 1450);
  result.currentHoldings.forEach(h => {
    assert.ok(h.qty >= 0, `${h.ticker} qty 음수: ${h.qty}`);
  });
});

test('실제 데이터: NVDA avgCost ≈ 28.8325, qty = 10', (t) => {
  if (!requireRealData(t)) return;
  const result = computePortfolio(realTxns, {}, 1450);
  const h = result.currentHoldings.find(h => h.ticker === 'NVDA');
  assert.ok(h, 'NVDA 보유 종목 존재');
  assert.equal(h.qty, 10, `NVDA qty: 예상 10, 실제 ${h.qty}`);
  assertAvgCost(h.avgCost, 28.8325, 'NVDA');
});

test('실제 데이터: IREN avgCost ≈ 43.51', (t) => {
  if (!requireRealData(t)) return;
  const result = computePortfolio(realTxns, {}, 1450);
  const h = result.currentHoldings.find(h => h.ticker === 'IREN');
  assert.ok(h, 'IREN 보유 종목 존재');
  assertAvgCost(h.avgCost, 43.5083, 'IREN');
});

test('실제 데이터: RKLB avgCost ≈ 41.00', (t) => {
  if (!requireRealData(t)) return;
  const result = computePortfolio(realTxns, {}, 1450);
  const h = result.currentHoldings.find(h => h.ticker === 'RKLB');
  assert.ok(h, 'RKLB 보유 종목 존재');
  assertAvgCost(h.avgCost, 41.00, 'RKLB');
});

test('실제 데이터: NVDA 액면분할 후 fetchPricesFromAPI 보유수량 계산 정확성', (t) => {
  if (!requireRealData(t)) return;
  // fetchPricesFromAPI와 동일한 간이 계산: 출고/입고 포함
  const holdings = {};
  [...realTxns].sort((a, b) => a.거래일자.localeCompare(b.거래일자)).forEach(tx => {
    const t2 = tx.종목코드;
    if (!t2) return;
    if (!holdings[t2]) holdings[t2] = 0;
    if (tx.유형 === '매수' || tx.유형 === '입고') holdings[t2] += tx.수량;
    else if (tx.유형 === '매도' || tx.유형 === '출고' || tx.유형 === '감자출고') holdings[t2] -= tx.수량;
  });
  assert.ok((holdings['NVDA'] || 0) > 0, `NVDA 시세 조회 대상 포함 필요. 현재 holdings: ${holdings['NVDA']}`);
});

test('실제 데이터: 종합 보유 종목 검증 (IREN, RKLB, NVDA 포함)', (t) => {
  if (!requireRealData(t)) return;
  const result = computePortfolio(realTxns, {}, 1450);
  const tickers = result.currentHoldings.map(h => h.ticker);
  ['IREN', 'RKLB', 'NVDA'].forEach(ticker => {
    assert.ok(tickers.includes(ticker), `${ticker} 보유 종목에 없음`);
  });
});

// ── 라이브 CSV 무결성 테스트 ──────────────────────────────────────
// output/종합거래내역.csv (실제 운영 데이터)를 직접 검증한다.
// 파서 버그나 중복 추가로 인한 데이터 오염을 조기에 감지하는 목적.
// 새 계좌/종목이 추가되면 스냅샷 테스트의 기대값을 함께 갱신하라.

const LIVE_CSV_PATH = path.join(__dirname, '../output/종합거래내역.csv');
const liveTxns = fs.existsSync(LIVE_CSV_PATH)
  ? parseCSV(fs.readFileSync(LIVE_CSV_PATH, 'utf8'))
  : null;

function requireLiveData(t) {
  if (!liveTxns) { t.skip('output/종합거래내역.csv 없음'); return false; }
  return true;
}

// parse_namu.py의 DEDUP_KEYS와 동일
const DEDUP_KEYS = ['거래일자', '유형', '종목코드', '수량', '단가', '금액', '통화', '증권사', '계좌번호'];

test('라이브 CSV: 중복 거래 없음', (t) => {
  if (!requireLiveData(t)) return;
  const seen = new Set();
  const dups = [];
  liveTxns.forEach(tx => {
    const key = DEDUP_KEYS.map(k => String(tx[k] ?? '')).join('|');
    if (seen.has(key)) dups.push(key);
    else seen.add(key);
  });
  assert.equal(dups.length, 0,
    `중복 거래 ${dups.length}건 발견 (parse_namu.py 재실행 후 dedup 미적용):\n` +
    dups.slice(0, 3).join('\n'));
});

test('라이브 CSV: 전체 계좌 음수 잔고 없음', (t) => {
  if (!requireLiveData(t)) return;
  const result = computePortfolio(liveTxns, {}, 1450);
  result.currentHoldings.forEach(h => {
    assert.ok(h.qty >= 0, `${h.ticker} qty 음수: ${h.qty}`);
  });
});

// [202-02-292788] 계좌 스냅샷
// 새 거래 추가 시 아래 기대값을 함께 갱신하라.
test('라이브 CSV [202-02]: IREN qty = 61, CRCL qty = 9', (t) => {
  if (!requireLiveData(t)) return;
  const txns02 = liveTxns.filter(tx => tx.계좌번호 === '202-02-292788');
  if (txns02.length === 0) { t.skip('202-02-292788 계좌 데이터 없음'); return; }
  const result = computePortfolio(txns02, {}, 1450);

  result.currentHoldings.forEach(h => {
    assert.ok(h.qty >= 0, `[202-02] ${h.ticker} qty 음수: ${h.qty}`);
  });

  const iren = result.currentHoldings.find(h => h.ticker === 'IREN');
  assert.ok(iren, '[202-02] IREN 보유 종목 존재');
  assert.equal(iren.qty, 61, `[202-02] IREN qty: 예상 61, 실제 ${iren.qty}`);

  const crcl = result.currentHoldings.find(h => h.ticker === 'CRCL');
  assert.ok(crcl, '[202-02] CRCL 보유 종목 존재');
  assert.equal(crcl.qty, 9, `[202-02] CRCL qty: 예상 9, 실제 ${crcl.qty}`);

  const sgov = result.currentHoldings.find(h => h.ticker === 'SGOV');
  assert.equal(sgov, undefined, '[202-02] SGOV 전량 매도 후 잔고 없어야 함');
});

// [202-07-292788] 계좌 스냅샷
// 새 거래 추가 시 아래 기대값을 함께 갱신하라.
test('라이브 CSV [202-07]: IREN qty = 100, RKLB qty = 40', (t) => {
  if (!requireLiveData(t)) return;
  const txns07 = liveTxns.filter(tx => tx.계좌번호 === '202-07-292788');
  if (txns07.length === 0) { t.skip('202-07-292788 계좌 데이터 없음'); return; }
  const result = computePortfolio(txns07, {}, 1450);

  result.currentHoldings.forEach(h => {
    assert.ok(h.qty >= 0, `[202-07] ${h.ticker} qty 음수: ${h.qty}`);
  });

  const iren = result.currentHoldings.find(h => h.ticker === 'IREN');
  assert.ok(iren, '[202-07] IREN 보유 종목 존재');
  assert.equal(iren.qty, 100, `[202-07] IREN qty: 예상 100, 실제 ${iren.qty}`);

  const rklb = result.currentHoldings.find(h => h.ticker === 'RKLB');
  assert.ok(rklb, '[202-07] RKLB 보유 종목 존재');
  assert.equal(rklb.qty, 40, `[202-07] RKLB qty: 예상 40, 실제 ${rklb.qty}`);
});

// [209-02-687627] 계좌 스냅샷
// 새 거래 추가 시 아래 기대값을 함께 갱신하라.
test('라이브 CSV [209-02]: RISE 미국나스닥100 qty = 280', (t) => {
  if (!requireLiveData(t)) return;
  const txns209 = liveTxns.filter(tx => tx.계좌번호 === '209-02-687627');
  if (txns209.length === 0) { t.skip('209-02-687627 계좌 데이터 없음'); return; }
  const result = computePortfolio(txns209, {}, 1450);

  result.currentHoldings.forEach(h => {
    assert.ok(h.qty >= 0, `[209-02] ${h.ticker} qty 음수: ${h.qty}`);
  });

  const rise = result.currentHoldings.find(h => h.ticker === 'RISE 미국나스닥100');
  assert.ok(rise, '[209-02] RISE 미국나스닥100 보유 종목 존재');
  assert.equal(rise.qty, 280, `[209-02] RISE 미국나스닥100 qty: 예상 280, 실제 ${rise.qty}`);

  const sol = result.currentHoldings.find(h => h.ticker === 'SOL 미국배당다우존스');
  assert.equal(sol, undefined, '[209-02] SOL 미국배당다우존스 전량 매도 후 잔고 없어야 함');
});

// ── 현금잔고 단위 테스트 ─────────────────────────────────────────

test('현금잔고 USD: cashUSD가 SET됨', () => {
  const txns = [
    tx('2024-01-10', '매수', 'AAPL', 1, 100, { 금액: 100, 환율: 1300, 금액KRW: 130000, 통화: 'USD' }),
    { 거래일자: '2024-01-10', 유형: '현금잔고', 종목코드: '', 수량: 0, 단가: 0,
      금액: 500, 환율: 1300, 금액KRW: 650000, 통화: 'USD', 증권사: 'TEST', 계좌번호: '000', 비고: '현금잔고' },
  ];
  const result = computePortfolio(txns, {}, 1300);
  const cash = result.currentHoldings.find(h => h.ticker === '현금(USD)');
  assert.ok(cash, '현금(USD) 행 존재');
  assert.ok(Math.abs(cash.qty - 500) < 0.01, `현금(USD) qty: 예상 500, 실제 ${cash.qty}`);
  assert.ok(cash.isCash, 'isCash 플래그가 true');
});

test('현금잔고 KRW: cashKRW가 SET됨', () => {
  const txns = [
    tx('2024-01-10', '매수', 'RISE 미국나스닥100', 10, 1000, { 금액: 10000, 환율: 0, 금액KRW: 10000, 통화: 'KRW' }),
    { 거래일자: '2024-01-10', 유형: '현금잔고', 종목코드: '', 수량: 0, 단가: 0,
      금액: 0, 환율: 0, 금액KRW: 300000, 통화: 'KRW', 증권사: 'TEST', 계좌번호: '001', 비고: '현금잔고' },
  ];
  const result = computePortfolio(txns, {}, 1300);
  const cash = result.currentHoldings.find(h => h.ticker === '현금(KRW)');
  assert.ok(cash, '현금(KRW) 행 존재');
  assert.ok(Math.abs(cash.qty - 300000) < 1, `현금(KRW) qty: 예상 300000, 실제 ${cash.qty}`);
  assert.ok(cash.isCash, 'isCash 플래그가 true');
});

test('현금잔고 USD: 다른 계좌 두 개 합산', () => {
  const txns = [
    { 거래일자: '2024-01-10', 유형: '현금잔고', 종목코드: '', 수량: 0, 단가: 0,
      금액: 1500, 환율: 1300, 금액KRW: 1950000, 통화: 'USD', 증권사: 'BROKER_A', 계좌번호: 'ACC-1', 비고: '현금잔고' },
    { 거래일자: '2024-01-10', 유형: '현금잔고', 종목코드: '', 수량: 0, 단가: 0,
      금액: 200, 환율: 1300, 금액KRW: 260000, 통화: 'USD', 증권사: 'BROKER_B', 계좌번호: 'ACC-2', 비고: '현금잔고' },
  ];
  const result = computePortfolio(txns, {}, 1300);
  const cash = result.currentHoldings.find(h => h.ticker === '현금(USD)');
  assert.ok(cash, '현금(USD) 행 존재');
  assert.ok(Math.abs(cash.qty - 1700) < 0.01, `현금(USD) qty: 예상 1700, 실제 ${cash.qty}`);
});

test('현금잔고: isCash=true 행이 currentHoldings에 포함됨', () => {
  const txns = [
    tx('2024-01-10', '매수', 'AAPL', 5, 100, { 금액: 500, 환율: 1300, 금액KRW: 650000, 통화: 'USD' }),
    { 거래일자: '2024-01-10', 유형: '현금잔고', 종목코드: '', 수량: 0, 단가: 0,
      금액: 100, 환율: 1300, 금액KRW: 130000, 통화: 'USD', 증권사: 'TEST', 계좌번호: '000', 비고: '현금잔고' },
  ];
  const result = computePortfolio(txns, {}, 1300);
  const cashRows = result.currentHoldings.filter(h => h.isCash);
  assert.equal(cashRows.length, 1, '현금 행 1개');
  assert.equal(cashRows[0].ticker, '현금(USD)', '티커가 현금(USD)');
  assert.equal(cashRows[0].returnPct, 0, 'returnPct = 0');
});

test('현금잔고: weight가 총자산(주식+현금) 기준으로 계산됨', () => {
  // AAPL 5주 @100 USD, fx=1000 → 주식 KRW = 5*100*1000 = 500,000
  // 현금 USD 100 → KRW = 100*1000 = 100,000
  // 총자산 = 600,000 → 현금 비중 = 100,000/600,000 = 16.67%
  const txns = [
    tx('2024-01-10', '매수', 'AAPL', 5, 100, { 금액: 500, 환율: 1000, 금액KRW: 500000, 통화: 'USD' }),
    { 거래일자: '2024-01-10', 유형: '현금잔고', 종목코드: '', 수량: 0, 단가: 0,
      금액: 100, 환율: 1000, 금액KRW: 100000, 통화: 'USD', 증권사: 'TEST', 계좌번호: '000', 비고: '현금잔고' },
  ];
  const result = computePortfolio(txns, { AAPL: 100 }, 1000);
  const cash = result.currentHoldings.find(h => h.ticker === '현금(USD)');
  const aapl = result.currentHoldings.find(h => h.ticker === 'AAPL');
  assert.ok(cash, '현금(USD) 존재');
  assert.ok(aapl, 'AAPL 존재');
  const totalWeight = result.currentHoldings.reduce((s, h) => s + h.weight, 0);
  assert.ok(Math.abs(totalWeight - 100) < 0.1, `전체 비중 합계 ≈ 100%, 실제 ${totalWeight.toFixed(2)}%`);
  assert.ok(Math.abs(cash.weight - (100000 / 600000 * 100)) < 0.1,
    `현금 비중 ≈ 16.67%, 실제 ${cash.weight.toFixed(2)}%`);
});

test('현금잔고 SET 방식: 나중 스냅샷이 이전 값을 덮어씀', () => {
  // 같은 계좌에 현금잔고가 두 번 등장 → 마지막 값이 적용되어야 함
  const txns = [
    { 거래일자: '2024-01-05', 유형: '현금잔고', 종목코드: '', 수량: 0, 단가: 0,
      금액: 1000, 환율: 1300, 금액KRW: 1300000, 통화: 'USD', 증권사: 'TEST', 계좌번호: '000', 비고: '현금잔고' },
    { 거래일자: '2024-01-10', 유형: '현금잔고', 종목코드: '', 수량: 0, 단가: 0,
      금액: 500, 환율: 1300, 금액KRW: 650000, 통화: 'USD', 증권사: 'TEST', 계좌번호: '000', 비고: '현금잔고' },
  ];
  const result = computePortfolio(txns, {}, 1300);
  const cash = result.currentHoldings.find(h => h.ticker === '현금(USD)');
  assert.ok(cash, '현금(USD) 존재');
  assert.ok(Math.abs(cash.qty - 500) < 0.01, `나중 스냅샷 값 500 적용, 실제 ${cash.qty}`);
});
