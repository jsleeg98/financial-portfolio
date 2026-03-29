// ── 종목 통화 판별 ─────────────────────────────────────────────
function isForeignTicker(ticker, currency) {
  if (currency === 'USD') return true;
  if (currency === 'KRW') return false;
  // 통화 정보 없으면 종목코드로 판별 (영문=해외, 한글=국내)
  return /^[A-Z]/.test(ticker);
}

// ── 포트폴리오 계산 엔진 ────────────────────────────────────────
function computePortfolio(txns, prices, fx, dailyFX = {}, historicalPrices = {}) {
  // 날짜순 정렬 후, 같은 날은 일별 그룹 처리로 정확한 순서 보장
  const dateSorted = [...txns].sort((a, b) => a.거래일자.localeCompare(b.거래일자));
  // 날짜별 그룹화
  const dateGroupsForSort = {};
  dateSorted.forEach(tx => {
    if (!dateGroupsForSort[tx.거래일자]) dateGroupsForSort[tx.거래일자] = [];
    dateGroupsForSort[tx.거래일자].push(tx);
  });
  // holdings: { ticker: { qty, totalCost, totalCostKRW, currency } }
  const holdings = {};
  let cashUSD = 0;
  let cashKRW = 0;
  const cashByAccount = {}; // "broker-account" → { USD?: number, KRW?: number }

  const monthMap = {};
  const monthlyRealizedMap = {}; // month → realized KRW (매도 손익 + 배당)

  // 거래내역 기반 마지막 단가 추적 (시세 미조회 시 fallback)
  const lastTxPrice = {};

  // TWR 계산용: 외부 자금 흐름 추적
  let totalDeposited = 0;

  // 날짜별 처리: 기존 보유 종목 매도 먼저, 미보유 종목 매수 먼저
  function getDayOrder(dayTxns) {
    // 1. 출고/감자출고 먼저 (기존 주식 회수 — 원가 보존, 수량 0)
    const splitOut = dayTxns.filter(tx => tx.유형 === '출고' || tx.유형 === '감자출고');
    // 2. 입고 (분할/감자 후 수량 교체)
    const splitIn = dayTxns.filter(tx => tx.유형 === '입고');
    // 3. 기존 보유 종목 매도 (평균단가 보존)
    const sells = dayTxns.filter(tx => tx.유형 === '매도' && tx.종목코드 && holdings[tx.종목코드]?.qty > 0.0001);
    // 4. 나머지: 매수 먼저, 미보유 종목 매도 나중 (당일 매수→매도 케이스)
    const processed = new Set([...splitOut, ...splitIn, ...sells]);
    const rest = dayTxns.filter(tx => !processed.has(tx));
    const restBuys = rest.filter(tx => tx.유형 === '매수');
    const restOther = rest.filter(tx => tx.유형 !== '매수');
    return [...splitOut, ...splitIn, ...sells, ...restBuys, ...restOther];
  }

  const sortedDatesMain = Object.keys(dateGroupsForSort).sort();
  const sorted = [];

  sortedDatesMain.forEach(date => {
    const ordered = getDayOrder(dateGroupsForSort[date]);
    ordered.forEach(tx => {
      sorted.push(tx);
      processTx(tx);
    });
  });

  function processTx(tx) {
    const ticker = tx.종목코드;
    const month = tx.거래일자.slice(0, 7);
    const currency = tx.통화 || (isForeignTicker(ticker, '') ? 'USD' : 'KRW');
    const amount = tx.금액 || 0;
    const amountKRW = tx.금액KRW || 0;
    const unitPrice = tx.단가 || 0;

    // 단가 추적 (매수/매도 시 마지막 거래 단가 기록)
    if (ticker && unitPrice > 0 && (tx.유형 === '매수' || tx.유형 === '매도')) {
      lastTxPrice[ticker] = { price: unitPrice, currency };
    }

    if (tx.유형 === '매수' && ticker) {
      if (!holdings[ticker]) holdings[ticker] = { qty: 0, totalCost: 0, totalCostKRW: 0, currency };
      holdings[ticker].qty += tx.수량;
      holdings[ticker].totalCost += amount;
      // KRW 원가: KRW 종목은 금액 그대로, USD 종목은 금액KRW (환율 적용된 값)
      if (currency === 'KRW') {
        holdings[ticker].totalCostKRW += amount;
      } else {
        const txFX = dailyFX[tx.거래일자] || tx.환율 || fx;
        holdings[ticker].totalCostKRW += amountKRW > 0 ? amountKRW : amount * txFX;
      }
    } else if (tx.유형 === '매도' && ticker) {
      if (!holdings[ticker]) holdings[ticker] = { qty: 0, totalCost: 0, totalCostKRW: 0, currency };
      if (holdings[ticker].qty > 0) {
        const ratio = tx.수량 / holdings[ticker].qty;
        const costDeducted = holdings[ticker].totalCostKRW * ratio;
        const txFX = dailyFX[tx.거래일자] || tx.환율 || fx;
        const sellAmountKRW = currency === 'KRW' ? amount : (amountKRW > 0 ? amountKRW : amount * txFX);
        if (!monthlyRealizedMap[month]) monthlyRealizedMap[month] = 0;
        monthlyRealizedMap[month] += sellAmountKRW - costDeducted;
        holdings[ticker].totalCost -= holdings[ticker].totalCost * ratio;
        holdings[ticker].totalCostKRW -= costDeducted;
        holdings[ticker].qty -= tx.수량;
        if (holdings[ticker].qty < 0.0001) holdings[ticker] = { qty: 0, totalCost: 0, totalCostKRW: 0, currency };
      }
      // 매도대금 → 현금
      if (currency === 'USD') cashUSD += amount;
      else cashKRW += amount;
    } else if (tx.유형 === '배당') {
      if (!monthlyRealizedMap[month]) monthlyRealizedMap[month] = 0;
      const txFX = dailyFX[tx.거래일자] || tx.환율 || fx;
      monthlyRealizedMap[month] += currency === 'KRW' ? amount : (amountKRW > 0 ? amountKRW : amount * txFX);
      if (currency === 'USD') cashUSD += amount;
      else cashKRW += amount;
    } else if (tx.유형 === '입금') {
      if (currency === 'USD') cashUSD += amount;
      else cashKRW += amountKRW || amount;
    } else if (tx.유형 === '현금잔고') {
      const acctKey = `${tx.증권사 || ''}-${tx.계좌번호 || ''}`;
      if (!cashByAccount[acctKey]) cashByAccount[acctKey] = {};
      if (currency === 'USD') cashByAccount[acctKey].USD = amount;
      else cashByAccount[acctKey].KRW = tx.금액KRW || amount;
    } else if (tx.유형 === '출고' && ticker) {
      // 액면분할 출고: 기존 주식 전량 회수 (원가 보존, 입고에서 수량 교체)
      // 원가는 유지하고 수량만 0으로 (입고에서 새 수량 설정)
      if (holdings[ticker] && holdings[ticker].qty > 0) {
        holdings[ticker].qty = 0;
      }
    } else if (tx.유형 === '감자출고' && ticker) {
      // 감자출고: 수량만 0으로 (원가 보존 — 이어지는 감자입고에서 수량 교체)
      if (holdings[ticker] && holdings[ticker].qty > 0) {
        holdings[ticker].qty = 0;
      }
    } else if (tx.유형 === '입고' && ticker) {
      if (!holdings[ticker]) holdings[ticker] = { qty: 0, totalCost: 0, totalCostKRW: 0, currency };
      // 입고: 수량 교체, 원가는 기존 값 보존 (액면분할/감자입고)
      // 기존 원가가 있으면 보존, 없으면 0 (회사분할입고 등 신규 종목)
      const prevCost = holdings[ticker].totalCost;
      const prevCostKRW = holdings[ticker].totalCostKRW;
      holdings[ticker].qty = tx.수량;
      holdings[ticker].totalCost = prevCost;
      holdings[ticker].totalCostKRW = prevCostKRW;
    }

    // 월말 스냅샷
    let snapCostKRW = 0;
    Object.values(holdings).forEach(h => { if (h.qty > 0) snapCostKRW += h.totalCostKRW; });
    monthMap[month] = {
      holdings: JSON.parse(JSON.stringify(holdings)),
      cashUSD, cashKRW, costKRW: snapCostKRW
    };
  }

  // cashByAccount 스냅샷이 있으면 accumulated cash 대신 사용
  // USD: 스냅샷 없으면 0 처리 (NH나무증권처럼 환전→즉시매수 패턴은 매도 누적값이 실제 잔고와 무관)
  const _snapKeys = Object.keys(cashByAccount);
  if (_snapKeys.some(k => cashByAccount[k].USD !== undefined)) {
    cashUSD = _snapKeys.reduce((s, k) => s + (cashByAccount[k].USD || 0), 0);
  } else {
    cashUSD = 0;
  }
  if (_snapKeys.some(k => cashByAccount[k].KRW !== undefined)) {
    cashKRW = _snapKeys.reduce((s, k) => s + (cashByAccount[k].KRW || 0), 0);
  }

  // 가격 조회: 시세 > 마지막 거래 단가 순으로 fallback
  function getPrice(ticker) {
    return prices[ticker] || (lastTxPrice[ticker] ? lastTxPrice[ticker].price : 0);
  }

  // 현재 보유 종목
  const currentHoldings = [];
  let totalValueKRW = 0;
  let totalCostKRW = 0;
  Object.entries(holdings).forEach(([ticker, h]) => {
    if (h.qty < 0.0001) return;
    const price = getPrice(ticker);
    const isUSD = h.currency === 'USD';
    const valueKRW = isUSD ? h.qty * price * fx : h.qty * price;
    const avgCost = h.qty > 0 ? h.totalCost / h.qty : 0;
    totalValueKRW += valueKRW;
    totalCostKRW += h.totalCostKRW;
    currentHoldings.push({
      ticker, qty: h.qty, avgCost, price,
      valueKRW, costKRW: h.totalCostKRW, currency: h.currency
    });
  });

  // 매입금액 = 보유종목 KRW 원가 합계, 평가금액 = 보유종목 시가
  const evalKRW = totalValueKRW;
  const cashUSDValue = cashUSD * fx;
  const cashKRWValue = cashKRW;
  const netAssetKRW = evalKRW + cashUSDValue + cashKRWValue;
  const profitKRW = evalKRW - totalCostKRW;
  const profitRate = totalCostKRW > 0 ? (profitKRW / totalCostKRW) * 100 : 0;

  // 비중: 주식 + 현금 합산 기준
  const totalForWeight = totalValueKRW + cashUSDValue + cashKRWValue || 1;
  currentHoldings.forEach(h => {
    h.weight = (h.valueKRW / totalForWeight) * 100;
    h.returnPct = h.avgCost > 0 ? ((h.price - h.avgCost) / h.avgCost) * 100 : 0;
  });
  currentHoldings.sort((a, b) => b.weight - a.weight);

  // 현금 행 추가 (USD·KRW 각각, 현재 환율 기준 KRW 환산)
  if (cashUSD > 0.001) currentHoldings.push({
    ticker: '현금(USD)', qty: cashUSD, avgCost: 1, price: 1,
    valueKRW: cashUSDValue, costKRW: cashUSDValue, currency: 'USD',
    weight: cashUSDValue / totalForWeight * 100, returnPct: 0, isCash: true,
  });
  if (cashKRW > 0.5) currentHoldings.push({
    ticker: '현금(KRW)', qty: cashKRW, avgCost: 1, price: 1,
    valueKRW: cashKRWValue, costKRW: cashKRWValue, currency: 'KRW',
    weight: cashKRWValue / totalForWeight * 100, returnPct: 0, isCash: true,
  });

  // 월별 시계열
  const months = Object.keys(monthMap).sort();
  const monthlyTrend = [];
  const monthlyPnL = [];
  let prevVal = null;

  const todayYM = new Date().toISOString().slice(0, 7);
  const sortedFXDates = Object.keys(dailyFX).sort();

  // 해당 월의 마지막 가용 FX (benchmarkFX 기반)
  function getMonthEndFX(month) {
    const upperBound = `${month}-31`;
    let mfx = fx;
    for (const d of sortedFXDates) {
      if (d <= upperBound) mfx = dailyFX[d];
      else break;
    }
    return mfx;
  }

  months.forEach(m => {
    const snap = monthMap[m];
    const isHistorical = m < todayYM;
    const monthFX = isHistorical ? getMonthEndFX(m) : fx;

    let valKRW = 0;
    Object.entries(snap.holdings).forEach(([t, h]) => {
      if (h.qty > 0) {
        let p;
        if (isHistorical && historicalPrices[t]?.[m] != null) {
          p = historicalPrices[t][m];
        } else {
          p = getPrice(t);
        }
        const isUSD = h.currency === 'USD';
        valKRW += isUSD ? h.qty * p * monthFX : h.qty * p;
      }
    });
    const costKRW = snap.costKRW;
    monthlyTrend.push({ month: m, valuation: valKRW, principal: costKRW });

    const pnl = prevVal !== null ? valKRW - prevVal - (costKRW - (monthlyTrend.length >= 2 ? monthlyTrend[monthlyTrend.length - 2].principal : 0)) : 0;
    monthlyPnL.push({ month: m, pnl });
    prevVal = valKRW;
  });

  // 과거 시세 조회 필요 목록 계산용 (USD 종목만)
  const monthlyHoldings = months.map(m => ({
    month: m,
    usdTickers: Object.entries(monthMap[m].holdings)
      .filter(([, h]) => h.qty > 0 && h.currency === 'USD')
      .map(([t]) => t)
  }));

  // 월별 실현손익 + 누적
  const monthlyRealizedPnL = [];
  let cumRealized = 0;
  months.forEach(m => {
    const realized = monthlyRealizedMap[m] || 0;
    cumRealized += realized;
    monthlyRealizedPnL.push({ month: m, realized: Math.round(realized), cumulative: Math.round(cumRealized) });
  });

  // 누적수익률 (월별)
  const cumulativeReturn = [];
  monthlyTrend.forEach(mt => {
    const ret = mt.principal > 0 ? ((mt.valuation / mt.principal) - 1) * 100 : 0;
    cumulativeReturn.push({ month: mt.month, returnPct: ret });
  });

  // ── TWR (시간가중수익률) 계산 ──────────────────────────────
  // 거래일마다 포트폴리오 가치를 계산하고, 외부 자금 유입 시 구간 분리
  const dailySnapshots = {};
  const twrHoldings = {};
  let twrCashUSD = 0, twrCashKRW = 0;
  const twrPeriods = []; // [{ startValue, endValue }]
  let twrPrevValue = 0;
  let runningTwr = 1.0; // 완료된 구간의 누적 수익률 곱

  // 거래일별로 그룹화
  const dateGroups = {};
  sorted.forEach(tx => {
    if (!dateGroups[tx.거래일자]) dateGroups[tx.거래일자] = [];
    dateGroups[tx.거래일자].push(tx);
  });

  // TWR 전용 단가 추적 (거래일별로 업데이트; 전역 lastTxPrice와 독립)
  const twrPriceMap = {};

  function calcPortfolioValue() {
    let val = 0;
    Object.entries(twrHoldings).forEach(([t, h]) => {
      if (h.qty > 0) {
        const p = twrPriceMap[t] || 0;
        val += h.currency === 'USD' ? h.qty * p * fx : h.qty * p;
      }
    });
    val += twrCashUSD * fx + twrCashKRW;
    return val;
  }

  const sortedDates = Object.keys(dateGroups).sort();
  sortedDates.forEach(date => {
    const dayTxns = dateGroups[date];

    // Step 1: 오늘 거래 단가로 가격 먼저 업데이트 (가격 변동 반영)
    dayTxns.forEach(tx => {
      if (tx.종목코드 && tx.단가 > 0 && (tx.유형 === '매수' || tx.유형 === '매도')) {
        twrPriceMap[tx.종목코드] = tx.단가;
      }
    });

    // Step 2: 업데이트된 가격으로 거래 전 포트폴리오 가치 계산
    const valueBefore = calcPortfolioValue();

    // Step 3: 수량/현금 업데이트 및 외부유입 계산
    let externalFlow = 0;

    dayTxns.forEach(tx => {
      const ticker = tx.종목코드;
      const currency = tx.통화 || (isForeignTicker(ticker, '') ? 'USD' : 'KRW');
      const amount = tx.금액 || 0;
      const amountKRW = tx.금액KRW || 0;

      if (tx.유형 === '매수' && ticker) {
        if (!twrHoldings[ticker]) twrHoldings[ticker] = { qty: 0, currency };
        twrHoldings[ticker].qty += tx.수량;
        const txFX = dailyFX[tx.거래일자] || tx.환율 || fx;
        const costKRW = currency === 'KRW' ? amount : (amountKRW > 0 ? amountKRW : amount * txFX);
        externalFlow += costKRW;
      } else if (tx.유형 === '매도' && ticker) {
        if (twrHoldings[ticker] && twrHoldings[ticker].qty > 0) {
          twrHoldings[ticker].qty -= tx.수량;
          if (twrHoldings[ticker].qty < 0.0001) twrHoldings[ticker].qty = 0;
        }
        if (currency === 'USD') twrCashUSD += amount;
        else twrCashKRW += amount;
      } else if (tx.유형 === '배당') {
        if (currency === 'USD') twrCashUSD += amount;
        else twrCashKRW += amount;
      } else if (tx.유형 === '출고' && ticker) {
        if (twrHoldings[ticker]) twrHoldings[ticker].qty = 0;
      } else if (tx.유형 === '감자출고' && ticker) {
        if (twrHoldings[ticker]) twrHoldings[ticker].qty = 0;
      } else if (tx.유형 === '입고' && ticker) {
        if (!twrHoldings[ticker]) twrHoldings[ticker] = { qty: 0, currency };
        twrHoldings[ticker].qty = tx.수량;
      }
    });

    const valueAfter = calcPortfolioValue();

    // Step 4: 외부유입 시 이전 구간 종료 → runningTwr 업데이트
    if (twrPrevValue > 0 && externalFlow > 0) {
      runningTwr *= valueBefore > 0 ? (valueBefore / twrPrevValue) : 1;
      twrPeriods.push({ startValue: twrPrevValue, endValue: valueBefore });
    }

    twrPrevValue = externalFlow > 0 ? valueAfter : (twrPrevValue > 0 ? twrPrevValue : valueAfter);
    if (twrPrevValue === 0 && valueAfter > 0) twrPrevValue = valueAfter;

    // Step 5: 스냅샷 저장 — running TWR(%) 포함
    // snapTwr = 완료된 구간 누적 × 현재 구간 진행률
    const snapTwr = twrPrevValue > 0
      ? (runningTwr * (valueAfter / twrPrevValue) - 1) * 100
      : 0;

    dailySnapshots[date] = {
      holdings: JSON.parse(JSON.stringify(twrHoldings)),
      cashUSD: twrCashUSD, cashKRW: twrCashKRW,
      portfolioValue: valueAfter,
      twr: snapTwr,
      externalFlow
    };
  });

  // 마지막 구간 종료
  const finalValue = calcPortfolioValue();
  if (twrPrevValue > 0) {
    twrPeriods.push({ startValue: twrPrevValue, endValue: finalValue });
  }

  // TWR = (1+r1)(1+r2)...(1+rn) - 1
  let twrCumulative = 1;
  twrPeriods.forEach(p => {
    if (p.startValue > 0) twrCumulative *= (p.endValue / p.startValue);
  });
  const twrReturn = (twrCumulative - 1) * 100;

  // 첫 거래일
  const firstTxDate = sorted.length > 0 ? sorted[0].거래일자 : null;

  return {
    currentHoldings, totalValueKRW: evalKRW, profitKRW, profitRate,
    investedKRW: totalCostKRW, netAssetKRW,
    monthlyTrend, monthlyPnL, monthlyRealizedPnL, monthlyHoldings, cumulativeReturn,
    cashUSD, cashKRW, dailySnapshots, firstTxDate, twrReturn
  };
}

