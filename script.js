const DATA_URL = "./data/market_sum_by_roe.json";
const ROE_THRESHOLD = 10;

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }

  return Number(value).toLocaleString("ko-KR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function formatMarketCap(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }

  const trillion = Math.floor(value / 10000);
  const remainder = value % 10000;

  if (trillion > 0) {
    return remainder > 0 ? `${trillion}조 ${remainder.toLocaleString("ko-KR")}억` : `${trillion}조`;
  }

  return `${value.toLocaleString("ko-KR")}억`;
}

function updateBadge(count) {
  const badge = document.getElementById("roe-count-badge");
  badge.textContent = `${count} Stocks`;
}

function renderTable(stocks) {
  const tbody = document.getElementById("roe-table-body");

  if (!stocks.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7">ROE ${ROE_THRESHOLD}% 초과 종목이 없습니다.</td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = stocks.map((stock, index) => `
    <tr>
      <td><span class="rank-chip">${index + 1}</span></td>
      <td>${stock.name}</td>
      <td>${stock.code}</td>
      <td class="roe-value">${formatNumber(stock.roe)}%</td>
      <td>${formatNumber(stock.per)}</td>
      <td>${formatNumber(stock.foreigner_ratio)}%</td>
      <td>${formatMarketCap(stock.market_cap_krw_100m)}</td>
    </tr>
  `).join("");
}

function renderHighlight(stock) {
  const container = document.getElementById("top-highlight");

  if (!stock) {
    container.innerHTML = "<div>표시할 데이터가 없습니다.</div>";
    return;
  }

  container.innerHTML = `
    <div>
      <div class="highlight-ticker">${stock.code}</div>
      <div class="highlight-name">${stock.name}</div>
    </div>
    <div class="highlight-grid">
      <div class="highlight-item">
        <span class="label">ROE</span>
        <span class="value">${formatNumber(stock.roe)}%</span>
      </div>
      <div class="highlight-item">
        <span class="label">PER</span>
        <span class="value">${formatNumber(stock.per)}</span>
      </div>
      <div class="highlight-item">
        <span class="label">외국인비율</span>
        <span class="value">${formatNumber(stock.foreigner_ratio)}%</span>
      </div>
      <div class="highlight-item">
        <span class="label">시가총액</span>
        <span class="value">${formatMarketCap(stock.market_cap_krw_100m)}</span>
      </div>
    </div>
  `;
}

function renderError(message) {
  const tbody = document.getElementById("roe-table-body");
  const container = document.getElementById("top-highlight");
  const badge = document.getElementById("roe-count-badge");

  tbody.innerHTML = `<tr><td colspan="7">${message}</td></tr>`;
  container.innerHTML = `<div>${message}</div>`;
  badge.textContent = "Error";
}

async function loadRoeStocks() {
  try {
    const response = await fetch(DATA_URL);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    const stocks = (payload.stocks || [])
      .filter((stock) => typeof stock.roe === "number" && stock.roe > ROE_THRESHOLD)
      .sort((a, b) => b.roe - a.roe);

    updateBadge(stocks.length);
    renderTable(stocks);
    renderHighlight(stocks[0]);
  } catch (error) {
    renderError("데이터를 불러오지 못했습니다. 로컬 서버에서 페이지를 열고 JSON 경로를 확인해주세요.");
    console.error(error);
  }
}

loadRoeStocks();
