const DATA_URL = "./data/market_sum_by_roe.json";
const MARKET_IMPLIED_DISCOUNT = 0.10;

const state = {
  rawStocks: [],
  selectedCode: null,
  threshold: 10,
  discountRate: 10,
  durationYears: 3,
  assumedRoe: 20,
  growthRate: 3,
  sortKey: "roe",
  sortDirection: "desc"
};

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }

  return Number(value).toLocaleString("ko-KR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function formatInteger(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }

  return Math.round(value).toLocaleString("ko-KR");
}

function formatPercent(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }

  return `${formatNumber(value, digits)}%`;
}

function formatMarketCap(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }

  const trillion = Math.floor(value / 10000);
  const remainder = value % 10000;

  if (trillion > 0) {
    return remainder > 0
      ? `${trillion}조 ${remainder.toLocaleString("ko-KR")}억`
      : `${trillion}조`;
  }

  return `${value.toLocaleString("ko-KR")}억`;
}

function updateLastUpdated(value) {
  const node = document.getElementById("last-updated-value");

  if (!value) {
    node.textContent = "Unknown";
    return;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    node.textContent = value;
    return;
  }

  node.textContent = date.toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function getBookValuePerShare(stock) {
  if (!stock.current_price || !stock.pbr || stock.pbr <= 0) {
    return null;
  }

  return stock.current_price / stock.pbr;
}

function compoundFairPrice(stock, params) {
  const bps0 = getBookValuePerShare(stock);
  if (!bps0) {
    return null;
  }

  const roe = params.assumedRoe / 100;
  const discount = params.discountRate / 100;
  const growth = params.growthRate / 100;
  const duration = params.durationYears;

  if (roe <= 0 || discount <= 0 || duration <= 0) {
    return null;
  }

  let bps = bps0;
  let pv = 0;

  for (let year = 1; year <= duration; year += 1) {
    const eps = bps * roe;
    pv += eps / ((1 + discount) ** year);
    bps += eps;
  }

  const terminalBps = bps * (1 + growth);
  pv += terminalBps / ((1 + discount) ** duration);

  return pv;
}

function marketImpliedPbr(roePercent, years, discountRate = MARKET_IMPLIED_DISCOUNT) {
  const roe = roePercent / 100;
  if (roe <= 0) {
    return null;
  }

  if (years <= 0) {
    return 1;
  }

  let bps = 1;
  let price = 0;

  for (let year = 1; year <= years; year += 1) {
    const eps = bps * roe;
    price += eps / ((1 + discountRate) ** year);
    bps += eps;
  }

  price += bps / ((1 + discountRate) ** years);
  return price;
}

function estimateImpliedDuration(stock) {
  if (!stock.roe || !stock.pbr || stock.roe <= 0 || stock.pbr <= 0) {
    return null;
  }

  const targetPbr = stock.pbr;
  const maxYears = 50;

  if (targetPbr <= 1) {
    return 0;
  }

  let prevYears = 0;
  let prevValue = marketImpliedPbr(stock.roe, prevYears);

  for (let years = 1; years <= maxYears; years += 1) {
    const currentValue = marketImpliedPbr(stock.roe, years);
    if (currentValue === null) {
      return null;
    }

    if (currentValue >= targetPbr) {
      const range = currentValue - prevValue;
      if (range <= 0) {
        return years;
      }

      const ratio = (targetPbr - prevValue) / range;
      return Number((prevYears + ratio).toFixed(1));
    }

    prevYears = years;
    prevValue = currentValue;
  }

  return maxYears;
}

function estimateKellyRatio(stock, fairPrice) {
  if (!stock.current_price || !fairPrice || fairPrice <= 0) {
    return null;
  }

  const p = 0.5;
  const b = fairPrice / stock.current_price;
  if (b <= 0) {
    return null;
  }

  return p - ((1 - p) / b);
}

function enrichStock(stock) {
  const fairPrice = compoundFairPrice(stock, state);
  const gapRate = fairPrice && stock.current_price
    ? ((fairPrice - stock.current_price) / stock.current_price) * 100
    : null;
  const kellyRatio = estimateKellyRatio(stock, fairPrice);
  const impliedDuration = estimateImpliedDuration(stock);

  return {
    ...stock,
    bps: getBookValuePerShare(stock),
    fairPrice,
    gapRate,
    kellyRatio,
    impliedDuration
  };
}

function getFilteredStocks() {
  const stocks = state.rawStocks
    .filter((stock) => typeof stock.roe === "number" && stock.roe >= state.threshold)
    .map(enrichStock)
    .sort((a, b) => compareStocks(a, b, state.sortKey, state.sortDirection));

  return stocks;
}

function compareValues(aValue, bValue, direction) {
  const aMissing = aValue === null || aValue === undefined || Number.isNaN(aValue);
  const bMissing = bValue === null || bValue === undefined || Number.isNaN(bValue);

  if (aMissing && bMissing) {
    return 0;
  }
  if (aMissing) {
    return 1;
  }
  if (bMissing) {
    return -1;
  }

  if (typeof aValue === "string" || typeof bValue === "string") {
    const result = String(aValue).localeCompare(String(bValue), "ko");
    return direction === "asc" ? result : -result;
  }

  return direction === "asc" ? aValue - bValue : bValue - aValue;
}

function compareStocks(a, b, sortKey, direction) {
  const primary = compareValues(a[sortKey], b[sortKey], direction);
  if (primary !== 0) {
    return primary;
  }

  return compareValues(a.rank, b.rank, "asc");
}

function updateSortHeaders() {
  Array.from(document.querySelectorAll("th[data-sort-key]")).forEach((th) => {
    const isActive = th.dataset.sortKey === state.sortKey;
    th.classList.toggle("is-active", isActive);
    th.classList.toggle("asc", isActive && state.sortDirection === "asc");
    th.classList.toggle("desc", isActive && state.sortDirection === "desc");
  });
}

function bindTableSortHeaders() {
  Array.from(document.querySelectorAll("th[data-sort-key]")).forEach((th) => {
    th.addEventListener("click", () => {
      const { sortKey } = th.dataset;
      if (state.sortKey === sortKey) {
        state.sortDirection = state.sortDirection === "desc" ? "asc" : "desc";
      } else {
        state.sortKey = sortKey;
        state.sortDirection = sortKey === "name" ? "asc" : "desc";
      }

      renderDashboard();
    });
  });
}

function metricClass(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "metric-neutral";
  }

  if (value > 0) {
    return "metric-positive";
  }

  if (value < 0) {
    return "metric-negative";
  }

  return "metric-neutral";
}