// ── 벤치마크 수익률 (일별 데이터 기반) ──────────────────────────
function computeBenchmarkReturns(dailyMap, dates, baseDate) {
  // baseDate 이전의 가장 가까운 거래일 종가를 기준가로 사용
  const sortedDates = Object.keys(dailyMap).sort();
  let baseClose = null;
  for (const d of sortedDates) {
    if (d <= baseDate) baseClose = dailyMap[d];
    else break;
  }
  if (!baseClose) return dates.map(d => ({ date: d, returnPct: 0 }));

  return dates.map(date => {
    // 해당 날짜 이전의 가장 가까운 거래일 종가
    let close = null;
    for (const d of sortedDates) {
      if (d <= date) close = dailyMap[d];
      else break;
    }
    if (!close) close = baseClose;
    return { date, returnPct: ((close / baseClose) - 1) * 100 };
  });
}

// ── 현금흐름 반영 벤치마크 TWR ──────────────────────────────────
// 포트폴리오의 매수 발생일(externalFlow > 0)을 구간 경계로 삼아
// 벤치마크도 동일한 타이밍에 투자했다고 가정한 TWR을 계산한다.
// getPortfolioSubReturn과 완전히 대칭되는 공정한 비교 기준.
function computeCashFlowBenchmarkTWR(dailySnapshots, dailyMap, queryDates) {
  const sortedBmDates = Object.keys(dailyMap).sort();
  if (!sortedBmDates.length) return queryDates.map(d => ({ date: d, returnPct: 0 }));

  function getPrice(date) {
    let price = null;
    for (const d of sortedBmDates) {
      if (d <= date) price = dailyMap[d];
      else break;
    }
    return price;
  }

  const snapDates = Object.keys(dailySnapshots).sort();
  const flowDates = snapDates.filter(d => (dailySnapshots[d].externalFlow || 0) > 0);
  if (flowDates.length === 0) return queryDates.map(d => ({ date: d, returnPct: 0 }));

  function getBenchmarkTWRAt(targetDate) {
    if (targetDate < flowDates[0]) return 0;

    let periodIdx = 0;
    for (let i = 1; i < flowDates.length; i++) {
      if (flowDates[i] <= targetDate) periodIdx = i;
      else break;
    }

    let twr = 1;

    // 완료된 구간들 복리 계산
    for (let i = 0; i < periodIdx; i++) {
      const startPrice = getPrice(flowDates[i]);
      const lastBeforeNext = [...snapDates].reverse().find(d => d < flowDates[i + 1]) || flowDates[i];
      const endPrice = getPrice(lastBeforeNext);
      if (startPrice && endPrice && startPrice > 0) twr *= endPrice / startPrice;
    }

    // 현재 구간 (진행 중): flowDates[periodIdx] → targetDate
    const currStart = getPrice(flowDates[periodIdx]);
    const currEnd = getPrice(targetDate);
    if (currStart && currEnd && currStart > 0) twr *= currEnd / currStart;

    return (twr - 1) * 100;
  }

  return queryDates.map(date => ({ date, returnPct: getBenchmarkTWRAt(date) }));
}

// Node.js 환경에서 모듈로 사용
if (typeof module !== 'undefined') {
  module.exports = { computePortfolio, isForeignTicker, computeBenchmarkReturns, computeCashFlowBenchmarkTWR };
}
