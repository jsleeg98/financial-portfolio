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