function renderTable(stocks) {
  const tbody = document.getElementById("roe-table-body");
  const countBadge = document.getElementById("roe-count-badge");
  const summaryBadge = document.getElementById("table-summary-badge");

  countBadge.textContent = `${stocks.length} Stocks`;
  summaryBadge.textContent = `ROE ${state.threshold}% 이상`;

  if (!stocks.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="11" class="empty-state">조건에 맞는 종목이 없습니다.</td>
      </tr>
    `;
    return;
  }

  updateSortHeaders();

  tbody.innerHTML = stocks.map((stock, index) => `
    <tr data-code="${stock.code}" class="${stock.code === state.selectedCode ? "is-selected" : ""}">
      <td><span class="rank-chip">${index + 1}</span></td>
      <td>${stock.name}</td>
      <td>${formatPercent(stock.roe, 2)}</td>
      <td>${formatNumber(stock.pbr, 2)}</td>
      <td>${formatNumber(stock.per, 2)}</td>
      <td>${formatMarketCap(stock.market_cap_krw_100m)}</td>
      <td>${stock.impliedDuration === null ? "N/A" : `${formatNumber(stock.impliedDuration, 1)}년`}</td>
      <td>${stock.fairPrice === null ? "N/A" : `${formatInteger(stock.fairPrice)}원`}</td>
      <td>${stock.current_price ? `${formatInteger(stock.current_price)}원` : "N/A"}</td>
      <td class="${metricClass(stock.gapRate)}">${formatPercent(stock.gapRate, 1)}</td>
      <td class="${metricClass(stock.kellyRatio)}">${stock.kellyRatio === null ? "N/A" : formatPercent(stock.kellyRatio * 100, 1)}</td>
    </tr>
  `).join("");

  Array.from(tbody.querySelectorAll("tr[data-code]")).forEach((row) => {
    row.addEventListener("click", () => {
      state.selectedCode = row.dataset.code;
      renderDashboard();
    });
  });
}

function renderSelectedSummary(stock) {
  const container = document.getElementById("selected-stock-summary");

  if (!stock) {
    container.innerHTML = "<div class='empty-state'>선택된 종목이 없습니다.</div>";
    return;
  }

  container.innerHTML = `
    <div class="summary-hero">
      <div class="summary-code">${stock.code}</div>
      <div class="summary-name">${stock.name}</div>
      <div class="summary-caption">
        현재 시장이 부여한 PBR과 현재 ROE를 기준으로 시장 내재 지속기간을 추정하고,
        사용자가 설정한 ROE/할인율/N년 가정으로 적정주가를 다시 계산합니다.
      </div>
    </div>

    <div class="summary-grid">
      <div class="summary-card">
        <span class="label">현재주가</span>
        <span class="value">${stock.current_price ? `${formatInteger(stock.current_price)}원` : "N/A"}</span>
      </div>
      <div class="summary-card">
        <span class="label">BPS 추정</span>
        <span class="value">${stock.bps ? `${formatInteger(stock.bps)}원` : "N/A"}</span>
      </div>
      <div class="summary-card">
        <span class="label">시가총액</span>
        <span class="value">${formatMarketCap(stock.market_cap_krw_100m)}</span>
      </div>
      <div class="summary-card">
        <span class="label">ROE</span>
        <span class="value">${formatPercent(stock.roe, 2)}</span>
      </div>
      <div class="summary-card">
        <span class="label">PBR</span>
        <span class="value">${formatNumber(stock.pbr, 2)}</span>
      </div>
      <div class="summary-card">
        <span class="label">PER</span>
        <span class="value">${formatNumber(stock.per, 2)}</span>
      </div>
    </div>
  `;
}

function renderDurationPanel(stock) {
  const container = document.getElementById("duration-panel");

  if (!stock) {
    container.innerHTML = "<div class='empty-state'>선택 종목이 없습니다.</div>";
    return;
  }

  container.innerHTML = `
    <div class="calc-grid">
      <div class="calc-item">
        <div class="label">현재 ROE</div>
        <div class="value">${formatPercent(stock.roe, 2)}</div>
      </div>
      <div class="calc-item">
        <div class="label">현재 PBR</div>
        <div class="value">${formatNumber(stock.pbr, 2)}</div>
      </div>
      <div class="calc-item">
        <div class="label">할인율</div>
        <div class="value">10.0%</div>
      </div>
      <div class="calc-item">
        <div class="label">시장 내재 지속기간</div>
        <div class="value">${stock.impliedDuration === null ? "N/A" : `${formatNumber(stock.impliedDuration, 1)}년`}</div>
      </div>
    </div>
    <div class="calc-note">
      현재 PBR이 동일해지도록 “연도별 EPS 현재가치 합 + 최종 BPS 현재가치” 모델을 역으로 풀어
      시장이 이 ROE를 몇 년 유지된다고 보고 있는지 추정합니다.
    </div>
  `;
}

function renderFairValuePanel(stock) {
  const container = document.getElementById("fair-value-panel");

  if (!stock) {
    container.innerHTML = "<div class='empty-state'>선택 종목이 없습니다.</div>";
    return;
  }

  container.innerHTML = `
    <div class="calc-grid">
      <div class="calc-item">
        <div class="label">ROE 가정</div>
        <div class="value">${formatPercent(state.assumedRoe, 1)}</div>
      </div>
      <div class="calc-item">
        <div class="label">지속기간</div>
        <div class="value">${state.durationYears}년</div>
      </div>
      <div class="calc-item">
        <div class="label">영구성장률</div>
        <div class="value">${formatPercent(state.growthRate, 1)}</div>
      </div>
      <div class="calc-item">
        <div class="label">할인율</div>
        <div class="value">${formatPercent(state.discountRate, 1)}</div>
      </div>
      <div class="calc-item">
        <div class="label">추정 BPS</div>
        <div class="value">${stock.bps ? `${formatInteger(stock.bps)}원` : "N/A"}</div>
      </div>
      <div class="calc-item">
        <div class="label">적정주가</div>
        <div class="value">${stock.fairPrice ? `${formatInteger(stock.fairPrice)}원` : "N/A"}</div>
      </div>
    </div>
    <div class="calc-note">
      연도별로 <strong>BPS × ROE = EPS</strong>를 계산하고, 각 연도의 EPS를 할인한 뒤
      마지막 BPS의 현재가치를 더하는 방식으로 적정주가를 계산합니다.
    </div>
  `;
}

function renderKellyPanel(stock) {
  const container = document.getElementById("kelly-panel");

  if (!stock) {
    container.innerHTML = "<div class='empty-state'>선택 종목이 없습니다.</div>";
    return;
  }

  const payoutMultiple = stock.fairPrice && stock.current_price
    ? stock.fairPrice / stock.current_price
    : null;

  container.innerHTML = `
    <div class="calc-grid">
      <div class="calc-item">
        <div class="label">승률 p</div>
        <div class="value">50.0%</div>
      </div>
      <div class="calc-item">
        <div class="label">패배확률 q</div>
        <div class="value">50.0%</div>
      </div>
      <div class="calc-item">
        <div class="label">배당률 b</div>
        <div class="value">${payoutMultiple === null ? "N/A" : formatNumber(payoutMultiple, 2)}</div>
      </div>
      <div class="calc-item">
        <div class="label">켈리비율</div>
        <div class="value ${metricClass(stock.kellyRatio)}">${stock.kellyRatio === null ? "N/A" : formatPercent(stock.kellyRatio * 100, 1)}</div>
      </div>
      <div class="calc-item">
        <div class="label">현재가 대비 괴리율</div>
        <div class="value ${metricClass(stock.gapRate)}">${formatPercent(stock.gapRate, 1)}</div>
      </div>
      <div class="calc-item">
        <div class="label">기준식</div>
        <div class="value">K = p - (1-p) / b</div>
      </div>
    </div>
    <div class="calc-note">
      현재 단계에서는 승률과 패배확률을 각각 50%로 고정하고,
      배당률 b는 적정가 ÷ 현재가로 단순화해 계산합니다.
    </div>
  `;
}

function renderDashboard() {
  const stocks = getFilteredStocks();

  if (!state.selectedCode || !stocks.some((stock) => stock.code === state.selectedCode)) {
    state.selectedCode = stocks[0]?.code ?? null;
  }

  const selectedStock = stocks.find((stock) => stock.code === state.selectedCode) ?? null;

  renderTable(stocks);
  renderSelectedSummary(selectedStock);
  renderDurationPanel(selectedStock);
  renderFairValuePanel(selectedStock);
  renderKellyPanel(selectedStock);
}

function syncControlLabels() {
  document.getElementById("discount-value").textContent = `${formatNumber(state.discountRate, 1)}%`;
  document.getElementById("duration-value").textContent = `${state.durationYears}년`;
}

function bindControls() {
  const thresholdSelect = document.getElementById("roe-threshold-select");
  const discountRange = document.getElementById("discount-range");
  const durationRange = document.getElementById("duration-range");
  const assumedRoeInput = document.getElementById("assumed-roe-input");
  const growthRateInput = document.getElementById("growth-rate-input");

  thresholdSelect.value = String(state.threshold);
  discountRange.value = String(state.discountRate);
  durationRange.value = String(state.durationYears);
  assumedRoeInput.value = String(state.assumedRoe);
  growthRateInput.value = String(state.growthRate);
  syncControlLabels();

  thresholdSelect.addEventListener("change", (event) => {
    state.threshold = Number(event.target.value);
    renderDashboard();
  });

  discountRange.addEventListener("input", (event) => {
    state.discountRate = Number(event.target.value);
    syncControlLabels();
    renderDashboard();
  });

  durationRange.addEventListener("input", (event) => {
    state.durationYears = Number(event.target.value);
    syncControlLabels();
    renderDashboard();
  });

  assumedRoeInput.addEventListener("input", (event) => {
    state.assumedRoe = Number(event.target.value);
    renderDashboard();
  });

  growthRateInput.addEventListener("input", (event) => {
    state.growthRate = Number(event.target.value);
    renderDashboard();
  });
}

function renderError(message) {
  document.getElementById("roe-table-body").innerHTML = `<tr><td colspan="11" class="empty-state">${message}</td></tr>`;
  document.getElementById("selected-stock-summary").innerHTML = `<div class="empty-state">${message}</div>`;
  document.getElementById("duration-panel").innerHTML = `<div class="empty-state">${message}</div>`;
  document.getElementById("fair-value-panel").innerHTML = `<div class="empty-state">${message}</div>`;
  document.getElementById("kelly-panel").innerHTML = `<div class="empty-state">${message}</div>`;
}

async function loadStocks() {
  try {
    const response = await fetch(DATA_URL);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    state.rawStocks = payload.stocks || [];
    updateLastUpdated(payload.crawled_at_utc);
    bindControls();
    bindTableSortHeaders();
    renderDashboard();
  } catch (error) {
    renderError("데이터를 불러오지 못했습니다. 최신 JSON을 다시 생성한 뒤 서버에서 페이지를 열어주세요.");
    console.error(error);
  }
}

loadStocks();
