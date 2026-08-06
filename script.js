const MARKET_DATA_URL = "./data/market_sum_by_roe.json";
const ROE_HISTORY_URL = "./data/fnguide_roe_history.json";
const FINANCIAL_N_URL = "./data/financial_n_estimates.json";
const INVESTMENT_SCREENS_URL = "./data/investment_screens.json";
const DART_MAJOR_URL = "./data/dart_major_holders.json";
const TREASURY_YIELDS_URL = "./data/treasury_yields.json";
const ETF_BRANDS_URL = "./data/naver_etf_brands.json";
const MARKET_INDICES_URL = "./data/market_indices.json";
const MARKET_HEATMAP_URL = "./data/market_heatmap.json";
const PORTFOLIO_URL = "./data/portfolio.json";
const PORTFOLIO_STORAGE_KEY = "value-dashboard-portfolio-v2";
const KOREA_FLOW_URL = "./data/korea_investor_flow.json";
const KOREA_SHORT_URL = "./data/korea_short_selling.json";
const DART_DISCLOSURES_URL = "./data/dart_disclosures.json";
const DART_EVENTS_URL = "./data/dart_event_details.json";
const DART_INSIDERS_URL = "./data/dart_insider_trades.json";
const US_MARKET_URL = "./data/us_market_snapshot.json";
const US_SHORT_INTEREST_URL = "./data/us_finra_short_interest.json";
const US_SHORT_VOLUME_URL = "./data/us_finra_short_volume.json";
const NAVER_NEWS_URL = "./data/naver_news.json";
const AI_BRIEFING_URL = "./data/ai_market_briefing.json";
const SEC_FILINGS_URL = "./data/us_sec_filings.json";
const FINNHUB_URL = "./data/us_finnhub.json";
const DATA_MANIFEST_URL = "./data/data_manifest.json";
const MARKET_IMPLIED_DISCOUNT_PCT = 10;
const MARKET_IMPLIED_ROE_GUARD_PP = 2;

const state = {
  rawStocks: [],
  rawStockByCode: new Map(),
  roeHistoryByCode: new Map(),
  financialNByCode: new Map(),
  investmentScreenByCode: new Map(),
  investmentScreensPayload: null,
  dartMajorByCode: new Map(),
  selectedCode: null,
  threshold: 10,
  minRoa: 7,
  exemptFinancialRoa: true,
  discountRate: 10,
  durationOffset: 0,
  roeAdjustment: 0,
  sortKey: "roe",
  sortDirection: "desc",
  prioritySortKey: "buffettRank",
  prioritySortDirection: "asc",
  activeWorkspace: "priority",
  loadedWorkspaces: new Set(),
  loadingWorkspaces: new Set(),
  featureData: {},
  flowMarket: "KOSPI",
  flowInvestor: "foreign",
  flowDirection: "buy",
  flowSearch: "",
  shortMarket: "KOSPI",
  shortMode: "trade",
  shortSearch: "",
  eventType: "buybacks",
  eventSort: "impact",
  eventSearch: "",
  insiderMode: "confirmed",
  insiderSearch: "",
  filingCategory: "all",
  filingSearch: "",
  usStockSort: "market_cap",
  usStockSearch: "",
  usSelectedSymbol: null,
  usShortMode: "interest",
  usShortSearch: "",
  newsCategory: "all",
  newsSearch: "",
  secCategory: "all",
  secSearch: "",
  marketAssets: [],
  selectedMarketAsset: null,
  marketChartRange: "3m",
  todayNewsCategory: "semiconductor",
  todayNewsItems: [],
  todayNewsLabels: {},
  todayNewsCrawledAt: null,
  marketMapData: null,
  marketMapMarket: "KR",
  marketMapGroup: "KOSPI",
  marketMapSector: "all",
  marketMapColor: "change_pct",
  marketMapSize: "market_cap",
  marketMapLimit: 500,
  marketMapSearch: "",
  marketMapSelected: null,
  portfolioData: null,
  portfolioDefaultData: null,
  portfolioUsingLocal: false,
  portfolioSelectedCode: null,
  portfolioModalMode: "detail",
  pendingDetailMode: null,
  pendingDetailSearch: ""
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

function formatSignedPercent(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }

  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value, digits)}%`;
}

function formatSignedYears(value) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value}년`;
}

function formatPrice(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }

  return `${formatInteger(value)}원`;
}

function formatYears(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }

  return `${formatNumber(value, 1)}년`;
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

function formatCompactDate(value) {
  if (!value) {
    return "N/A";
  }

  const normalized = String(value).trim();
  if (/^\d{8}$/.test(normalized)) {
    return `${normalized.slice(0, 4)}.${normalized.slice(4, 6)}.${normalized.slice(6, 8)}`;
  }

  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) {
    return normalized;
  }

  return date.toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  });
}

function formatCompactDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return formatCompactDate(value);
  }

  return date.toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Seoul"
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function summarizeReporterNames(names, limit = 2) {
  if (!names.length) {
    return "공시 없음";
  }
  if (names.length <= limit) {
    return names.join(", ");
  }
  return `${names.slice(0, limit).join(", ")} 외 ${names.length - limit}명`;
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

  const dateText = date.toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "Asia/Seoul"
  });
  const timeText = date.toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Seoul"
  });
  node.replaceChildren();
  const dateNode = document.createElement("span");
  dateNode.className = "last-updated-date";
  dateNode.textContent = dateText;
  const timeNode = document.createElement("small");
  timeNode.className = "last-updated-time";
  timeNode.textContent = `${timeText} KST`;
  node.append(dateNode, timeNode);
}

function formatTickerDate(value) {
  if (!value) {
    return "N/A";
  }

  const normalized = String(value).replaceAll("-", "");
  if (/^\d{8}$/.test(normalized)) {
    return `${normalized.slice(4, 6)}.${normalized.slice(6, 8)}`;
  }
  return escapeHtml(value);
}

function orderTreasuryYields(koreaYields, usYields) {
  const allMonths = new Set(
    [...koreaYields, ...usYields]
      .map((item) => Number(item?.months))
      .filter((months) => !Number.isNaN(months))
  );
  const orderedMonths = [...allMonths].sort((left, right) => {
    const leftIsAnnual = left >= 12;
    const rightIsAnnual = right >= 12;
    if (leftIsAnnual !== rightIsAnnual) {
      return leftIsAnnual ? -1 : 1;
    }
    return left - right;
  });

  return orderedMonths.flatMap((months) => [
    ...koreaYields
      .filter((item) => Number(item?.months) === months)
      .map((item) => ({ item, countryCode: "KR" })),
    ...usYields
      .filter((item) => Number(item?.months) === months)
      .map((item) => ({ item, countryCode: "US" }))
  ]);
}

function fillLoopingTicker(track, items, secondsPerItem = 4.5) {
  const segment = `
    <div class="rate-ticker-segment">
      ${items.join("<span class='rate-ticker-divider' aria-hidden='true'>•</span>")}
      <span class="rate-ticker-divider market-divider" aria-hidden="true">◆</span>
    </div>
  `;

  track.classList.remove("is-static");
  track.style.setProperty(
    "--ticker-duration",
    `${Math.max(40, items.length * secondsPerItem)}s`
  );
  track.innerHTML = `${segment}${segment.replace(
    'class="rate-ticker-segment"',
    'class="rate-ticker-segment" aria-hidden="true"'
  )}`;
}

function renderRateTicker(payload) {
  const track = document.getElementById("rate-ticker-track");
  const dateNode = document.getElementById("rate-ticker-date");
  const korea = payload?.markets?.korea;
  const unitedStates = payload?.markets?.united_states;
  const koreaYields = Array.isArray(korea?.yields) ? korea.yields : [];
  const usYields = Array.isArray(unitedStates?.yields) ? unitedStates.yields : [];

  const renderYield = (item, countryCode) => {
    const value = Number(item?.value);
    const change = item?.change === null || item?.change === undefined
      ? null
      : Number(item.change);
    const hasChange = change !== null && !Number.isNaN(change);
    const direction = !hasChange || change === 0
      ? "is-flat"
      : change > 0
        ? "is-up"
        : "is-down";
    const changeText = !hasChange
      ? ""
      : change > 0
        ? `▲ +${formatNumber(change, 2)}`
        : change < 0
          ? `▼ ${formatNumber(change, 2)}`
          : "— 0.00";

    return `
      <span class="rate-ticker-item ${direction}">
        <span class="rate-country">${countryCode}</span>
        <span class="rate-maturity">${escapeHtml(item?.label || item?.maturity || "")}</span>
        <strong>${Number.isNaN(value) ? "N/A" : `${formatNumber(value, 2)}%`}</strong>
        ${changeText ? `<span class="rate-change">${changeText}</span>` : ""}
      </span>
    `;
  };

  const items = orderTreasuryYields(koreaYields, usYields)
    .map(({ item, countryCode }) => renderYield(item, countryCode));

  if (!items.length) {
    track.innerHTML = "<div class='rate-ticker-loading'>표시할 국채 금리 데이터가 없습니다.</div>";
    track.classList.add("is-static");
    dateNode.textContent = "No data";
    return;
  }

  fillLoopingTicker(track, items);
  dateNode.textContent = `KR ${formatTickerDate(korea?.as_of_date)} · US ${formatTickerDate(unitedStates?.as_of_date)}`;
}

async function loadTreasuryTicker() {
  const track = document.getElementById("rate-ticker-track");
  const dateNode = document.getElementById("rate-ticker-date");

  try {
    const response = await fetch(TREASURY_YIELDS_URL, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} for treasury yields`);
    }
    renderRateTicker(await response.json());
  } catch (error) {
    track.classList.add("is-static");
    track.innerHTML = "<div class='rate-ticker-loading'>국채 금리 데이터를 불러오지 못했습니다.</div>";
    dateNode.textContent = "Unavailable";
    console.error(error);
  }
}

function renderEtfBrandTicker(payload, brand, trackId, dateId) {
  const track = document.getElementById(trackId);
  const dateNode = document.getElementById(dateId);
  const brandData = (payload?.brands || []).find(
    (item) => String(item?.brand || "").toLocaleLowerCase() === brand.toLocaleLowerCase()
  );
  const etfs = Array.isArray(brandData?.etfs) ? brandData.etfs : [];

  if (!etfs.length) {
    track.classList.add("is-static");
    track.innerHTML = `<div class="rate-ticker-loading">${escapeHtml(brand)} ETF 데이터가 없습니다.</div>`;
    dateNode.textContent = "No data";
    return;
  }

  const items = etfs.map((item) => {
    const changeRate = Number(item?.change_rate);
    const direction = Number.isNaN(changeRate) || changeRate === 0
      ? "is-flat"
      : changeRate > 0
        ? "is-up"
        : "is-down";
    const changeText = Number.isNaN(changeRate)
      ? "N/A"
      : changeRate > 0
        ? `▲ +${formatNumber(changeRate, 2)}%`
        : changeRate < 0
          ? `▼ ${formatNumber(changeRate, 2)}%`
          : "— 0.00%";
    const code = encodeURIComponent(String(item?.code || ""));

    return `
      <a
        class="rate-ticker-item etf-ticker-item ${direction}"
        href="https://finance.naver.com/item/main.naver?code=${code}"
        target="_blank"
        rel="noopener noreferrer"
      >
        <span class="rate-maturity">${escapeHtml(item?.short_name || item?.name || "")}</span>
        <strong>${formatInteger(Number(item?.current_price))}원</strong>
        <span class="rate-change">${changeText}</span>
      </a>
    `;
  });

  fillLoopingTicker(track, items, 3);
  dateNode.textContent = `Naver · ${etfs.length}개`;
}

async function loadEtfBrandTickers() {
  try {
    const response = await fetch(ETF_BRANDS_URL, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} for ETF brands`);
    }
    const payload = await response.json();
    renderEtfBrandTicker(
      payload,
      "KoAct",
      "koact-etf-ticker-track",
      "koact-etf-ticker-date"
    );
    renderEtfBrandTicker(
      payload,
      "TIME",
      "time-etf-ticker-track",
      "time-etf-ticker-date"
    );
  } catch (error) {
    [
      ["koact-etf-ticker-track", "koact-etf-ticker-date", "KoAct"],
      ["time-etf-ticker-track", "time-etf-ticker-date", "TIME"]
    ].forEach(([trackId, dateId, brand]) => {
      const track = document.getElementById(trackId);
      track.classList.add("is-static");
      track.innerHTML = `<div class="rate-ticker-loading">${brand} ETF 데이터를 불러오지 못했습니다.</div>`;
      document.getElementById(dateId).textContent = "Unavailable";
    });
    console.error(error);
  }
}

function marketTone(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number === 0) {
    return "market-tone-flat";
  }
  return number > 0 ? "market-tone-up" : "market-tone-down";
}

function formatMarketAssetValue(asset, value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "N/A";
  }
  const digits = Number(asset?.decimals ?? 2);
  const prefix = asset?.group === "Crypto" ? "$" : "";
  return `${prefix}${formatNumber(number, digits)}`;
}

function marketHistoryForRange(history, range) {
  if (!Array.isArray(history) || !history.length || range === "2y") {
    return Array.isArray(history) ? history : [];
  }
  const daysByRange = {
    "1m": 31,
    "3m": 93,
    "6m": 186,
    "1y": 366
  };
  const days = daysByRange[range] || 93;
  const lastDate = new Date(`${history.at(-1).date}T00:00:00Z`);
  if (Number.isNaN(lastDate.getTime())) {
    return history;
  }
  const cutoff = lastDate.getTime() - days * 86400000;
  const filtered = history.filter((row) => {
    const time = new Date(`${row.date}T00:00:00Z`).getTime();
    return Number.isFinite(time) && time >= cutoff;
  });
  return filtered.length >= 2 ? filtered : history.slice(-2);
}

function marketSparkline(history, change) {
  const rows = marketHistoryForRange(history, "3m");
  const closes = rows
    .map((row) => Number(row.close))
    .filter(Number.isFinite);
  if (closes.length < 2) {
    return "";
  }
  const width = 92;
  const height = 46;
  const pad = 3;
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = Math.max(max - min, 0.0001);
  const points = closes.map((value, index) => {
    const x = pad + index / (closes.length - 1) * (width - pad * 2);
    const y = pad + (max - value) / range * (height - pad * 2);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  const areaPoints = `${pad},${height - pad} ${points} ${width - pad},${height - pad}`;
  const numericChange = Number(change);
  const color = numericChange > 0
    ? "#d8483f"
    : numericChange < 0
      ? "#3478c7"
      : "#83776a";
  return `
    <svg class="market-sparkline" viewBox="0 0 ${width} ${height}" aria-hidden="true">
      <polygon points="${areaPoints}" fill="${color}" fill-opacity=".09"></polygon>
      <polyline points="${points}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"></polyline>
    </svg>
  `;
}

function renderMarketOverviewCards() {
  const container = document.getElementById("market-overview-cards");
  if (!state.marketAssets.length) {
    container.innerHTML = "<div class='market-overview-loading'>표시할 시장 차트 데이터가 없습니다.</div>";
    return;
  }
  if (
    state.selectedMarketAsset
    && !state.marketAssets.some((asset) => asset.id === state.selectedMarketAsset)
  ) {
    state.selectedMarketAsset = null;
  }
  container.innerHTML = state.marketAssets.map((asset) => {
    const tone = marketTone(asset.change_pct);
    const cardTone = Number(asset.change_pct) > 0
      ? "market-card-up"
      : Number(asset.change_pct) < 0
        ? "market-card-down"
        : "market-card-flat";
    const direction = Number(asset.change_pct) > 0
      ? "▲"
      : Number(asset.change_pct) < 0
        ? "▼"
        : "—";
    return `
      <button
        class="market-asset-card ${cardTone} ${asset.id === state.selectedMarketAsset ? "is-selected" : ""}"
        type="button"
        data-market-asset="${escapeHtml(asset.id)}"
        aria-pressed="${asset.id === state.selectedMarketAsset ? "true" : "false"}"
        aria-label="${escapeHtml(asset.name)} ${escapeHtml(formatMarketAssetValue(asset, asset.current))}, ${direction} ${escapeHtml(formatSignedPercent(asset.change_pct, 2))}. 상세 차트 ${asset.id === state.selectedMarketAsset ? "닫기" : "열기"}"
      >
        <span class="market-asset-main">
          <span class="market-asset-label">${escapeHtml(asset.name)}</span>
          <span class="market-asset-value">${escapeHtml(formatMarketAssetValue(asset, asset.current))}</span>
          <span class="market-asset-change ${tone}">${direction} ${escapeHtml(formatSignedPercent(asset.change_pct, 2))}</span>
        </span>
        ${marketSparkline(asset.history, asset.change_pct)}
      </button>
    `;
  }).join("");
}

function renderMarketMainChart() {
  const asset = state.marketAssets.find(
    (item) => item.id === state.selectedMarketAsset
  );
  const shell = document.getElementById("market-chart-shell");
  const summary = document.getElementById("market-chart-summary");
  const container = document.getElementById("market-index-chart");
  if (!asset) {
    shell.hidden = true;
    summary.innerHTML = "";
    container.innerHTML = "";
    return;
  }
  shell.hidden = false;
  const rows = marketHistoryForRange(asset.history, state.marketChartRange);
  const closes = rows.map((row) => Number(row.close)).filter(Number.isFinite);
  if (closes.length < 2) {
    summary.innerHTML = "";
    container.innerHTML = "<div class='market-overview-loading'>유효한 차트 이력이 없습니다.</div>";
    return;
  }
  const periodReturn = closes[0]
    ? (closes.at(-1) / closes[0] - 1) * 100
    : null;
  const tone = marketTone(periodReturn);
  summary.innerHTML = `
    <p class="section-kicker">${escapeHtml(asset.group || "")} · ${escapeHtml(asset.symbol || "")}</p>
    <h3>${escapeHtml(asset.name)} <span class="${tone}">${escapeHtml(state.marketChartRange.toUpperCase())}</span></h3>
    <div class="market-chart-summary-line">
      <strong>${escapeHtml(formatMarketAssetValue(asset, closes.at(-1)))}</strong>
      <span class="${tone}">${escapeHtml(formatSignedPercent(periodReturn, 2))}</span>
    </div>
  `;

  const compactChart = window.matchMedia("(max-width: 640px)").matches;
  const width = compactChart ? 360 : 1120;
  const height = compactChart ? 220 : 300;
  const pad = compactChart
    ? { left: 48, right: 10, top: 14, bottom: 26 }
    : { left: 62, right: 18, top: 18, bottom: 30 };
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const valueRange = Math.max(max - min, 0.0001);
  const x = (index) => pad.left
    + index / Math.max(closes.length - 1, 1) * (width - pad.left - pad.right);
  const y = (value) => pad.top
    + (max - value) / valueRange * (height - pad.top - pad.bottom);
  const points = closes.map(
    (value, index) => `${x(index).toFixed(2)},${y(value).toFixed(2)}`
  ).join(" ");
  const bottom = height - pad.bottom;
  const color = periodReturn > 0
    ? "#d8483f"
    : periodReturn < 0
      ? "#3478c7"
      : "#83776a";
  const fillId = `market-fill-${escapeHtml(asset.id)}`;
  const firstDate = formatCompactDate(rows[0]?.date);
  const lastDate = formatCompactDate(rows.at(-1)?.date);
  const mid = min + valueRange / 2;
  container.innerHTML = `
    <svg class="market-main-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(asset.name)} ${escapeHtml(state.marketChartRange)} 가격 차트">
      <defs>
        <linearGradient id="${fillId}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="${color}" stop-opacity=".24"></stop>
          <stop offset="1" stop-color="${color}" stop-opacity=".02"></stop>
        </linearGradient>
      </defs>
      <polygon points="${pad.left},${bottom} ${points} ${width - pad.right},${bottom}" fill="url(#${fillId})"></polygon>
      <polyline points="${points}" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
      <text class="market-chart-axis" x="${pad.left - 8}" y="${pad.top + 4}" text-anchor="end">${escapeHtml(formatMarketAssetValue(asset, max))}</text>
      <text class="market-chart-axis" x="${pad.left - 8}" y="${y(mid) + 4}" text-anchor="end">${escapeHtml(formatMarketAssetValue(asset, mid))}</text>
      <text class="market-chart-axis" x="${pad.left - 8}" y="${bottom}" text-anchor="end">${escapeHtml(formatMarketAssetValue(asset, min))}</text>
      <text class="market-chart-axis" x="${pad.left}" y="${height - 8}">${escapeHtml(firstDate)}</text>
      <text class="market-chart-axis" x="${width - pad.right}" y="${height - 8}" text-anchor="end">${escapeHtml(lastDate)}</text>
    </svg>
  `;
}

function renderMarketOverview() {
  renderMarketOverviewCards();
  renderMarketMainChart();
  document.querySelectorAll("[data-market-range]").forEach((button) => {
    button.classList.toggle(
      "is-active",
      button.dataset.marketRange === state.marketChartRange
    );
  });
}

function bindMarketOverview() {
  document.getElementById("market-overview-cards")?.addEventListener("click", (event) => {
    const card = event.target.closest("[data-market-asset]");
    if (!card) {
      return;
    }
    state.selectedMarketAsset = state.selectedMarketAsset === card.dataset.marketAsset
      ? null
      : card.dataset.marketAsset;
    renderMarketOverview();
  });
  document.querySelectorAll("[data-market-range]").forEach((button) => {
    button.addEventListener("click", () => {
      state.marketChartRange = button.dataset.marketRange;
      renderMarketOverview();
    });
  });
  const compactMarketChart = window.matchMedia("(max-width: 640px)");
  compactMarketChart.addEventListener?.("change", () => {
    if (state.selectedMarketAsset) {
      renderMarketMainChart();
    }
  });
}

async function loadMarketOverview() {
  try {
    const response = await fetch(`${MARKET_INDICES_URL}?v=${Date.now()}`, {
      cache: "no-store"
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} for market indices`);
    }
    const payload = await response.json();
    state.marketAssets = Array.isArray(payload.assets) ? payload.assets : [];
    const updated = new Date(payload.crawled_at_utc);
    document.getElementById("market-overview-updated").textContent =
      Number.isNaN(updated.getTime())
        ? "갱신일 확인 불가"
        : `${updated.toLocaleString("ko-KR")} 갱신`;
    renderMarketOverview();
  } catch (error) {
    document.getElementById("market-overview-cards").innerHTML =
      "<div class='market-overview-loading'>시장 차트 데이터를 불러오지 못했습니다.</div>";
    document.getElementById("market-chart-shell").hidden = true;
    document.getElementById("market-overview-updated").textContent = "Unavailable";
    console.error(error);
  }
}

function screenStatusLabel(status) {
  if (status === "pass") return "통과";
  if (status === "fail") return "탈락";
  return "판정 대기";
}

function confidenceLabel(value) {
  if (value === "high") return "높음";
  if (value === "medium") return "중간";
  return "낮음";
}

function marketMapGroupOptions(market) {
  if (market === "KR") {
    return [
      ["all", "한국 전체"],
      ["KOSPI", "코스피"],
      ["KOSDAQ", "코스닥"],
      ["top100", "시가총액 상위 100"],
      ["top200", "시가총액 상위 200"]
    ];
  }
  return [
    ["all", "미국 전체"],
    ["top100", "시가총액 상위 100"],
    ["top500", "시가총액 상위 500"],
    ["mega", "메가캡 · $200B 이상"],
    ["large", "대형주 · $10B 이상"]
  ];
}

function marketMapColorOptions(market) {
  if (market === "KR") {
    return [
      ["change_pct", "당일 등락률"],
      ["roe", "ROE"],
      ["foreigner_ratio", "외국인 보유율"]
    ];
  }
  return [
    ["change_pct", "당일 등락률"],
    ["return_1m", "1개월 수익률"],
    ["rsi14", "RSI(14)"]
  ];
}

function setSelectOptions(select, options, selectedValue) {
  if (!select) {
    return selectedValue;
  }
  select.innerHTML = options.map(([value, label]) => `
    <option value="${escapeHtml(value)}">${escapeHtml(label)}</option>
  `).join("");
  const available = options.some(([value]) => value === selectedValue);
  select.value = available ? selectedValue : options[0]?.[0] || "";
  return select.value;
}

function marketMapAllStocks() {
  return state.marketMapData?.markets?.[state.marketMapMarket]?.stocks || [];
}

const KOREA_MARKET_MAP_SECTOR_RULES = [
  ["정보기술", ["반도체", "전자", "디스플레이", "컴퓨터", "소프트웨어", "IT서비스", "통신장비", "핸드셋"]],
  ["헬스케어", ["제약", "바이오", "생물공학", "생명과학", "건강관리", "의료"]],
  ["금융", ["은행", "증권", "보험", "카드", "캐피탈", "금융", "창업투자"]],
  ["산업재", ["조선", "기계", "건설", "우주항공", "운송", "철도", "무역", "상업서비스", "전기장비", "전기제품", "복합기업", "항공사", "해운사", "건축제품"]],
  ["경기소비재", ["자동차", "화장품", "호텔", "레저", "백화점", "소매", "가정용", "섬유", "의류", "교육", "미디어", "엔터", "게임", "가구", "판매업체"]],
  ["필수소비재", ["식품", "음료", "담배", "생활용품"]],
  ["커뮤니케이션", ["통신서비스", "방송", "광고", "인터넷", "출판"]],
  ["소재", ["화학", "철강", "비철금속", "건축자재", "종이", "목재", "포장재"]],
  ["에너지", ["에너지", "석유", "가스"]],
  ["유틸리티", ["전기유틸리티", "가스유틸리티", "복합유틸리티"]],
  ["부동산", ["부동산", "리츠"]]
];

function marketMapKoreaBroadSector(industry) {
  const normalized = String(industry || "").replace(/\s+/g, "");
  if (!normalized || normalized === "기타") {
    return "기타";
  }
  const match = KOREA_MARKET_MAP_SECTOR_RULES.find(([, keywords]) =>
    keywords.some((keyword) => normalized.includes(keyword))
  );
  return match?.[0] || "기타";
}

function marketMapHierarchy(stock) {
  if (stock.market === "KR") {
    const industry = stock.industry || stock.sector || "기타";
    return {
      sector: stock.industry ? (stock.sector || "기타") : marketMapKoreaBroadSector(industry),
      industry
    };
  }
  return {
    sector: stock.sector || "Other",
    industry: stock.industry || "Other"
  };
}

function marketMapGroupStocks() {
  const stocks = marketMapAllStocks()
    .filter((stock) => Number.isFinite(Number(stock.market_cap)))
    .sort((a, b) => Number(b.market_cap) - Number(a.market_cap));
  const group = state.marketMapGroup;
  if (state.marketMapMarket === "KR") {
    if (group === "KOSPI" || group === "KOSDAQ") {
      return stocks.filter((stock) => stock.group === group);
    }
    if (group === "top100" || group === "top200") {
      return stocks.slice(0, group === "top100" ? 100 : 200);
    }
    return stocks;
  }
  if (group === "top100" || group === "top500") {
    return stocks.slice(0, group === "top100" ? 100 : 500);
  }
  if (group === "mega") {
    return stocks.filter((stock) => Number(stock.market_cap) >= 200e9);
  }
  if (group === "large") {
    return stocks.filter((stock) => Number(stock.market_cap) >= 10e9);
  }
  return stocks;
}

function renderMarketMapFilterOptions() {
  state.marketMapGroup = setSelectOptions(
    document.getElementById("market-map-group"),
    marketMapGroupOptions(state.marketMapMarket),
    state.marketMapGroup
  );
  state.marketMapColor = setSelectOptions(
    document.getElementById("market-map-color"),
    marketMapColorOptions(state.marketMapMarket),
    state.marketMapColor
  );
  const sectors = Array.from(
    new Set(marketMapGroupStocks().map((stock) => marketMapHierarchy(stock).sector))
  ).sort((a, b) => a.localeCompare(b, state.marketMapMarket === "KR" ? "ko" : "en"));
  state.marketMapSector = setSelectOptions(
    document.getElementById("market-map-sector"),
    [["all", "전체 섹터"], ...sectors.map((sector) => [sector, sector])],
    state.marketMapSector
  );
}

function filteredMarketMapStocks() {
  const search = state.marketMapSearch.trim().toLocaleLowerCase();
  return marketMapGroupStocks()
    .filter((stock) =>
      state.marketMapSector === "all"
      || marketMapHierarchy(stock).sector === state.marketMapSector
    )
    .filter((stock) => {
      if (!search) {
        return true;
      }
      const hierarchy = marketMapHierarchy(stock);
      return [stock.symbol, stock.name, hierarchy.sector, hierarchy.industry]
        .some((value) => String(value || "").toLocaleLowerCase().includes(search));
    });
}

function marketMapMetricConfig() {
  const configs = {
    change_pct: { label: "당일", center: 0, scale: 6, digits: 2, suffix: "%" },
    return_1m: { label: "1개월", center: 0, scale: 20, digits: 1, suffix: "%" },
    rsi14: { label: "RSI", center: 50, scale: 30, digits: 1, suffix: "" },
    roe: { label: "ROE", center: 0, scale: 25, digits: 1, suffix: "%" },
    foreigner_ratio: {
      label: "외국인",
      center: 20,
      scale: 25,
      digits: 1,
      suffix: "%"
    }
  };
  return configs[state.marketMapColor] || configs.change_pct;
}

function marketMapMetricValue(stock) {
  const value = Number(stock?.[state.marketMapColor]);
  return Number.isFinite(value) ? value : null;
}

function marketMapMetricText(stock) {
  const value = marketMapMetricValue(stock);
  if (value === null) {
    return "N/A";
  }
  const config = marketMapMetricConfig();
  const sign = value > 0 && ["change_pct", "return_1m", "roe"].includes(state.marketMapColor)
    ? "+"
    : "";
  return `${sign}${formatNumber(value, config.digits)}${config.suffix}`;
}

function marketMapTileStyle(stock) {
  const value = marketMapMetricValue(stock);
  const config = marketMapMetricConfig();
  if (value === null) {
    return "--map-tile-bg:#e9e2d8;--map-tile-color:#62584e;--map-tile-border:rgba(71,55,40,.12)";
  }
  const delta = (value - config.center) / config.scale;
  const intensity = Math.min(Math.abs(delta), 1);
  if (intensity < 0.05) {
    return "--map-tile-bg:#ddd5ca;--map-tile-color:#534a42;--map-tile-border:rgba(71,55,40,.14)";
  }
  const rising = delta > 0;
  const rgb = rising ? "216,72,63" : "52,120,199";
  const alpha = 0.28 + intensity * 0.64;
  return `--map-tile-bg:rgba(${rgb},${alpha.toFixed(3)});--map-tile-color:#fff;--map-tile-border:rgba(${rgb},.5)`;
}

function marketMapTileClass(index) {
  if (index < 3) {
    return "is-xl";
  }
  if (index < 12) {
    return "is-lg";
  }
  if (index < 30) {
    return "is-md";
  }
  return "is-sm";
}

function marketMapPrice(stock) {
  return stock.market === "KR"
    ? formatPrice(Number(stock.price))
    : `$${formatNumber(Number(stock.price), 2)}`;
}

function marketMapCap(stock) {
  return stock.market === "KR"
    ? formatMarketCap(Number(stock.market_cap))
    : formatUsdCompact(Number(stock.market_cap));
}

function formatMarketMapOptional(value, formatter) {
  if (value === null || value === undefined || value === "") {
    return "N/A";
  }
  const number = Number(value);
  return Number.isFinite(number) ? formatter(number) : "N/A";
}

const PORTFOLIO_POSITIONS = {
  ST: { x: 50, y: 12, label: "ST · 최전방 공격수", group: "attack" },
  CF: { x: 50, y: 18, label: "CF · 중앙 공격수", group: "attack" },
  SS: { x: 50, y: 23, label: "SS · 세컨드 스트라이커", group: "attack" },
  LF: { x: 32, y: 24, label: "LF · 왼쪽 포워드", group: "attack" },
  RF: { x: 68, y: 24, label: "RF · 오른쪽 포워드", group: "attack" },
  LWF: { x: 18, y: 27, label: "LWF · 왼쪽 윙포워드", group: "attack" },
  WF: { x: 50, y: 29, label: "WF · 윙포워드", group: "attack" },
  RWF: { x: 82, y: 27, label: "RWF · 오른쪽 윙포워드", group: "attack" },
  LW: { x: 18, y: 29, label: "LW · 왼쪽 공격수", group: "attack" },
  RW: { x: 82, y: 29, label: "RW · 오른쪽 공격수", group: "attack" },
  AM: { x: 50, y: 38, label: "AM · 공격형 미드필더", group: "midfield" },
  LAM: { x: 34, y: 40, label: "LAM · 왼쪽 공격형 미드필더", group: "midfield" },
  RAM: { x: 66, y: 40, label: "RAM · 오른쪽 공격형 미드필더", group: "midfield" },
  LM: { x: 18, y: 49, label: "LM · 왼쪽 미드필더", group: "midfield" },
  LCM: { x: 36, y: 52, label: "LCM · 왼쪽 중앙 미드필더", group: "midfield" },
  CM: { x: 50, y: 52, label: "CM · 중앙 미드필더", group: "midfield" },
  RCM: { x: 64, y: 52, label: "RCM · 오른쪽 중앙 미드필더", group: "midfield" },
  RM: { x: 82, y: 49, label: "RM · 오른쪽 미드필더", group: "midfield" },
  DM: { x: 50, y: 63, label: "DM · 수비형 미드필더", group: "midfield" },
  LDM: { x: 36, y: 63, label: "LDM · 왼쪽 수비형 미드필더", group: "midfield" },
  RDM: { x: 64, y: 63, label: "RDM · 오른쪽 수비형 미드필더", group: "midfield" },
  WB: { x: 50, y: 69, label: "WB · 윙백", group: "defense" },
  LWB: { x: 14, y: 67, label: "LWB · 왼쪽 윙백", group: "defense" },
  RWB: { x: 86, y: 67, label: "RWB · 오른쪽 윙백", group: "defense" },
  LB: { x: 14, y: 75, label: "LB · 왼쪽 수비수", group: "defense" },
  LCB: { x: 36, y: 76, label: "LCB · 왼쪽 센터백", group: "defense" },
  CB: { x: 50, y: 75, label: "CB · 중앙 수비수", group: "defense" },
  RCB: { x: 64, y: 76, label: "RCB · 오른쪽 센터백", group: "defense" },
  RB: { x: 86, y: 75, label: "RB · 오른쪽 수비수", group: "defense" },
  SW: { x: 50, y: 84, label: "SW · 스위퍼", group: "defense" },
  GK: { x: 50, y: 92, label: "GK · 골키퍼", group: "goalkeeper" }
};

const PORTFOLIO_POSITION_ALIASES = {
  CAM: "AM",
  CDM: "DM",
  RL: "RM",
  FW: "CF",
  FWD: "CF",
  WG: "WF",
  MF: "CM",
  DF: "CB",
  FB: "CB",
  G: "GK",
  GOALKEEPER: "GK",
  공격수: "ST",
  미드필더: "CM",
  수비수: "CB",
  골키퍼: "GK"
};

function clonePortfolioData(payload) {
  return JSON.parse(JSON.stringify(payload));
}

function normalizePortfolioPosition(value) {
  const raw = String(value || "CM").trim().toUpperCase();
  const normalized = PORTFOLIO_POSITION_ALIASES[raw] || raw;
  return PORTFOLIO_POSITIONS[normalized] ? normalized : "CM";
}

function portfolioPositionCoordinates(holding, occurrence, total) {
  const position = normalizePortfolioPosition(holding.position);
  const base = PORTFOLIO_POSITIONS[position];
  const spacing = position === "GK" ? 8 : 13;
  const xOffset = (occurrence - ((total - 1) / 2)) * spacing;
  return {
    position,
    x: clamp(base.x + xOffset, 9, 91),
    y: base.y,
    label: base.label,
    group: base.group
  };
}

function portfolioLayoutHoldings(holdings) {
  const totals = new Map();
  holdings.forEach((holding) => {
    const position = normalizePortfolioPosition(holding.position);
    totals.set(position, (totals.get(position) || 0) + 1);
  });
  const occurrences = new Map();
  return holdings.map((holding) => {
    const position = normalizePortfolioPosition(holding.position);
    const occurrence = occurrences.get(position) || 0;
    occurrences.set(position, occurrence + 1);
    return {
      ...holding,
      layout: portfolioPositionCoordinates(holding, occurrence, totals.get(position) || 1)
    };
  });
}

function portfolioScenarioReturn(stock, scenario, years) {
  const fairPriceKeys = {
    conservative: "fairPriceConservative",
    base: "fairPriceBase",
    optimistic: "fairPriceOptimistic"
  };
  const currentPrice = Number(stock?.current_price);
  const fairPrice = Number(stock?.[fairPriceKeys[scenario]]);
  const annualDividend = Math.max(0, Number(stock?.dividend) || 0);
  if (!(currentPrice > 0) || !(fairPrice > 0) || !(years > 0)) {
    return null;
  }
  const terminalValue = fairPrice + annualDividend * years;
  return ((terminalValue / currentPrice) ** (1 / years) - 1) * 100;
}

function portfolioExpectedReturn(holdings, stocks, scenario, years) {
  let weightedReturn = 0;
  let coveredWeight = 0;
  holdings.forEach((holding) => {
    const weight = Number(holding.weight_pct);
    const expectedReturn = holding.type === "cash"
      ? 0
      : portfolioScenarioReturn(stocks.get(holding.code), scenario, years);
    if (expectedReturn === null || !Number.isFinite(weight) || weight <= 0) {
      return;
    }
    weightedReturn += expectedReturn * weight;
    coveredWeight += weight;
  });
  return coveredWeight > 0 ? weightedReturn / coveredWeight : null;
}

function portfolioScenarioMarkup(label, value, scenario) {
  return `
    <div class="portfolio-return-card is-${scenario}">
      <span>${escapeHtml(label)}</span>
      <strong class="${marketTone(value)}">${formatSignedPercent(value, 1)}</strong>
      <small>연환산</small>
    </div>
  `;
}

function portfolioNamesByGroup(holdings, group) {
  const names = holdings
    .filter((holding) => holding.layout.group === group)
    .map((holding) => holding.name);
  return names.length ? names.join(" · ") : "비어 있음";
}

function portfolioTextMarkup(value) {
  if (!value) {
    return '<span class="portfolio-note-empty">아직 입력하지 않았습니다.</span>';
  }
  return escapeHtml(value).replace(/\n/g, "<br>");
}

function portfolioCrestTheme(code, name, type) {
  if (type === "cash" || code === "CASH") return "cash";
  const known = {
    "042700": "hanmi",
    "000660": "hynix",
    "214450": "pharma",
    "383220": "fnf",
    "138040": "meritz",
    "005930": "samsung"
  };
  return known[code] || (String(name || "").length <= 4 ? "compact" : "default");
}

function portfolioMark(code, name, type) {
  if (type === "cash" || code === "CASH") return "CASH";
  return String(name || code || "?").replace(/\s+/g, "").slice(0, 5);
}

function renderPortfolioBoard() {
  const container = document.getElementById("portfolio-board");
  const payload = state.portfolioData;
  if (!container || !payload) {
    return;
  }
  const holdings = portfolioLayoutHoldings(Array.isArray(payload.holdings) ? payload.holdings : []);
  const stockHoldings = holdings.filter((holding) => holding.type !== "cash");
  const cashHolding = holdings.find((holding) => holding.type === "cash");
  const rawByCode = new Map(state.rawStocks.map((stock) => [stock.code, stock]));
  const enrichedByCode = new Map();
  stockHoldings.forEach((holding) => {
    const rawStock = rawByCode.get(holding.code);
    if (rawStock) {
      enrichedByCode.set(holding.code, enrichStock(rawStock));
    }
  });
  const convergenceYears = Number(payload.convergence_years) || 3;
  const conservative = portfolioExpectedReturn(holdings, enrichedByCode, "conservative", convergenceYears);
  const base = portfolioExpectedReturn(holdings, enrichedByCode, "base", convergenceYears);
  const optimistic = portfolioExpectedReturn(holdings, enrichedByCode, "optimistic", convergenceYears);
  const covered = stockHoldings.filter((holding) => enrichedByCode.has(holding.code)).length;
  const changes = Array.isArray(payload.changes) ? payload.changes.slice(0, 3) : [];
  const stockWeight = stockHoldings.reduce((sum, holding) => sum + (Number(holding.weight_pct) || 0), 0);
  const cashWeight = Number(cashHolding?.weight_pct) || 0;

  container.innerHTML = `
    <div class="portfolio-head">
      <div>
        <p class="section-kicker">Portfolio Tactics</p>
        <h2 id="portfolio-board-title">${escapeHtml(payload.title || "나의 포트폴리오")}</h2>
        <p>ST·CF·SS·WF·AM·CM·LM·RM·DM·WB·CB·SW·GK 등 포지션을 입력하면 전술판의 표준 위치에 자동 배치합니다. 같은 포지션은 서로 겹치지 않게 펼쳐집니다.</p>
      </div>
      <div class="portfolio-head-side">
        <div class="portfolio-head-meta">
          <span>${escapeHtml(payload.formation || "자유 전술")}</span>
          <strong>${stockHoldings.length}종목 + ${cashHolding ? "GK" : "현금 없음"}</strong>
          <small>${state.portfolioUsingLocal ? "이 브라우저의 편집값 적용 중" : "공개 JSON 기본값"}</small>
        </div>
        <div class="portfolio-head-actions">
          <button type="button" data-portfolio-add>+ 종목 추가</button>
          <button type="button" data-portfolio-export>JSON 내보내기</button>
          ${state.portfolioUsingLocal ? '<button type="button" data-portfolio-reset>공개 기본값 복원</button>' : ""}
        </div>
      </div>
    </div>

    <div class="portfolio-kpis">
      <div><span>보유 종목</span><strong>${stockHoldings.length}개</strong><small>현금은 별도 GK</small></div>
      <div><span>현재 배분</span><strong>주식 ${formatNumber(stockWeight, 1)}%</strong><small>현금 ${formatNumber(cashWeight, 1)}%</small></div>
      <div><span>수익률 산출</span><strong>${covered}/${stockHoldings.length}</strong><small>가치평가 연결 종목</small></div>
      <div><span>수렴 기간</span><strong>${convergenceYears}년</strong><small>적정가 도달 가정</small></div>
    </div>

    <div class="portfolio-layout">
      <div class="portfolio-pitch" aria-label="포트폴리오 축구 전술판">
        <span class="portfolio-pitch-halfway" aria-hidden="true"></span>
        <span class="portfolio-pitch-circle" aria-hidden="true"></span>
        <span class="portfolio-pitch-box is-top" aria-hidden="true"></span>
        <span class="portfolio-pitch-box is-bottom" aria-hidden="true"></span>
        ${holdings.map((holding) => `
          <button
            type="button"
            class="portfolio-player"
            style="--player-x:${holding.layout.x}%;--player-y:${holding.layout.y}%"
            data-portfolio-code="${escapeHtml(holding.code)}"
            aria-label="${escapeHtml(`${holding.name} 투자 노트 보기`)}"
          >
            <span class="portfolio-position-chip">${escapeHtml(holding.layout.position)}</span>
            <span class="portfolio-crest is-${escapeHtml(holding.crest_theme || "default")}">
              ${escapeHtml(holding.mark || holding.name)}
            </span>
            <span class="portfolio-player-card">
              <strong>${escapeHtml(holding.name)}</strong>
              <small>${escapeHtml(holding.role || holding.layout.label)}</small>
              <em>${formatPercent(Number(holding.weight_pct), 1)}</em>
            </span>
          </button>
        `).join("")}
      </div>

      <aside class="portfolio-tactics">
        <div class="portfolio-tactics-card">
          <p>전술 포인트</p>
          <h3>사용자가 정한 역할로 읽는 포트폴리오</h3>
          <ul>
            <li><span>공격</span><strong>${escapeHtml(portfolioNamesByGroup(holdings, "attack"))}</strong></li>
            <li><span>미드필드</span><strong>${escapeHtml(portfolioNamesByGroup(holdings, "midfield"))}</strong></li>
            <li><span>수비</span><strong>${escapeHtml(portfolioNamesByGroup(holdings, "defense"))}</strong></li>
            <li><span>골키퍼</span><strong>${escapeHtml(portfolioNamesByGroup(holdings, "goalkeeper"))}</strong></li>
          </ul>
        </div>
        <div class="portfolio-tactics-card is-change">
          <p>구성 및 변동 사항</p>
          ${changes.length ? changes.map((change) => `
            <div class="portfolio-change-row">
              <span>${escapeHtml(change.type || "변동")}</span>
              <strong>${escapeHtml(change.reason || "-")}</strong>
              <small>${escapeHtml(change.date || "")}</small>
            </div>
          `).join("") : '<div class="portfolio-change-row"><strong>기록된 변동이 없습니다.</strong></div>'}
        </div>
      </aside>
    </div>

    <div class="portfolio-return-section">
      <div class="portfolio-return-copy">
        <p>Annualized Expectation</p>
        <h3>연간 기대수익률</h3>
        <span>${convergenceYears}년 안에 현재 적정가 시나리오로 수렴하고 현재 배당이 유지된다는 가정입니다.</span>
      </div>
      <div class="portfolio-return-grid">
        ${portfolioScenarioMarkup("약세", conservative, "bear")}
        ${portfolioScenarioMarkup("기준", base, "base")}
        ${portfolioScenarioMarkup("강세", optimistic, "bull")}
      </div>
    </div>
    <p class="portfolio-disclaimer">브라우저에서 수정한 내용은 이 기기에만 저장됩니다. JSON 내보내기 파일을 공개 저장소의 data/portfolio.json에 반영하면 모든 기기에 공개할 수 있습니다.</p>
  `;
}

function portfolioHoldingByCode(code) {
  return state.portfolioData?.holdings?.find((holding) => holding.code === code) || null;
}

function closePortfolioModal() {
  const modal = document.getElementById("portfolio-modal");
  if (modal) modal.hidden = true;
  state.portfolioSelectedCode = null;
  state.portfolioModalMode = "detail";
  document.body.classList.remove("market-map-modal-open");
}

function renderPortfolioNoteCard(title, value, key) {
  return `
    <section class="portfolio-note-card is-${key}">
      <h4>${escapeHtml(title)}</h4>
      <p>${portfolioTextMarkup(value)}</p>
    </section>
  `;
}

function renderPortfolioDetail(holding) {
  const notes = holding.notes || {};
  const position = normalizePortfolioPosition(holding.position);
  const sourceUrls = Array.isArray(notes.source_urls) ? notes.source_urls : [];
  return `
    <button type="button" class="market-map-modal-close" data-portfolio-close aria-label="닫기">×</button>
    <div class="portfolio-detail-head">
      <span class="portfolio-crest is-${escapeHtml(holding.crest_theme || "default")}">${escapeHtml(holding.mark || holding.name)}</span>
      <div>
        <p>${escapeHtml(PORTFOLIO_POSITIONS[position].label)}</p>
        <h3 id="portfolio-modal-title">${escapeHtml(holding.name)}</h3>
        <span>${escapeHtml(holding.code)} · 비중 ${formatPercent(Number(holding.weight_pct), 1)}</span>
      </div>
    </div>
    <div class="portfolio-note-grid">
      ${renderPortfolioNoteCard("투자 아이디어", notes.investment_idea, "idea")}
      ${renderPortfolioNoteCard("주가 추이 및 개인적 해석", notes.price_view, "price")}
      ${renderPortfolioNoteCard("주요 변수", notes.key_variables, "variables")}
      ${renderPortfolioNoteCard("시나리오", notes.scenario, "scenario")}
      ${renderPortfolioNoteCard("주가 전망 및 촉매", notes.catalysts, "catalysts")}
    </div>
    ${sourceUrls.length ? `
      <div class="portfolio-note-sources">
        <span>참고 자료</span>
        ${sourceUrls.map((url, index) => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">자료 ${index + 1}</a>`).join("")}
      </div>
    ` : ""}
    <div class="portfolio-detail-actions">
      <button type="button" data-portfolio-edit="${escapeHtml(holding.code)}">내용·포지션 편집</button>
      ${holding.type !== "cash" ? `<button type="button" data-portfolio-open-market="${escapeHtml(holding.code)}">국내 종목 상세 보기</button>` : ""}
    </div>
  `;
}

function renderPortfolioEditor(holding = null) {
  const isNew = !holding;
  const notes = holding?.notes || {};
  const position = normalizePortfolioPosition(holding?.position || "CM");
  return `
    <button type="button" class="market-map-modal-close" data-portfolio-close aria-label="닫기">×</button>
    <div class="portfolio-editor-head">
      <p>Portfolio Editor</p>
      <h3 id="portfolio-modal-title">${isNew ? "종목 추가" : `${escapeHtml(holding.name)} 편집`}</h3>
      <span>입력값은 이 브라우저에 저장되며 JSON으로 내보낼 수 있습니다.</span>
    </div>
    <form id="portfolio-editor-form" class="portfolio-editor-form">
      <input type="hidden" name="original_code" value="${escapeHtml(holding?.code || "")}">
      <div class="portfolio-editor-grid">
        <label><span>종목코드 또는 종목명</span><input name="code" value="${escapeHtml(holding?.code || "")}" placeholder="예: 214450 또는 파마리서치" required></label>
        <label><span>표시 이름</span><input name="name" value="${escapeHtml(holding?.name || "")}" placeholder="비워두면 종목 데이터에서 검색"></label>
        <label><span>포지션 코드</span><input name="position" list="portfolio-position-options" value="${escapeHtml(position)}" placeholder="ST, CF, WF, AM, LM, RM, CB, GK" required></label>
        <label><span>비중 (%)</span><input name="weight_pct" type="number" min="0" max="100" step="0.01" value="${Number(holding?.weight_pct ?? 0)}"></label>
        <label class="is-wide"><span>전술 역할 한 줄</span><input name="role" value="${escapeHtml(holding?.role || "")}" placeholder="예: 리쥬란 글로벌 성장"></label>
      </div>
      <datalist id="portfolio-position-options">
        ${Object.entries(PORTFOLIO_POSITIONS).map(([code, item]) => `<option value="${code}">${escapeHtml(item.label)}</option>`).join("")}
      </datalist>
      <label><span>투자 아이디어</span><textarea name="investment_idea" rows="5">${escapeHtml(notes.investment_idea || "")}</textarea></label>
      <label><span>주가 추이 및 개인적 해석</span><textarea name="price_view" rows="4">${escapeHtml(notes.price_view || "")}</textarea></label>
      <label><span>주요 변수</span><textarea name="key_variables" rows="6">${escapeHtml(notes.key_variables || "")}</textarea></label>
      <label><span>시나리오</span><textarea name="scenario" rows="7">${escapeHtml(notes.scenario || "")}</textarea></label>
      <label><span>주가 전망 및 촉매</span><textarea name="catalysts" rows="5">${escapeHtml(notes.catalysts || "")}</textarea></label>
      <div class="portfolio-editor-actions">
        <button type="submit">저장</button>
        <button type="button" data-portfolio-cancel>취소</button>
        ${!isNew ? '<button type="button" class="is-danger" data-portfolio-delete>종목 삭제</button>' : ""}
      </div>
    </form>
  `;
}

function renderPortfolioModal() {
  const modal = document.getElementById("portfolio-modal");
  const container = document.getElementById("portfolio-detail");
  if (!modal || !container) return;
  const holding = portfolioHoldingByCode(state.portfolioSelectedCode);
  if (state.portfolioModalMode === "add") {
    container.innerHTML = renderPortfolioEditor(null);
  } else if (state.portfolioModalMode === "edit" && holding) {
    container.innerHTML = renderPortfolioEditor(holding);
  } else if (holding) {
    container.innerHTML = renderPortfolioDetail(holding);
  } else {
    closePortfolioModal();
    return;
  }
  modal.hidden = false;
  document.body.classList.add("market-map-modal-open");
}

function openPortfolioStock(code) {
  state.portfolioSelectedCode = code;
  state.portfolioModalMode = "detail";
  renderPortfolioModal();
}

function openPortfolioMarketDetail(code) {
  const stock = state.marketMapData?.markets?.KR?.stocks?.find((row) => row.symbol === code);
  closePortfolioModal();
  if (stock) {
    state.marketMapSelected = `KR:${code}`;
    renderMarketMapDetail(stock);
    return;
  }
  if (state.rawStocks.some((row) => row.code === code)) {
    state.selectedCode = code;
    switchWorkspace("valuation");
    renderDashboard();
    document.getElementById("selected-stock-workbench")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function persistPortfolioData(payload) {
  payload.count = payload.holdings.length;
  payload.stock_count = payload.holdings.filter((holding) => holding.type !== "cash").length;
  payload.as_of = new Date().toISOString().slice(0, 10);
  state.portfolioData = payload;
  state.portfolioUsingLocal = true;
  localStorage.setItem(PORTFOLIO_STORAGE_KEY, JSON.stringify(payload));
  renderPortfolioBoard();
}

function resolvePortfolioStock(query, name) {
  const normalized = String(query || "").trim();
  return state.rawStocks.find((stock) =>
    stock.code === normalized || stock.name === normalized || stock.name === String(name || "").trim()
  ) || null;
}

function savePortfolioEditor(form) {
  const formData = new FormData(form);
  const originalCode = String(formData.get("original_code") || "").trim();
  const query = String(formData.get("code") || "").trim();
  const inputName = String(formData.get("name") || "").trim();
  const rawStock = resolvePortfolioStock(query, inputName);
  const isCash = query.toUpperCase() === "CASH" || query === "현금" || inputName === "현금";
  const code = isCash ? "CASH" : (rawStock?.code || query.toUpperCase());
  const name = isCash ? "현금" : (inputName || rawStock?.name || query);
  if (!code || !name) {
    window.alert("종목코드 또는 종목명을 입력해주세요.");
    return;
  }
  const payload = clonePortfolioData(state.portfolioData);
  const existing = portfolioHoldingByCode(originalCode);
  const duplicate = payload.holdings.find((holding) => holding.code === code && holding.code !== originalCode);
  if (duplicate) {
    window.alert("이미 포트폴리오에 있는 종목입니다.");
    return;
  }
  const type = isCash ? "cash" : "stock";
  const holding = {
    code,
    name,
    type,
    weight_pct: Number(formData.get("weight_pct")) || 0,
    position: normalizePortfolioPosition(formData.get("position")),
    role: String(formData.get("role") || "").trim(),
    mark: existing?.mark || portfolioMark(code, name, type),
    crest_theme: existing?.crest_theme || portfolioCrestTheme(code, name, type),
    notes: {
      ...(existing?.notes || {}),
      investment_idea: String(formData.get("investment_idea") || "").trim(),
      price_view: String(formData.get("price_view") || "").trim(),
      key_variables: String(formData.get("key_variables") || "").trim(),
      scenario: String(formData.get("scenario") || "").trim(),
      catalysts: String(formData.get("catalysts") || "").trim()
    }
  };
  const index = payload.holdings.findIndex((item) => item.code === originalCode);
  if (index >= 0) payload.holdings[index] = holding;
  else payload.holdings.push(holding);
  payload.changes = [
    {
      type: index >= 0 ? "내용 수정" : "신규 편입",
      date: new Date().toISOString().slice(0, 10),
      reason: `${name} · ${holding.position} 포지션 ${index >= 0 ? "수정" : "추가"}`
    },
    ...(payload.changes || [])
  ].slice(0, 20);
  persistPortfolioData(payload);
  state.portfolioSelectedCode = code;
  state.portfolioModalMode = "detail";
  renderPortfolioModal();
}

function deletePortfolioHolding() {
  const holding = portfolioHoldingByCode(state.portfolioSelectedCode);
  if (!holding || !window.confirm(`${holding.name}을(를) 포트폴리오에서 삭제할까요?`)) return;
  const payload = clonePortfolioData(state.portfolioData);
  payload.holdings = payload.holdings.filter((item) => item.code !== holding.code);
  payload.changes = [
    { type: "제외", date: new Date().toISOString().slice(0, 10), reason: `${holding.name} 포트폴리오 제외` },
    ...(payload.changes || [])
  ].slice(0, 20);
  persistPortfolioData(payload);
  closePortfolioModal();
}

function exportPortfolioJson() {
  const blob = new Blob([`${JSON.stringify(state.portfolioData, null, 2)}\n`], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `portfolio-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function resetPortfolioData() {
  if (!window.confirm("이 브라우저에서 수정한 내용을 지우고 공개 JSON 기본값으로 되돌릴까요?")) return;
  localStorage.removeItem(PORTFOLIO_STORAGE_KEY);
  state.portfolioData = clonePortfolioData(state.portfolioDefaultData);
  state.portfolioUsingLocal = false;
  renderPortfolioBoard();
}

function bindPortfolioBoard() {
  document.getElementById("portfolio-board")?.addEventListener("click", (event) => {
    const player = event.target.closest("[data-portfolio-code]");
    if (player) openPortfolioStock(player.dataset.portfolioCode);
    else if (event.target.closest("[data-portfolio-add]")) {
      state.portfolioSelectedCode = null;
      state.portfolioModalMode = "add";
      renderPortfolioModal();
    } else if (event.target.closest("[data-portfolio-export]")) exportPortfolioJson();
    else if (event.target.closest("[data-portfolio-reset]")) resetPortfolioData();
  });
  document.getElementById("portfolio-modal")?.addEventListener("click", (event) => {
    if (event.target.closest("[data-portfolio-close]")) closePortfolioModal();
  });
  document.getElementById("portfolio-detail")?.addEventListener("click", (event) => {
    const edit = event.target.closest("[data-portfolio-edit]");
    const market = event.target.closest("[data-portfolio-open-market]");
    if (edit) {
      state.portfolioSelectedCode = edit.dataset.portfolioEdit;
      state.portfolioModalMode = "edit";
      renderPortfolioModal();
    } else if (market) openPortfolioMarketDetail(market.dataset.portfolioOpenMarket);
    else if (event.target.closest("[data-portfolio-cancel]")) {
      if (state.portfolioSelectedCode) {
        state.portfolioModalMode = "detail";
        renderPortfolioModal();
      } else closePortfolioModal();
    } else if (event.target.closest("[data-portfolio-delete]")) deletePortfolioHolding();
  });
  document.getElementById("portfolio-detail")?.addEventListener("submit", (event) => {
    if (event.target.matches("#portfolio-editor-form")) {
      event.preventDefault();
      savePortfolioEditor(event.target);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !document.getElementById("portfolio-modal")?.hidden) {
      closePortfolioModal();
    }
  });
}

async function loadPortfolio() {
  const container = document.getElementById("portfolio-board");
  try {
    const response = await fetch(`${PORTFOLIO_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status} for portfolio`);
    const publicPayload = await response.json();
    state.portfolioDefaultData = publicPayload;
    const localPayload = localStorage.getItem(PORTFOLIO_STORAGE_KEY);
    if (localPayload) {
      try {
        state.portfolioData = JSON.parse(localPayload);
        state.portfolioUsingLocal = true;
      } catch (storageError) {
        localStorage.removeItem(PORTFOLIO_STORAGE_KEY);
        state.portfolioData = clonePortfolioData(publicPayload);
        state.portfolioUsingLocal = false;
        console.warn("손상된 로컬 포트폴리오를 공개 기본값으로 복원했습니다.", storageError);
      }
    } else {
      state.portfolioData = clonePortfolioData(publicPayload);
      state.portfolioUsingLocal = false;
    }
    renderPortfolioBoard();
  } catch (error) {
    if (container) container.innerHTML = '<div class="portfolio-loading">포트폴리오 데이터를 불러오지 못했습니다.</div>';
    console.error(error);
  }
}

function renderMarketMapKpis(stocks) {
  const container = document.getElementById("market-map-kpis");
  if (!container) {
    return;
  }
  const capTotal = stocks.reduce((sum, stock) => sum + (Number(stock.market_cap) || 0), 0);
  const weightedChange = capTotal
    ? stocks.reduce(
      (sum, stock) => sum
        + (Number(stock.change_pct) || 0) * (Number(stock.market_cap) || 0),
      0
    ) / capTotal
    : 0;
  const rising = stocks.filter((stock) => Number(stock.change_pct) > 0).length;
  const sectors = new Set(stocks.map((stock) => marketMapHierarchy(stock).sector)).size;
  const capText = state.marketMapMarket === "KR"
    ? formatMarketCap(capTotal)
    : formatUsdCompact(capTotal);
  container.innerHTML = [
    ["표시 대상", `${formatInteger(stocks.length)}개`, `${sectors}개 섹터`],
    ["시총 합계", capText, "현재 필터 기준"],
    ["가중 등락", formatSignedPercent(weightedChange, 2), "시가총액 가중"],
    ["상승 비율", stocks.length ? formatPercent(rising / stocks.length * 100, 1) : "N/A", `${rising}개 상승`]
  ].map(([label, value, note]) => `
    <div class="market-map-kpi">
      <span>${escapeHtml(label)}</span>
      <strong class="${label === "가중 등락" ? marketTone(weightedChange) : ""}">${escapeHtml(value)}</strong>
      <small>${escapeHtml(note)}</small>
    </div>
  `).join("");
}

function renderMarketMapDetail(stock) {
  const container = document.getElementById("market-map-detail");
  const modal = document.getElementById("market-map-modal");
  if (!container || !modal) {
    return;
  }
  if (!stock) {
    modal.hidden = true;
    container.innerHTML = "";
    document.body.classList.remove("market-map-modal-open");
    return;
  }
  modal.hidden = false;
  document.body.classList.add("market-map-modal-open");
  const isKorea = stock.market === "KR";
  const hierarchy = marketMapHierarchy(stock);
  const metrics = isKorea
    ? [
      ["시가총액", marketMapCap(stock)],
      ["거래량", formatMarketMapOptional(stock.volume, formatInteger)],
      ["ROE", formatMarketMapOptional(stock.roe, (value) => formatPercent(value, 1))],
      ["PBR", formatMarketMapOptional(stock.pbr, (value) => formatNumber(value, 2))],
      ["PER", formatMarketMapOptional(stock.per, (value) => formatNumber(value, 2))],
      ["외국인", formatMarketMapOptional(
        stock.foreigner_ratio,
        (value) => formatPercent(value, 1)
      )]
    ]
    : [
      ["시가총액", marketMapCap(stock)],
      ["거래량", formatMarketMapOptional(stock.volume, formatInteger)],
      ["RSI(14)", formatMarketMapOptional(stock.rsi14, (value) => formatNumber(value, 1))],
      ["1주 수익률", formatMarketMapOptional(
        stock.return_1w,
        (value) => formatSignedPercent(value, 1)
      )],
      ["1개월 수익률", formatMarketMapOptional(
        stock.return_1m,
        (value) => formatSignedPercent(value, 1)
      )],
      ["3개월 수익률", formatMarketMapOptional(
        stock.return_3m,
        (value) => formatSignedPercent(value, 1)
      )]
    ];
  container.innerHTML = `
    <button
      type="button"
      class="market-map-modal-close"
      data-market-map-close
      aria-label="종목 상세 팝업 닫기"
    >×</button>
    <div class="market-map-detail-head">
      <div>
        <p>${escapeHtml(`${hierarchy.sector} · ${hierarchy.industry}`)}</p>
        <h3 id="market-map-modal-title">${escapeHtml(isKorea ? stock.name : stock.symbol)}</h3>
        <span>${escapeHtml(isKorea ? stock.symbol : stock.name)}</span>
      </div>
      <span class="market-map-detail-change ${marketTone(stock.change_pct)}">
        ${escapeHtml(formatSignedPercent(Number(stock.change_pct), 2))}
      </span>
    </div>
    <div class="market-map-detail-price">${escapeHtml(marketMapPrice(stock))}</div>
    <div class="market-map-detail-grid">
      ${metrics.map(([label, value]) => `
        <div>
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
        </div>
      `).join("")}
    </div>
    <div class="market-map-detail-actions">
      <button type="button" data-market-map-jump="${isKorea ? "valuation" : "us"}" data-market-map-symbol="${escapeHtml(stock.symbol)}">
        ${isKorea ? "가치평가에서 보기" : "미국 시장에서 보기"}
      </button>
      <a href="${escapeHtml(stock.url)}" target="_blank" rel="noopener noreferrer">원문 시세 ↗</a>
    </div>
  `;
}

function closeMarketMapModal({ render = true } = {}) {
  state.marketMapSelected = null;
  document.getElementById("market-map-modal")?.setAttribute("hidden", "");
  document.body.classList.remove("market-map-modal-open");
  if (render) {
    renderMarketMap();
  }
}

function marketMapWeight(item) {
  const value = Number(item?.[state.marketMapSize]);
  return Number.isFinite(value) && value > 0 ? value : 1;
}

function marketMapInsetRect(rect, left, top, right = left, bottom = top) {
  return {
    x: rect.x + left,
    y: rect.y + top,
    w: Math.max(0, rect.w - left - right),
    h: Math.max(0, rect.h - top - bottom)
  };
}

function marketMapSquarify(items, bounds, weightAccessor) {
  const weighted = items
    .map((item) => ({ item, weight: Math.max(0, Number(weightAccessor(item)) || 0) }))
    .filter((entry) => entry.weight > 0)
    .sort((a, b) => b.weight - a.weight);
  const totalWeight = weighted.reduce((sum, entry) => sum + entry.weight, 0);
  const totalArea = Math.max(0, bounds.w * bounds.h);
  if (!weighted.length || !totalWeight || !totalArea) {
    return [];
  }

  weighted.forEach((entry) => {
    entry.area = entry.weight / totalWeight * totalArea;
  });

  const output = [];
  const remaining = { ...bounds };
  const worstRatio = (row, shortSide) => {
    if (!row.length || shortSide <= 0) {
      return Number.POSITIVE_INFINITY;
    }
    const sum = row.reduce((total, entry) => total + entry.area, 0);
    const largest = Math.max(...row.map((entry) => entry.area));
    const smallest = Math.min(...row.map((entry) => entry.area));
    if (!sum || !smallest) {
      return Number.POSITIVE_INFINITY;
    }
    const sideSquared = shortSide * shortSide;
    return Math.max(
      sideSquared * largest / (sum * sum),
      (sum * sum) / (sideSquared * smallest)
    );
  };
  const placeRow = (row) => {
    const rowArea = row.reduce((total, entry) => total + entry.area, 0);
    if (remaining.w >= remaining.h) {
      const stripWidth = remaining.h ? rowArea / remaining.h : 0;
      let cursor = remaining.y;
      row.forEach((entry, index) => {
        const height = stripWidth
          ? (index === row.length - 1 ? remaining.y + remaining.h - cursor : entry.area / stripWidth)
          : 0;
        output.push({
          item: entry.item,
          rect: { x: remaining.x, y: cursor, w: stripWidth, h: height }
        });
        cursor += height;
      });
      remaining.x += stripWidth;
      remaining.w = Math.max(0, remaining.w - stripWidth);
    } else {
      const stripHeight = remaining.w ? rowArea / remaining.w : 0;
      let cursor = remaining.x;
      row.forEach((entry, index) => {
        const width = stripHeight
          ? (index === row.length - 1 ? remaining.x + remaining.w - cursor : entry.area / stripHeight)
          : 0;
        output.push({
          item: entry.item,
          rect: { x: cursor, y: remaining.y, w: width, h: stripHeight }
        });
        cursor += width;
      });
      remaining.y += stripHeight;
      remaining.h = Math.max(0, remaining.h - stripHeight);
    }
  };

  let row = [];
  weighted.forEach((entry) => {
    const shortSide = Math.min(remaining.w, remaining.h);
    const nextRow = [...row, entry];
    if (!row.length || worstRatio(nextRow, shortSide) <= worstRatio(row, shortSide)) {
      row = nextRow;
      return;
    }
    placeRow(row);
    row = [entry];
  });
  if (row.length) {
    placeRow(row);
  }
  return output;
}

function marketMapRectStyle(rect) {
  return [
    `left:${rect.x.toFixed(2)}px`,
    `top:${rect.y.toFixed(2)}px`,
    `width:${Math.max(0, rect.w).toFixed(2)}px`,
    `height:${Math.max(0, rect.h).toFixed(2)}px`
  ].join(";");
}

function marketMapTileMarkup(stock, rect) {
  const key = `${stock.market}:${stock.symbol}`;
  const primary = stock.market === "KR" ? stock.name : stock.symbol;
  const secondary = stock.market === "KR" ? stock.symbol : stock.name;
  const area = rect.w * rect.h;
  const showPrimary = rect.w >= 38 && rect.h >= 22;
  const showMetric = rect.w >= 54 && rect.h >= 39;
  const showSecondary = area >= 13500 && rect.w >= 96 && rect.h >= 68;
  const sizeClass = area >= 32000
    ? "is-xl"
    : area >= 10500
      ? "is-lg"
      : area >= 2800
        ? "is-md"
        : "is-sm";
  return `
    <button
      type="button"
      class="market-heatmap-tile ${sizeClass} ${key === state.marketMapSelected ? "is-selected" : ""}"
      style="${marketMapRectStyle(marketMapInsetRect(rect, 1, 1))};${marketMapTileStyle(stock)}"
      data-market-map-key="${escapeHtml(key)}"
      aria-label="${escapeHtml(`${primary}, ${marketMapMetricConfig().label} ${marketMapMetricText(stock)}`)}"
      aria-pressed="${key === state.marketMapSelected ? "true" : "false"}"
      title="${escapeHtml(`${primary} · ${secondary} · ${marketMapMetricConfig().label} ${marketMapMetricText(stock)}`)}"
    >
      ${showPrimary ? `<strong>${escapeHtml(primary)}</strong>` : ""}
      ${showSecondary ? `<span class="market-heatmap-tile-name">${escapeHtml(secondary)}</span>` : ""}
      ${showMetric ? `<span class="market-heatmap-tile-value">${escapeHtml(marketMapMetricText(stock))}</span>` : ""}
    </button>
  `;
}

function marketMapIndustryMarkup(group, rect, showIndustryFrame) {
  const showTitle = showIndustryFrame && rect.w >= 78 && rect.h >= 48;
  const headerHeight = showTitle ? 17 : 0;
  const stockBounds = marketMapInsetRect(
    { x: 0, y: 0, w: rect.w, h: rect.h },
    2,
    headerHeight + 2,
    2,
    2
  );
  const stockRects = marketMapSquarify(group.stocks, stockBounds, marketMapWeight);
  return `
    <div
      class="market-heatmap-industry ${showIndustryFrame ? "" : "is-flat"}"
      style="${marketMapRectStyle(rect)}"
      title="${escapeHtml(`${group.industry} · ${group.stocks.length}개 종목`)}"
    >
      ${showTitle ? `<span class="market-heatmap-industry-title">${escapeHtml(group.industry)}</span>` : ""}
      ${stockRects.map(({ item, rect: stockRect }) =>
        marketMapTileMarkup(item, stockRect)
      ).join("")}
    </div>
  `;
}

function renderMarketHeatmap(stocks) {
  const container = document.getElementById("market-heatmap");
  if (!container) {
    return;
  }
  const sorted = [...stocks].sort((a, b) => marketMapWeight(b) - marketMapWeight(a));
  const visible = state.marketMapLimit > 0
    ? sorted.slice(0, state.marketMapLimit)
    : sorted;
  if (!visible.length) {
    container.innerHTML = `
      <div class="market-map-loading">현재 조건에 맞는 종목이 없습니다.</div>
    `;
    renderMarketMapDetail(null);
    return;
  }

  const containerRect = container.getBoundingClientRect();
  const containerStyle = window.getComputedStyle(container);
  const horizontalBorder = (Number.parseFloat(containerStyle.borderLeftWidth) || 0)
    + (Number.parseFloat(containerStyle.borderRightWidth) || 0);
  const verticalBorder = (Number.parseFloat(containerStyle.borderTopWidth) || 0)
    + (Number.parseFloat(containerStyle.borderBottomWidth) || 0);
  const width = Math.max(0, Math.floor(containerRect.width - horizontalBorder));
  const height = Math.max(0, Math.floor(containerRect.height - verticalBorder));
  if (width < 20 || height < 20) {
    window.requestAnimationFrame(() => renderMarketHeatmap(stocks));
    return;
  }

  const visibleKeys = new Set(visible.map((stock) => `${stock.market}:${stock.symbol}`));
  if (state.marketMapSelected && !visibleKeys.has(state.marketMapSelected)) {
    state.marketMapSelected = null;
  }

  const sectors = new Map();
  visible.forEach((stock) => {
    const hierarchy = marketMapHierarchy(stock);
    if (!sectors.has(hierarchy.sector)) {
      sectors.set(hierarchy.sector, {
        sector: hierarchy.sector,
        stocks: [],
        industries: new Map()
      });
    }
    const sector = sectors.get(hierarchy.sector);
    sector.stocks.push(stock);
    if (!sector.industries.has(hierarchy.industry)) {
      sector.industries.set(hierarchy.industry, []);
    }
    sector.industries.get(hierarchy.industry).push(stock);
  });

  const sectorGroups = Array.from(sectors.values()).map((group) => ({
    ...group,
    weight: group.stocks.reduce((sum, stock) => sum + marketMapWeight(stock), 0),
    cap: group.stocks.reduce((sum, stock) => sum + (Number(stock.market_cap) || 0), 0)
  }));
  const sectorRects = marketMapSquarify(
    sectorGroups,
    { x: 0, y: 0, w: width, h: height },
    (group) => group.weight
  );

  container.innerHTML = sectorRects.map(({ item: group, rect }) => {
    const weightedChange = group.cap
      ? group.stocks.reduce(
        (sum, stock) => sum
          + (Number(stock.change_pct) || 0) * (Number(stock.market_cap) || 0),
        0
      ) / group.cap
      : 0;
    const showSectorTitle = rect.w >= 76 && rect.h >= 42;
    const sectorHeaderHeight = showSectorTitle ? 24 : 0;
    const industryBounds = marketMapInsetRect(
      { x: 0, y: 0, w: rect.w, h: rect.h },
      3,
      sectorHeaderHeight + 3,
      3,
      3
    );
    const industries = Array.from(group.industries.entries()).map(
      ([industry, industryStocks]) => ({
        industry,
        stocks: industryStocks,
        weight: industryStocks.reduce((sum, stock) => sum + marketMapWeight(stock), 0)
      })
    );
    const industryRects = marketMapSquarify(
      industries,
      industryBounds,
      (industry) => industry.weight
    );
    const showIndustryFrames = industries.length > 1 && rect.w >= 150 && rect.h >= 100;
    return `
      <section
        class="market-heatmap-sector"
        style="${marketMapRectStyle(marketMapInsetRect(rect, 1, 1))}"
      >
        ${showSectorTitle ? `
          <button
            type="button"
            class="market-heatmap-sector-head"
            data-market-map-sector-filter="${escapeHtml(group.sector)}"
            title="${escapeHtml(`${group.sector}만 보기`)}"
          >
            <strong>${escapeHtml(group.sector)}</strong>
            <span class="${marketTone(weightedChange)}">${escapeHtml(formatSignedPercent(weightedChange, 2))}</span>
          </button>
        ` : ""}
        ${industryRects.map(({ item: industry, rect: industryRect }) =>
          marketMapIndustryMarkup(industry, industryRect, showIndustryFrames)
        ).join("")}
      </section>
    `;
  }).join("");

  const selected = visible.find(
    (stock) => `${stock.market}:${stock.symbol}` === state.marketMapSelected
  );
  renderMarketMapDetail(selected || null);
}

function renderMarketMap() {
  if (!state.marketMapData) {
    return;
  }
  const stocks = filteredMarketMapStocks();
  renderMarketMapKpis(stocks);
  renderMarketHeatmap(stocks);
}

function resetMarketMap() {
  state.marketMapMarket = "KR";
  state.marketMapGroup = "KOSPI";
  state.marketMapSector = "all";
  state.marketMapColor = "change_pct";
  state.marketMapSize = "market_cap";
  state.marketMapLimit = 500;
  state.marketMapSearch = "";
  state.marketMapSelected = null;
  document.getElementById("market-map-market").value = state.marketMapMarket;
  document.getElementById("market-map-size").value = state.marketMapSize;
  document.getElementById("market-map-limit").value = String(state.marketMapLimit);
  document.getElementById("market-map-search").value = "";
  renderMarketMapFilterOptions();
  renderMarketMap();
}

function bindMarketMap() {
  const bindings = [
    ["market-map-market", "change", (event) => {
      state.marketMapMarket = event.target.value;
      state.marketMapGroup = state.marketMapMarket === "KR" ? "KOSPI" : "top500";
      state.marketMapSector = "all";
      state.marketMapColor = "change_pct";
      state.marketMapSelected = null;
      renderMarketMapFilterOptions();
      renderMarketMap();
    }],
    ["market-map-group", "change", (event) => {
      state.marketMapGroup = event.target.value;
      state.marketMapSector = "all";
      state.marketMapSelected = null;
      renderMarketMapFilterOptions();
      renderMarketMap();
    }],
    ["market-map-sector", "change", (event) => {
      state.marketMapSector = event.target.value;
      state.marketMapSelected = null;
      renderMarketMap();
    }],
    ["market-map-color", "change", (event) => {
      state.marketMapColor = event.target.value;
      renderMarketMap();
    }],
    ["market-map-size", "change", (event) => {
      state.marketMapSize = event.target.value;
      renderMarketMap();
    }],
    ["market-map-limit", "change", (event) => {
      const value = Number(event.target.value);
      state.marketMapLimit = Number.isFinite(value) ? value : 500;
      renderMarketMap();
    }],
    ["market-map-search", "input", (event) => {
      state.marketMapSearch = event.target.value;
      state.marketMapSelected = null;
      renderMarketMap();
    }]
  ];
  bindings.forEach(([id, eventName, handler]) => {
    document.getElementById(id)?.addEventListener(eventName, handler);
  });
  document.getElementById("market-map-reset")?.addEventListener("click", resetMarketMap);
  document.getElementById("market-heatmap")?.addEventListener("click", (event) => {
    const tile = event.target.closest("[data-market-map-key]");
    if (tile) {
      state.marketMapSelected = tile.dataset.marketMapKey;
      renderMarketMap();
      return;
    }
    const sector = event.target.closest("[data-market-map-sector-filter]");
    if (sector) {
      state.marketMapSector = sector.dataset.marketMapSectorFilter;
      state.marketMapSelected = null;
      document.getElementById("market-map-sector").value = state.marketMapSector;
      renderMarketMap();
    }
  });
  document.getElementById("market-map-modal")?.addEventListener("click", (event) => {
    if (event.target.closest("[data-market-map-close]")) {
      closeMarketMapModal();
    }
  });
  document.getElementById("market-map-detail")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-market-map-jump]");
    if (!button) {
      return;
    }
    const symbol = button.dataset.marketMapSymbol;
    closeMarketMapModal({ render: false });
    if (button.dataset.marketMapJump === "valuation") {
      if (state.rawStocks.some((stock) => stock.code === symbol)) {
        state.selectedCode = symbol;
        switchWorkspace("valuation");
        renderDashboard();
        setTimeout(() => {
          document.getElementById("selected-stock-workbench")
            ?.scrollIntoView({ behavior: "smooth", block: "center" });
        }, 120);
      }
    } else {
      state.usSelectedSymbol = symbol;
      switchWorkspace("us");
      setTimeout(() => {
        renderUsWorkspace();
        document.getElementById("us-selected-summary")
          ?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 900);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !document.getElementById("market-map-modal")?.hidden) {
      closeMarketMapModal();
    }
  });
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      if (state.marketMapData) {
        renderMarketMap();
      }
    }, 140);
  });
}

async function loadMarketMap() {
  const heatmap = document.getElementById("market-heatmap");
  try {
    const response = await fetch(`${MARKET_HEATMAP_URL}?v=${Date.now()}`, {
      cache: "no-store"
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} for market heatmap`);
    }
    const payload = await response.json();
    state.marketMapData = payload;
    renderPortfolioBoard();
    document.getElementById("market-map-market").value = state.marketMapMarket;
    const updated = new Date(payload.crawled_at_utc);
    document.getElementById("market-map-updated").textContent =
      Number.isNaN(updated.getTime())
        ? "갱신 시각 확인 불가"
        : `${updated.toLocaleString("ko-KR")} 갱신`;
    renderMarketMapFilterOptions();
    renderMarketMap();
  } catch (error) {
    heatmap.innerHTML = `
      <div class="market-map-loading">시장 히트맵 데이터를 불러오지 못했습니다.</div>
    `;
    document.getElementById("market-map-updated").textContent = "Unavailable";
    console.error(error);
  }
}

const TODAY_NEWS_LABELS = {
  semiconductor: "반도체",
  it: "IT",
  us: "미국",
  kospi: "코스피",
  kosdaq: "코스닥",
  korea_rates: "국내 금리",
  korea_flow: "국내 수급",
  us_rates: "미국 금리",
  battery: "2차전지",
  bio: "바이오"
};

function newsCategoryLabel(category) {
  return state.todayNewsLabels?.[category]
    || TODAY_NEWS_LABELS[category]
    || category;
}

function kstDateKey(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Date(date.getTime() + 9 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 10);
}

function newsSourceName(link) {
  try {
    return new URL(link).hostname.replace(/^www\./, "");
  } catch {
    return "뉴스";
  }
}

function newsThumbnailUrl(row) {
  try {
    const url = new URL(row?.thumbnail_url || "");
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

function formatNewsTimestamp(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "시간 미상";
  }
  const elapsedMinutes = Math.max(0, Math.floor((Date.now() - date.getTime()) / 60000));
  if (elapsedMinutes < 60) {
    return `${elapsedMinutes}분 전`;
  }
  if (elapsedMinutes < 1440) {
    return `${Math.floor(elapsedMinutes / 60)}시간 전`;
  }
  return formatCompactDate(value);
}

function todayNewsRows() {
  const categoryRows = state.todayNewsItems.filter(
    (row) => (row.categories || []).includes(state.todayNewsCategory)
  );
  const todayKey = kstDateKey(new Date());
  const todaysRows = categoryRows.filter(
    (row) => kstDateKey(row.published_at) === todayKey
  );
  return {
    rows: (todaysRows.length ? todaysRows : categoryRows).slice(0, 9),
    isToday: todaysRows.length > 0,
    categoryCount: todaysRows.length || categoryRows.length
  };
}

function renderTodayNews() {
  const container = document.getElementById("today-news-content");
  const { rows, isToday, categoryCount } = todayNewsRows();
  document.querySelectorAll("[data-today-news-category]").forEach((button) => {
    const selected = button.dataset.todayNewsCategory === state.todayNewsCategory;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-selected", selected ? "true" : "false");
  });
  if (!rows.length) {
    container.innerHTML = `
      <div class="today-news-loading">
        ${escapeHtml(newsCategoryLabel(state.todayNewsCategory))} 뉴스가 아직 없습니다. 다음 뉴스 수집 후 표시됩니다.
      </div>
    `;
    return;
  }
  const [featured, ...rest] = rows;
  const featuredSource = newsSourceName(featured.link);
  const featuredLink = escapeHtml(featured.link || "#");
  const featuredThumbnail = newsThumbnailUrl(featured);
  container.innerHTML = `
    <a class="today-news-feature ${featuredThumbnail ? "has-thumbnail" : ""}" href="${featuredLink}" target="_blank" rel="noopener">
      ${featuredThumbnail ? `
        <img
          class="today-news-feature-image"
          src="${escapeHtml(featuredThumbnail)}"
          alt=""
          referrerpolicy="no-referrer"
          decoding="async"
        >
      ` : ""}
      <span class="today-news-feature-tag">${escapeHtml(newsCategoryLabel(state.todayNewsCategory))} · ${isToday ? "오늘" : "최근"}</span>
      <h3>${escapeHtml(featured.title || "-")}</h3>
      <p>${escapeHtml(featured.description || "")}</p>
      <span class="today-news-feature-meta">
        <span>${escapeHtml(featuredSource)}</span>
        <span>·</span>
        <span>${escapeHtml(formatNewsTimestamp(featured.published_at))}</span>
      </span>
    </a>
    <div class="today-news-list">
      ${rest.slice(0, 8).map((row, index) => {
        const thumbnail = newsThumbnailUrl(row);
        return `
          <a class="today-news-item ${thumbnail ? "has-thumbnail" : ""}" href="${escapeHtml(row.link || "#")}" target="_blank" rel="noopener">
            <span class="today-news-rank">${index + 2}</span>
            <span class="today-news-item-main">
              <h3>${escapeHtml(row.title || "-")}</h3>
              <span class="today-news-item-meta">
                <span>${escapeHtml(newsSourceName(row.link))}</span>
                <span>·</span>
                <span>${escapeHtml(formatNewsTimestamp(row.published_at))}</span>
              </span>
            </span>
            ${thumbnail ? `
              <img
                class="today-news-item-image"
                src="${escapeHtml(thumbnail)}"
                alt=""
                loading="lazy"
                referrerpolicy="no-referrer"
                decoding="async"
              >
            ` : ""}
          </a>
        `;
      }).join("")}
    </div>
  `;
  container.querySelectorAll(".today-news-feature-image, .today-news-item-image").forEach((image) => {
    image.addEventListener("error", () => {
      image.closest(".has-thumbnail")?.classList.remove("has-thumbnail");
      image.remove();
    }, { once: true });
  });
  document.getElementById("today-news-updated").textContent =
    `${isToday ? "오늘" : "최근"} ${categoryCount}건 · ${newsCategoryLabel(state.todayNewsCategory)}`;
}

function bindTodayNews() {
  document.querySelectorAll("[data-today-news-category]").forEach((button) => {
    button.addEventListener("click", () => {
      state.todayNewsCategory = button.dataset.todayNewsCategory;
      renderTodayNews();
    });
  });
  document.getElementById("open-intelligence-news")?.addEventListener("click", () => {
    switchWorkspace("intelligence");
  });
}

async function loadTodayNews() {
  try {
    const response = await fetch(`${NAVER_NEWS_URL}?v=${Date.now()}`, {
      cache: "no-store"
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} for NAVER news`);
    }
    const payload = await response.json();
    state.todayNewsItems = Array.isArray(payload.items) ? payload.items : [];
    state.todayNewsLabels = payload.category_labels || {};
    state.todayNewsCrawledAt = payload.crawled_at_utc || null;
    state.featureData.news = payload;
    renderTodayNews();
  } catch (error) {
    document.getElementById("today-news-content").innerHTML =
      "<div class='today-news-loading'>오늘의 뉴스는 다음 뉴스 수집 후 표시됩니다.</div>";
    document.getElementById("today-news-updated").textContent = "Unavailable";
    console.error(error);
  }
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function average(values) {
  if (!values.length) {
    return null;
  }

  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function standardDeviation(values) {
  if (values.length < 2) {
    return 0;
  }

  const mean = average(values);
  const variance = values.reduce((sum, value) => sum + ((value - mean) ** 2), 0) / values.length;
  return Math.sqrt(variance);
}

function getBookValuePerShare(stock) {
  if (!stock.current_price || !stock.pbr || stock.pbr <= 0) {
    return null;
  }

  return stock.current_price / stock.pbr;
}

function compoundFairPrice(stock, params) {
  const bps0 = getBookValuePerShare(stock);
  if (!bps0 || !Number.isFinite(params.assumedRoe)) {
    return null;
  }

  const roe = params.assumedRoe / 100;
  const discount = params.discountRate / 100;
  const duration = params.durationYears;

  if (
    !Number.isFinite(roe)
    || !Number.isFinite(discount)
    || !Number.isFinite(duration)
    || roe <= -1
    || discount <= -1
    || duration < 0
  ) {
    return null;
  }

  const fairPrice = bps0 * (((1 + roe) / (1 + discount)) ** duration);
  return Number.isFinite(fairPrice) ? fairPrice : null;
}

function marketImpliedN(
  roePercent,
  pbr,
  discountPercent = MARKET_IMPLIED_DISCOUNT_PCT
) {
  if (
    !Number.isFinite(roePercent)
    || !Number.isFinite(pbr)
    || !Number.isFinite(discountPercent)
    || pbr <= 0
    || Math.abs(roePercent - discountPercent) < MARKET_IMPLIED_ROE_GUARD_PP
  ) {
    return null;
  }

  const roe = roePercent / 100;
  const discount = discountPercent / 100;
  const growthRatio = (1 + roe) / (1 + discount);
  if (!Number.isFinite(growthRatio) || growthRatio <= 0 || growthRatio === 1) {
    return null;
  }

  const impliedN = Math.log(pbr) / Math.log(growthRatio);
  if (!Number.isFinite(impliedN)) {
    return null;
  }
  return impliedN === 0 ? 0 : impliedN;
}

function estimateMarketImpliedDuration(stock) {
  return marketImpliedN(stock.roe, stock.pbr);
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

function isSuspendedLike(stock) {
  return stock.volume === 0 && stock.diff === 0 && stock.diff_rate === 0;
}

function getMarketLabel(stock) {
  if (stock.market_label) {
    return stock.market_label;
  }
  return stock.market === "KOSDAQ" ? "코스닥" : "코스피";
}

function getMarketBadgeClass(stock) {
  return stock.market === "KOSDAQ" ? "market-badge kosdaq" : "market-badge kospi";
}

function getRoeHistoryValues(history) {
  const fullYearValues = (history?.full_years || [])
    .map((item) => item?.roe)
    .filter((value) => typeof value === "number" && Number.isFinite(value));

  if (fullYearValues.length >= 2) {
    return fullYearValues;
  }

  const allValues = (history?.roe_values || [])
    .filter((value) => typeof value === "number" && Number.isFinite(value));

  return allValues;
}

function extractReporterNames(majorHolder) {
  const holders = majorHolder?.holders || [];
  const seen = new Set();
  const names = [];

  holders.forEach((holder) => {
    const rawName = holder?.raw?.repror || holder?.holder_name || null;
    const normalized = typeof rawName === "string" ? rawName.trim() : "";
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    names.push(normalized);
  });

  return names;
}

function inferRoeRange(stock, history) {
  const values = getRoeHistoryValues(history);

  if (!values.length) {
    const fallback = typeof stock.roe === "number" ? stock.roe : null;
    if (fallback === null) {
      return { conservative: null, base: null, optimistic: null, source: "none", values: [] };
    }

    return {
      conservative: clamp(fallback - 4, 1, 100),
      base: clamp(fallback, 1, 100),
      optimistic: clamp(fallback + 4, 1, 100),
      source: "current_roe",
      values: [fallback]
    };
  }

  return {
    conservative: clamp(Math.min(...values), 1, 100),
    base: clamp(average(values), 1, 100),
    optimistic: clamp(Math.max(...values), 1, 100),
    source: values.length >= 2 ? "history_avg" : "latest_mix",
    values
  };
}

function estimateFinancialN(stock, historyValues) {
  const values = historyValues.filter((value) => typeof value === "number" && Number.isFinite(value));
  const avgRoe = average(values);
  const roeStd = standardDeviation(values);
  const highRoeYears = values.filter((value) => value >= 15).length;
  const underTenYears = values.filter((value) => value < 10).length;

  let score = 0;

  if (avgRoe !== null) {
    if (avgRoe >= 20) score += 2;
    else if (avgRoe >= 15) score += 1;
  }

  if (roeStd <= 3) score += 2;
  else if (roeStd <= 6) score += 1;

  if (values.length && highRoeYears === values.length) score += 2;
  else if (highRoeYears >= Math.max(2, values.length - 1)) score += 1;

  if (underTenYears === 0 && values.length >= 3) score += 1;

  if (typeof stock.sales_increasing_rate === "number") {
    if (stock.sales_increasing_rate >= 10) score += 1;
    else if (stock.sales_increasing_rate >= 0) score += 0.5;
  }

  if (typeof stock.operating_profit_increasing_rate === "number") {
    if (stock.operating_profit_increasing_rate >= 10) score += 1;
    else if (stock.operating_profit_increasing_rate >= 0) score += 0.5;
  }

  if (typeof stock.roa === "number") {
    if (stock.roa >= 8) score += 1;
    else if (stock.roa >= 5) score += 0.5;
  }

  if (typeof stock.reserve_ratio === "number") {
    if (stock.reserve_ratio >= 1000) score += 1;
    else if (stock.reserve_ratio >= 300) score += 0.5;
  }

  const debtRatio = (
    typeof stock.debt_total_krw_100m === "number" &&
    typeof stock.property_total_krw_100m === "number" &&
    stock.property_total_krw_100m > 0
  )
    ? stock.debt_total_krw_100m / stock.property_total_krw_100m
    : null;

  if (debtRatio !== null) {
    if (debtRatio <= 0.5) score += 1;
    else if (debtRatio <= 1) score += 0.5;
  }

  let estimatedN = 2;
  if (score >= 9) estimatedN = 10;
  else if (score >= 7) estimatedN = 8;
  else if (score >= 5) estimatedN = 6;
  else if (score >= 3) estimatedN = 4;

  return {
    score: Number(score.toFixed(1)),
    estimatedN,
    avgRoe,
    roeStd,
    highRoeYears,
    debtRatio
  };
}

function adaptEmpiricalNModel(estimate, fallbackModel) {
  if (!estimate?.estimate || typeof estimate.estimate.base_years !== "number") {
    return fallbackModel;
  }

  const confidence = estimate.confidence || {};
  const roe = estimate.roe || {};
  const streak = roe.trailing_high_roe_streak || {};

  return {
    score: typeof confidence.score_0_to_100 === "number"
      ? confidence.score_0_to_100
      : fallbackModel.score,
    estimatedN: estimate.estimate.base_years,
    avgRoe: typeof roe.mean_pct === "number" ? roe.mean_pct : fallbackModel.avgRoe,
    roeStd: typeof roe.volatility_pct_points === "number"
      ? roe.volatility_pct_points
      : fallbackModel.roeStd,
    highRoeYears: typeof streak.years === "number"
      ? streak.years
      : fallbackModel.highRoeYears,
    debtRatio: fallbackModel.debtRatio,
    engine: "empirical_persistence",
    status: estimate.status || "provisional",
    confidence,
    sources: estimate.sources || [],
    modifiers: estimate.modifiers || [],
    warnings: estimate.warnings || []
  };
}

function empiricalDurationRange(estimate) {
  if (!estimate?.estimate || typeof estimate.estimate.base_years !== "number") {
    return null;
  }

  return {
    conservative: clamp(
      estimate.estimate.conservative_years + state.durationOffset,
      1,
      30
    ),
    base: clamp(
      estimate.estimate.base_years + state.durationOffset,
      1,
      30
    ),
    optimistic: clamp(
      estimate.estimate.optimistic_years + state.durationOffset,
      1,
      30
    )
  };
}

function inferDurationRange(estimatedN) {
  const base = clamp(estimatedN + state.durationOffset, 1, 30);

  return {
    conservative: clamp(base - 1, 1, 30),
    base,
    optimistic: clamp(base + 2, 1, 30)
  };
}

function buildScenarioResult(stock, params) {
  const fairPrice = compoundFairPrice(stock, params);
  const gapRate = fairPrice && stock.current_price
    ? ((fairPrice - stock.current_price) / stock.current_price) * 100
    : null;
  const kellyRatio = estimateKellyRatio(stock, fairPrice);

  return {
    params,
    fairPrice,
    gapRate,
    kellyRatio
  };
}

function enrichStock(stock) {
  const majorHolder = state.dartMajorByCode.get(stock.code) || null;
  const history = state.roeHistoryByCode.get(stock.code) || null;
  const reporterNames = extractReporterNames(majorHolder);
  const marketImpliedN = estimateMarketImpliedDuration(stock);
  const roeRange = inferRoeRange(stock, history);
  const heuristicNModel = estimateFinancialN(stock, roeRange.values);
  const financialNEstimate = state.financialNByCode.get(stock.code) || null;
  const investmentScreen = state.investmentScreenByCode.get(stock.code) || null;
  const nModel = adaptEmpiricalNModel(financialNEstimate, heuristicNModel);
  const durationRange = empiricalDurationRange(financialNEstimate)
    || inferDurationRange(nModel.estimatedN);

  const conservativeRoe = roeRange.conservative === null ? null : clamp(roeRange.conservative + state.roeAdjustment, 1, 100);
  const baseRoe = roeRange.base === null ? null : clamp(roeRange.base + state.roeAdjustment, 1, 100);
  const optimisticRoe = roeRange.optimistic === null ? null : clamp(roeRange.optimistic + state.roeAdjustment, 1, 100);

  const scenarios = {
    conservative: buildScenarioResult(stock, {
      assumedRoe: conservativeRoe,
      durationYears: durationRange.conservative,
      discountRate: state.discountRate
    }),
    base: buildScenarioResult(stock, {
      assumedRoe: baseRoe,
      durationYears: durationRange.base,
      discountRate: state.discountRate
    }),
    optimistic: buildScenarioResult(stock, {
      assumedRoe: optimisticRoe,
      durationYears: durationRange.optimistic,
      discountRate: state.discountRate
    })
  };

  return {
    ...stock,
    bps: getBookValuePerShare(stock),
    marketImpliedN,
    estimatedNBase: durationRange.base,
    estimatedNScore: nModel.score,
    estimatedNRaw: nModel.estimatedN,
    estimatedNConservative: durationRange.conservative,
    estimatedNOptimistic: durationRange.optimistic,
    recommendedRoeConservative: roeRange.conservative,
    recommendedRoeBase: roeRange.base,
    recommendedRoeOptimistic: roeRange.optimistic,
    roeInferenceSource: roeRange.source,
    roeHistory: history,
    majorHolder,
    hasMajorHolders: Boolean(majorHolder?.has_major_holders),
    reporterNames,
    reporterCount: reporterNames.length,
    reporterSummary: reporterNames.join(", "),
    topHolderName: majorHolder?.top_holder_name || null,
    topHolderRatio: typeof majorHolder?.top_holder_ratio === "number" ? majorHolder.top_holder_ratio : null,
    latestReportDate: majorHolder?.latest_report_date || null,
    nModel,
    financialNEstimate,
    investmentScreen,
    scenarios,
    fairPriceConservative: scenarios.conservative.fairPrice,
    fairPriceBase: scenarios.base.fairPrice,
    fairPriceOptimistic: scenarios.optimistic.fairPrice,
    gapRateConservative: scenarios.conservative.gapRate,
    gapRateBase: scenarios.base.gapRate,
    gapRateOptimistic: scenarios.optimistic.gapRate,
    kellyRatioConservative: scenarios.conservative.kellyRatio,
    kellyRatioBase: scenarios.base.kellyRatio,
    kellyRatioOptimistic: scenarios.optimistic.kellyRatio,
    is_suspended: stock.is_suspended ?? isSuspendedLike(stock)
  };
}

function compareValues(aValue, bValue, direction) {
  const aMissing = aValue === null || aValue === undefined || Number.isNaN(aValue);
  const bMissing = bValue === null || bValue === undefined || Number.isNaN(bValue);

  if (aMissing && bMissing) return 0;
  if (aMissing) return 1;
  if (bMissing) return -1;

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

function nEstimateMethodLabel(nModel) {
  const isEmpirical = nModel?.engine === "empirical_persistence"
    || ["robust", "provisional", "prior_only"].includes(nModel?.status);
  if (!isEmpirical) {
    return "임시 점수표";
  }
  if (nModel.status === "prior_only") {
    return "업종 기준값 중심";
  }
  if (nModel.status === "provisional") {
    return "실증 엔진 · 보완 중";
  }
  return "실증 엔진";
}

const FINANCIAL_ROA_EXEMPT_KEYWORDS = [
  "은행",
  "금융",
  "증권",
  "보험",
  "화재",
  "생명",
  "손해",
  "카드",
  "캐피탈",
  "리츠",
  "스팩",
  "제1호",
  "제2호",
  "제3호",
  "제4호",
  "제5호",
  "제6호",
  "제7호",
  "제8호",
  "제9호"
];

function isFinancialRoaExempt(stock) {
  const name = String(stock.name || "");
  return FINANCIAL_ROA_EXEMPT_KEYWORDS.some((keyword) => name.includes(keyword));
}

function passesRoaFilter(stock) {
  if (state.exemptFinancialRoa && isFinancialRoaExempt(stock)) {
    return true;
  }
  return typeof stock.roa === "number" && stock.roa >= state.minRoa;
}

function getFilteredStocks() {
  return state.rawStocks
    .filter((stock) => typeof stock.roe === "number" && stock.roe >= state.threshold)
    .filter(passesRoaFilter)
    .map(enrichStock)
    .sort((a, b) => compareStocks(a, b, state.sortKey, state.sortDirection));
}

function getPriorityCandidates(stocks) {
  const stockByCode = new Map(stocks.map((stock) => [stock.code, stock]));
  const rankings = state.investmentScreensPayload?.rankings?.buffett_watchlist
    || state.investmentScreensPayload?.rankings?.buffett_candidates
    || [];
  const candidates = rankings.map((ranking, index) => {
    const code = ranking.ticker;
    const screen = state.investmentScreenByCode.get(code) || {};
    const buffett = screen.buffett || {};
    const nEstimate = screen.n || {};
    const rawStock = state.rawStockByCode.get(code);
    const stock = stockByCode.get(code)
      || (rawStock ? enrichStock(rawStock) : {});

    return {
      ...stock,
      code,
      name: stock.name || ranking.company || screen.company || code,
      market: stock.market || screen.market,
      market_label: stock.market_label || screen.market,
      sector: screen.sector || stock.sector || "-",
      buffettRank: ranking.rank || index + 1,
      recentReturnMetric: buffett.minimum_persistence_metric,
      recentReturnAverage: buffett.minimum_persistence_average_pct,
      recentReturnValues: buffett.minimum_persistence_values_pct || [],
      supportingConditionCount: buffett.supporting_condition_count,
      strengthTags: buffett.strength_tags || ranking.strength_tags || [],
      riskTags: buffett.risk_tags || [],
      strictCandidate: Boolean(buffett.candidate || ranking.strict_candidate),
      epsCagr5y: buffett.eps_cagr_5y_pct,
      persistencePassYears: buffett.persistence_pass_years,
      grossMarginSigma: buffett.gross_margin_sigma_pct_points,
      fcfConversion: buffett.fcf_conversion_10y,
      netDebtToEbitda: buffett.latest_net_debt_to_ebitda,
      latestRoic: buffett.latest_roic_pct,
      latestRoe: buffett.latest_roe_pct,
      incrementalRoic: buffett.incremental_roic_5y_pct,
      payoutRatio: buffett.payout_ratio_pct,
      fcfYield: buffett.valuation?.fcf_yield_pct,
      fcfYieldBasis: buffett.valuation?.normalized_fcf_basis,
      cashToMarketCap: buffett.valuation?.cash_to_market_cap_pct,
      estimatedNBase: nEstimate.base_years,
      nModel: nEstimate,
      nConfidence: nEstimate.confidence?.label,
      nConfidenceScore: nEstimate.confidence?.score_0_to_100,
      canOpenValuation: Boolean(rawStock)
    };
  });

  return candidates.sort((a, b) =>
    compareStocks(a, b, state.prioritySortKey, state.prioritySortDirection)
  );
}

function getQualityCandidates(stocks) {
  const stockByCode = new Map(stocks.map((stock) => [stock.code, stock]));
  const rankings = state.investmentScreensPayload?.rankings?.quality_equal_weight_basket || [];

  return rankings.map((ranking, index) => {
    const code = ranking.ticker;
    const screen = state.investmentScreenByCode.get(code) || {};
    const quality = screen.quality || {};
    const nEstimate = screen.n || {};
    const rawStock = state.rawStockByCode.get(code);
    const stock = stockByCode.get(code)
      || (rawStock ? enrichStock(rawStock) : {});
    const piotroski = quality.piotroski || {};

    return {
      ...stock,
      code,
      name: stock.name || ranking.company || screen.company || code,
      market: stock.market || screen.market,
      market_label: stock.market_label || screen.market,
      sector: screen.sector || stock.sector || "-",
      qualityRank: ranking.rank || index + 1,
      gpa: quality.gpa_pct,
      piotroskiScore: piotroski.score_partial,
      piotroskiKnown: piotroski.known_criteria_count,
      epsCv: quality.eps_cv_5y,
      debtPass: quality.conditions?.debt_to_equity_le_100pct,
      shareholderReturnPass: quality.conditions?.dividend_or_buyback_recent_3y,
      estimatedNBase: nEstimate.base_years,
      nModel: nEstimate,
      nConfidence: nEstimate.confidence?.label,
      nConfidenceScore: nEstimate.confidence?.score_0_to_100,
      equalWeight: ranking.weight_pct,
      canOpenValuation: Boolean(rawStock)
    };
  });
}

function metricClass(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "metric-neutral";
  }
  if (value > 0) return "metric-positive";
  if (value < 0) return "metric-negative";
  return "metric-neutral";
}

function formatRange(start, end, formatter) {
  if (start === null && end === null) {
    return "N/A";
  }
  if (start === null || end === null) {
    return formatter(start ?? end);
  }

  return `${formatter(start)} ~ ${formatter(end)}`;
}

function updateSortHeaders() {
  Array.from(document.querySelectorAll("th[data-sort-key]")).forEach((th) => {
    const isActive = th.dataset.sortKey === state.sortKey;
    th.classList.toggle("is-active", isActive);
    th.classList.toggle("asc", isActive && state.sortDirection === "asc");
    th.classList.toggle("desc", isActive && state.sortDirection === "desc");
  });
}

function updatePrioritySortHeaders() {
  Array.from(document.querySelectorAll("th[data-priority-sort-key]")).forEach((th) => {
    const isActive = th.dataset.prioritySortKey === state.prioritySortKey;
    th.classList.toggle("is-active", isActive);
    th.classList.toggle("asc", isActive && state.prioritySortDirection === "asc");
    th.classList.toggle("desc", isActive && state.prioritySortDirection === "desc");
  });
}

const SCREEN_PENDING_REASON_LABELS = {
  buffett: {
    recent_3y_persistence: "최근 3개 연속 사업연도 ROIC·ROE 이력 부족",
    cash_to_market_cap: "현금/시가총액 비율 계산 데이터 부족",
    supporting_buffett_condition: "기존 7개 조건의 강점 판정 데이터 부족",
    persistence_9_of_10: "10년 ROIC·ROE 이력 부족",
    positive_net_income_all_10y: "10년 순이익 이력 부족",
    gross_margin_sigma_le_5pp: "10년 매출총이익률 이력 부족",
    fcf_conversion_ge_0_8: "FCF 전환율 계산 데이터 부족",
    net_debt_to_ebitda_le_2_or_net_cash: "순부채·EBITDA 데이터 부족",
    shares_not_increased_10y: "10년 발행주식수 이력 부족",
    incremental_roic_ge_15_or_payout_ge_50: "증분 ROIC·주주환원 데이터 부족"
  },
  quality: {
    gpa_market_top_30pct: "GP/A 시장 순위 데이터 부족",
    piotroski_f_score_ge_7: "F-Score 계산 데이터 부족",
    eps_cv_market_lowest: "EPS 변동성 데이터 부족",
    debt_to_equity_le_100pct: "부채비율 데이터 부족",
    dividend_or_buyback_recent_3y: "최근 3년 배당·자사주 데이터 부족"
  }
};

function screenPendingRows(mode) {
  const results = state.investmentScreensPayload?.results || {};
  const labels = SCREEN_PENDING_REASON_LABELS[mode] || {};
  return Object.values(results)
    .filter((row) => mode === "buffett"
      ? (row?.buffett?.watchlist_status || row?.buffett?.business_quality_status) === "pending"
      : row?.quality?.status === "pending")
    .map((row) => {
      const missing = mode === "buffett"
        ? row?.buffett?.missing_reasons || row?.buffett?.coverage?.missing || []
        : row?.quality?.coverage?.missing || [];
      return {
        code: row.ticker,
        company: row.company || row.ticker,
        market: row.market || "-",
        reasons: missing.map((key) => labels[key] || key)
      };
    })
    .sort((a, b) => (
      String(a.company).localeCompare(String(b.company), "ko")
      || String(a.code).localeCompare(String(b.code))
    ));
}

function renderScreenPendingModal() {
  const modal = document.getElementById("screen-pending-modal");
  const container = document.getElementById("screen-pending-detail");
  const mode = state.pendingDetailMode;
  if (!modal || !container || !mode) {
    return;
  }

  const allRows = screenPendingRows(mode);
  const query = state.pendingDetailSearch.trim().toLowerCase();
  const visibleRows = query
    ? allRows.filter((row) => (
      `${row.code} ${row.company} ${row.market} ${row.reasons.join(" ")}`
        .toLowerCase()
        .includes(query)
    ))
    : allRows;
  const reasonCounts = new Map();
  allRows.forEach((row) => {
    row.reasons.forEach((reason) => {
      reasonCounts.set(reason, (reasonCounts.get(reason) || 0) + 1);
    });
  });
  const valuationCodes = new Set(state.rawStockByCode.keys());
  const title = mode === "buffett"
    ? "버핏 스타일 관심종목 · 판정 대기"
    : "퀄리티 팩터 · 데이터 부족 종목";

  container.innerHTML = `
    <button
      type="button"
      class="market-map-modal-close"
      data-screen-pending-close
      aria-label="판정 대기 종목 목록 닫기"
    >×</button>
    <div class="market-map-detail-head pending-detail-head">
      <div>
        <p>수집 실패가 아니라 최근 3년 수익성 또는 강점 조건 계산에 필요한 이력이 부족한 종목입니다.</p>
        <h3 id="screen-pending-modal-title">${escapeHtml(title)}</h3>
        <span>현재 ROE·ROA 필터를 통과한 종목은 누르면 가치평가 화면으로 이동합니다.</span>
      </div>
      <span class="market-map-detail-change">${allRows.length.toLocaleString("ko-KR")}개</span>
    </div>
    <div class="pending-detail-reason-summary">
      ${Array.from(reasonCounts.entries()).map(([reason, count]) => `
        <span>${escapeHtml(reason)} <strong>${count.toLocaleString("ko-KR")}</strong></span>
      `).join("")}
    </div>
    <label class="pending-detail-search">
      <span>종목·누락 사유 검색</span>
      <input
        id="screen-pending-search"
        type="search"
        value="${escapeHtml(state.pendingDetailSearch)}"
        placeholder="종목명, 코드 또는 누락 항목"
        autocomplete="off"
      >
    </label>
    <div class="pending-detail-list-meta">
      <span>${visibleRows.length.toLocaleString("ko-KR")}개 표시</span>
      <span>누락 사유는 한 종목에 여러 개일 수 있습니다.</span>
    </div>
    <div class="pending-detail-list">
      ${visibleRows.length ? visibleRows.map((row) => {
        const canOpen = valuationCodes.has(row.code);
        return `
          <button
            type="button"
            class="pending-detail-row"
            data-screen-pending-code="${escapeHtml(row.code)}"
            title="${canOpen ? "가치평가 화면에서 보기" : "현재 ROE·ROA 필터에서는 가치평가 이동 불가"}"
            ${canOpen ? "" : "disabled"}
          >
            <span class="pending-detail-company">
              <strong>${escapeHtml(row.company)}</strong>
              <small>${escapeHtml(`${row.code} · ${row.market}`)}</small>
            </span>
            <span class="pending-detail-reasons">
              ${(row.reasons.length ? row.reasons : ["분석 조건 데이터 부족"]).map((reason) => `
                <span>${escapeHtml(reason)}</span>
              `).join("")}
            </span>
          </button>
        `;
      }).join("") : `
        <div class="market-map-detail-empty">
          <strong>검색 결과가 없습니다.</strong>
          <span>다른 종목명이나 누락 항목으로 검색해보세요.</span>
        </div>
      `}
    </div>
  `;
}

function openScreenPendingModal(mode) {
  state.pendingDetailMode = mode;
  state.pendingDetailSearch = "";
  const modal = document.getElementById("screen-pending-modal");
  if (!modal) {
    return;
  }
  modal.hidden = false;
  document.body.classList.add("market-map-modal-open");
  renderScreenPendingModal();
  window.setTimeout(() => document.getElementById("screen-pending-search")?.focus(), 0);
}

function closeScreenPendingModal({ returnFocus = true } = {}) {
  const mode = state.pendingDetailMode;
  state.pendingDetailMode = null;
  state.pendingDetailSearch = "";
  document.getElementById("screen-pending-modal")?.setAttribute("hidden", "");
  document.body.classList.remove("market-map-modal-open");
  if (returnFocus) {
    const triggerId = mode === "quality"
      ? "quality-pending-badge"
      : "buffett-pending-badge";
    document.getElementById(triggerId)?.focus();
  }
}

function bindScreenPendingModal() {
  document.getElementById("buffett-pending-badge")?.addEventListener("click", () => {
    openScreenPendingModal("buffett");
  });
  document.getElementById("quality-pending-badge")?.addEventListener("click", () => {
    openScreenPendingModal("quality");
  });
  document.getElementById("screen-pending-modal")?.addEventListener("click", (event) => {
    if (event.target.closest("[data-screen-pending-close]")) {
      closeScreenPendingModal();
      return;
    }
    const row = event.target.closest("[data-screen-pending-code]");
    if (!row || row.disabled) {
      return;
    }
    const code = row.dataset.screenPendingCode;
    closeScreenPendingModal({ returnFocus: false });
    state.selectedCode = code;
    switchWorkspace("valuation");
    renderDashboard();
    window.setTimeout(() => {
      document.getElementById("selected-stock-workbench")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 120);
  });
  document.getElementById("screen-pending-modal")?.addEventListener("input", (event) => {
    if (event.target.id !== "screen-pending-search") {
      return;
    }
    state.pendingDetailSearch = event.target.value;
    renderScreenPendingModal();
    const search = document.getElementById("screen-pending-search");
    window.setTimeout(() => {
      search?.focus();
      search?.setSelectionRange(search.value.length, search.value.length);
    }, 0);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !document.getElementById("screen-pending-modal")?.hidden) {
      closeScreenPendingModal();
    }
  });
}

function renderPriorityCandidates(stocks) {
  const tbody = document.getElementById("priority-candidates-body");
  const countBadge = document.getElementById("priority-count-badge");
  const pendingBadge = document.getElementById("buffett-pending-badge");
  const updatedBadge = document.getElementById("buffett-updated-badge");
  const candidates = getPriorityCandidates(stocks);
  const strictCandidateCount = Number(
    state.investmentScreensPayload?.summary?.buffett_candidate_count || 0
  );
  const pendingCount = Number(
    state.investmentScreensPayload?.summary?.buffett_watchlist_status_counts?.pending
      ?? state.investmentScreensPayload?.summary?.buffett_status_counts?.pending
      ?? 0
  );

  countBadge.textContent = `${candidates.length}개 관심 · 엄격 통과 ${strictCandidateCount}개`;
  pendingBadge.textContent = pendingCount
    ? `${pendingCount.toLocaleString("ko-KR")}개 판정 대기`
    : "판정 대기 없음";
  pendingBadge.disabled = pendingCount === 0;
  pendingBadge.title = pendingCount
    ? "클릭하여 종목별 누락 사유 보기"
    : "판정 대기 종목이 없습니다.";
  if (updatedBadge) {
    updatedBadge.textContent = state.investmentScreensPayload?.generated_at_utc
      ? `산출 ${formatCompactDateTime(state.investmentScreensPayload.generated_at_utc)}`
      : "산출 시각 없음";
  }

  if (!candidates.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="12" class="empty-state">
          ${pendingCount
            ? `최근 3년 수익성 또는 강점 조건을 확정할 데이터가 부족합니다. ${pendingCount.toLocaleString("ko-KR")}개 종목을 판정 중입니다.`
            : "최근 3년 수익성 최소조건과 기존 강점 조건을 함께 통과한 종목이 없습니다."}
        </td>
      </tr>
    `;
    return;
  }

  updatePrioritySortHeaders();

  tbody.innerHTML = candidates.map((stock) => `
    <tr data-code="${stock.code}" class="${stock.canOpenValuation ? "" : "is-static-row"}">
      <td class="buffett-rank-cell"><span class="rank-chip">${stock.buffettRank}</span></td>
      <td class="buffett-identity-cell">
        <span class="buffett-name-cell">
          <span class="name-cell">
            <span>${escapeHtml(stock.name)}</span>
            <span class="${getMarketBadgeClass(stock)}">${getMarketLabel(stock)}</span>
            ${stock.strictCandidate ? '<span class="buffett-strict-badge">7개+가치 통과</span>' : ""}
          </span>
          <span class="buffett-strength-tags">
            ${stock.strengthTags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}
            ${stock.riskTags.map((tag) => `<span class="is-warning">${escapeHtml(tag)}</span>`).join("")}
          </span>
        </span>
      </td>
      <td class="buffett-sector-cell">${escapeHtml(stock.sector || "-")}</td>
      <td class="buffett-return-cell" title="${escapeHtml(stock.recentReturnValues.map((value) => formatPercent(value, 1)).join(" · "))}">
        <div>3년 ${escapeHtml(stock.recentReturnMetric || "ROIC")} ${formatPercent(stock.recentReturnAverage, 1)}</div>
        <div class="table-subtext">최신 ROIC ${formatPercent(stock.latestRoic, 1)} · ROE ${formatPercent(stock.latestRoe, 1)}</div>
      </td>
      <td class="buffett-metric-cell">${formatPercent(stock.grossMarginSigma, 1)}</td>
      <td class="buffett-metric-cell">${stock.fcfConversion === null || stock.fcfConversion === undefined ? "N/A" : formatPercent(stock.fcfConversion * 100, 1)}</td>
      <td class="buffett-metric-cell">${formatNumber(stock.netDebtToEbitda, 2)}</td>
      <td class="buffett-metric-cell">${formatPercent(stock.incrementalRoic, 1)}</td>
      <td class="buffett-metric-cell">${formatPercent(stock.payoutRatio, 1)}</td>
      <td class="buffett-metric-cell buffett-fcf-yield-cell ${metricClass(stock.fcfYield)}">
        <div>${formatPercent(stock.fcfYield, 1)}</div>
        <div class="table-subtext">${stock.fcfYieldBasis === "10y_average" ? "10년 평균" : stock.fcfYieldBasis === "3y_average_fallback" ? "최근 3년 평균" : "산출 불가"} · 현금/시총 ${formatPercent(stock.cashToMarketCap, 1)}</div>
      </td>
      <td class="buffett-metric-cell"><div>${formatYears(stock.estimatedNBase)}</div><div class="table-subtext">${nEstimateMethodLabel(stock.nModel)}</div></td>
      <td class="buffett-metric-cell">${confidenceLabel(stock.nConfidence)} · ${formatNumber(stock.nConfidenceScore, 0)}</td>
    </tr>
  `).join("");

  Array.from(tbody.querySelectorAll("tr[data-code]")).forEach((row) => {
    row.addEventListener("click", () => {
      const stock = candidates.find((candidate) => candidate.code === row.dataset.code);
      if (!stock?.canOpenValuation) {
        return;
      }
      state.selectedCode = row.dataset.code;
      renderDashboard();
      switchWorkspace("valuation");
      setTimeout(() => {
        document.getElementById("selected-stock-workbench")
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 180);
    });
  });
}

function renderQualityCandidates(stocks) {
  const tbody = document.getElementById("quality-candidates-body");
  const countBadge = document.getElementById("quality-count-badge");
  const pendingBadge = document.getElementById("quality-pending-badge");
  const updatedBadge = document.getElementById("quality-updated-badge");
  const candidates = getQualityCandidates(stocks);
  const eligibleCount = Number(
    state.investmentScreensPayload?.summary?.quality_eligible_count || 0
  );
  const pendingCount = Number(
    state.investmentScreensPayload?.summary?.quality_status_counts?.pending || 0
  );

  countBadge.textContent = `${candidates.length}개 바스켓 · 전체 통과 ${eligibleCount.toLocaleString("ko-KR")}개`;
  pendingBadge.textContent = pendingCount
    ? `${pendingCount.toLocaleString("ko-KR")}개 판정 대기`
    : "판정 대기 없음";
  pendingBadge.disabled = pendingCount === 0;
  pendingBadge.title = pendingCount
    ? "클릭하여 종목별 누락 사유 보기"
    : "판정 대기 종목이 없습니다.";
  if (updatedBadge) {
    updatedBadge.textContent = state.investmentScreensPayload?.generated_at_utc
      ? `산출 ${formatCompactDateTime(state.investmentScreensPayload.generated_at_utc)}`
      : "산출 시각 없음";
  }

  if (!candidates.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="11" class="empty-state">
          ${pendingCount
            ? `퀄리티 조건 계산이 진행 중입니다. ${pendingCount.toLocaleString("ko-KR")}개 종목이 아직 판정 대기 상태입니다.`
            : "퀄리티 전 조건을 통과한 종목이 없습니다."}
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = candidates.map((stock) => `
    <tr data-code="${stock.code}" class="${stock.canOpenValuation ? "" : "is-static-row"}">
      <td><span class="rank-chip">${stock.qualityRank}</span></td>
      <td>
        <span class="name-cell">
          <span>${escapeHtml(stock.name)}</span>
          <span class="${getMarketBadgeClass(stock)}">${getMarketLabel(stock)}</span>
        </span>
      </td>
      <td>${escapeHtml(stock.sector || "-")}</td>
      <td>${formatPercent(stock.gpa, 1)}</td>
      <td>${stock.piotroskiScore === null || stock.piotroskiScore === undefined
        ? "N/A"
        : `${stock.piotroskiScore}/${stock.piotroskiKnown || 9}`}</td>
      <td>${formatNumber(stock.epsCv, 3)}</td>
      <td>${stock.debtPass === true ? '<span class="status-badge">통과</span>' : '<span class="table-subtext">확인 필요</span>'}</td>
      <td>${stock.shareholderReturnPass === true ? '<span class="status-badge">확인</span>' : '<span class="table-subtext">확인 필요</span>'}</td>
      <td><div>${formatYears(stock.estimatedNBase)}</div><div class="table-subtext">${nEstimateMethodLabel(stock.nModel)}</div></td>
      <td>${confidenceLabel(stock.nConfidence)} · ${formatNumber(stock.nConfidenceScore, 0)}</td>
      <td>${formatPercent(stock.equalWeight, 2)}</td>
    </tr>
  `).join("");

  Array.from(tbody.querySelectorAll("tr[data-code]")).forEach((row) => {
    row.addEventListener("click", () => {
      const stock = candidates.find((candidate) => candidate.code === row.dataset.code);
      if (!stock?.canOpenValuation) {
        return;
      }
      state.selectedCode = row.dataset.code;
      renderDashboard();
      switchWorkspace("valuation");
      setTimeout(() => {
        document.getElementById("selected-stock-workbench")
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 180);
    });
  });
}

function bindPrioritySortHeaders() {
  Array.from(document.querySelectorAll("th[data-priority-sort-key]")).forEach((th) => {
    th.addEventListener("click", () => {
      const { prioritySortKey } = th.dataset;
      if (state.prioritySortKey === prioritySortKey) {
        state.prioritySortDirection = state.prioritySortDirection === "desc" ? "asc" : "desc";
      } else {
        state.prioritySortKey = prioritySortKey;
        state.prioritySortDirection = ["name", "buffettRank"].includes(prioritySortKey)
          ? "asc"
          : "desc";
      }
      renderDashboard();
    });
  });
}

function renderTable(stocks) {
  const tbody = document.getElementById("roe-table-body");
  const countBadge = document.getElementById("roe-count-badge");
  const summaryBadge = document.getElementById("table-summary-badge");

  countBadge.textContent = `${stocks.length} Stocks`;
  summaryBadge.textContent = `ROE ${state.threshold}% 이상 · ROA ${state.minRoa}% 이상${state.exemptFinancialRoa ? " (금융업 예외)" : ""}`;

  if (!stocks.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="16" class="empty-state">조건에 맞는 종목이 없습니다.</td>
      </tr>
    `;
    return;
  }

  updateSortHeaders();

  tbody.innerHTML = stocks.map((stock, index) => `
    <tr
      data-code="${stock.code}"
      class="${stock.code === state.selectedCode ? "is-selected" : ""} ${stock.is_suspended ? "is-suspended" : ""}"
    >
      <td><span class="rank-chip">${index + 1}</span></td>
      <td>
        <span class="name-cell">
          <span>${stock.name}</span>
          <span class="${getMarketBadgeClass(stock)}">${getMarketLabel(stock)}</span>
          ${stock.is_suspended ? '<span class="status-badge">거래정지</span>' : ""}
        </span>
      </td>
      <td>${formatPercent(stock.roe, 2)}</td>
      <td>${formatPercent(stock.roa, 2)}</td>
      <td>${formatNumber(stock.pbr, 2)}</td>
      <td>${formatNumber(stock.per, 2)}</td>
      <td>${formatMarketCap(stock.market_cap_krw_100m)}</td>
      <td><div>${formatYears(stock.estimatedNBase)}</div><div class="table-subtext">${nEstimateMethodLabel(stock.nModel)}</div></td>
      <td>${formatYears(stock.marketImpliedN)}</td>
      <td>${formatPrice(stock.current_price)}</td>
      <td>${formatPrice(stock.fairPriceConservative)}</td>
      <td>${formatPrice(stock.fairPriceBase)}</td>
      <td>${formatPrice(stock.fairPriceOptimistic)}</td>
      <td class="${metricClass(stock.gapRateBase)}">${formatRange(stock.gapRateConservative, stock.gapRateOptimistic, (value) => formatPercent(value, 1))}</td>
      <td class="${metricClass(stock.kellyRatioBase)}">${formatRange(stock.kellyRatioConservative, stock.kellyRatioOptimistic, (value) => formatPercent(value * 100, 1))}</td>
      <td>${stock.reporterCount ? `<div class="table-subtext">${stock.reporterCount}명</div><div class="table-subtext">${escapeHtml(summarizeReporterNames(stock.reporterNames))}</div>` : '<span class="table-subtext">공시 없음</span>'}</td>
    </tr>
  `).join("");

  Array.from(tbody.querySelectorAll("tr[data-code]")).forEach((row) => {
    row.addEventListener("click", () => {
      state.selectedCode = row.dataset.code;
      renderDashboard();
      setTimeout(() => {
        document.getElementById("selected-stock-workbench")
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 80);
    });
  });
}

function renderSelectedSummary(stock) {
  const container = document.getElementById("selected-stock-summary");
  const name = document.getElementById("selected-workbench-name");
  const code = document.getElementById("selected-workbench-code");
  const market = document.getElementById("selected-workbench-market");

  if (!stock) {
    if (name) name.textContent = "선택 종목";
    if (code) code.textContent = "선택 없음";
    if (market) market.textContent = "가치평가 테이블에서 종목을 선택하세요";
    container.innerHTML = "<div class='empty-state'>선택된 종목이 없습니다.</div>";
    return;
  }

  if (name) name.textContent = stock.name;
  if (code) code.textContent = stock.code;
  if (market) {
    market.textContent = `${getMarketLabel(stock)} · 현재가 ${formatPrice(stock.current_price)}`;
  }

  const financials = stock.investmentScreen?.long_term_financials || {};
  const period = financials.period || {};
  const latest = financials.latest || {};
  const averages = financials.averages || {};
  const cagr = financials.cagr || {};
  const annual = Array.isArray(financials.annual)
    ? [...financials.annual].sort((a, b) => Number(a.year) - Number(b.year))
    : [];
  const valuation = financials.market_valuation || {};
  const buffettValuation = stock.investmentScreen?.buffett?.valuation || {};
  const periodLabel = period.start_year && period.end_year
    ? `${period.start_year}–${period.end_year}`
    : "장기 재무 기간 미확정";
  const observationLabel = period.observation_count
    ? `${period.observation_count}개 사업연도${period.consecutive ? " 연속" : " · 일부 결측"}`
    : "DART 장기 이력 부족";
  const fcfBasisLabel = buffettValuation.normalized_fcf_basis === "10y_average"
    ? "10년 평균 FCF"
    : buffettValuation.normalized_fcf_basis === "3y_average_fallback"
    ? "최근 3년 평균 FCF"
    : "정상 FCF 산출 불가";
  const epsGrowthLabel = cagr.eps_source === "net_income_cagr_split_fallback"
    ? `${periodLabel} · 주식분할 구간은 순이익 CAGR로 보정`
    : cagr.eps_source === "net_income_cagr_share_data_fallback"
    ? `${periodLabel} · 주식수 결측으로 순이익 CAGR 대체`
    : periodLabel;
  const summaryCard = (label, value, subtext = "") => `
    <div class="summary-card">
      <span class="label">${escapeHtml(label)}</span>
      <span class="value">${value}</span>
      ${subtext ? `<span class="summary-subtext">${subtext}</span>` : ""}
    </div>
  `;
  const annualRows = [
    ["ROE", "roe_pct", (value) => formatPercent(value, 1)],
    ["PBR", "pbr", (value) => `${formatNumber(value, 2)}×`],
    ["ROIC", "roic_pct", (value) => formatPercent(value, 1)],
    ["ROCE", "roce_pct", (value) => formatPercent(value, 1)],
    ["영업이익률", "operating_margin_pct", (value) => formatPercent(value, 1)],
    ["매출 YoY", "revenue_growth_yoy_pct", (value) => formatPercent(value, 1)],
    ["FCF / 순이익", "fcf_to_net_income_pct", (value) => formatPercent(value, 0)],
    ["부채 / 자본", "debt_to_equity_pct", (value) => formatPercent(value, 0)]
  ];
  const annualMatrix = annual.length ? `
    <div class="annual-matrix-scroll" tabindex="0" aria-label="${escapeHtml(stock.name)} 연도별 10년 재무지표">
      <table class="annual-matrix">
        <thead>
          <tr>
            <th scope="col">지표</th>
            ${annual.map((row) => `<th scope="col">${escapeHtml(String(row.year))}</th>`).join("")}
          </tr>
        </thead>
        <tbody>
          ${annualRows.map(([label, key, formatter]) => `
            <tr>
              <th scope="row">${escapeHtml(label)}</th>
              ${annual.map((row) => {
                const value = row[key];
                const missing = value === null || value === undefined || !Number.isFinite(Number(value));
                return `<td class="${missing ? "is-missing" : ""}">${missing ? "—" : formatter(Number(value))}</td>`;
              }).join("")}
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  ` : `<div class="annual-matrix-empty">연도별 DART 재무 이력이 부족합니다.</div>`;

  container.innerHTML = `
    <div class="summary-hero">
      <div class="summary-identity-row">
        <div>
          <div class="summary-code">${escapeHtml(stock.code)}</div>
          <div class="summary-name">${escapeHtml(stock.name)}</div>
        </div>
        <span>10년 연도별 비교</span>
      </div>
      <div class="summary-period">${escapeHtml(periodLabel)} · ${escapeHtml(observationLabel)}</div>
      ${annualMatrix}
      <div class="summary-market-strip">
        <div><span>현재가</span><strong>${formatPrice(stock.current_price)}</strong></div>
        <div><span>시가총액</span><strong>${formatMarketCap(stock.market_cap_krw_100m)}</strong></div>
        <div><span>고ROE N</span><strong>${formatYears(stock.estimatedNBase)}</strong></div>
      </div>
    </div>

    <div class="summary-grid">
      ${summaryCard("ROE", formatPercent(latest.roe_pct, 1), `장기 평균 ${formatPercent(averages.roe_pct, 1)}`)}
      ${summaryCard("ROIC", formatPercent(latest.roic_pct, 1), `장기 평균 ${formatPercent(averages.roic_pct, 1)}`)}
      ${summaryCard("ROCE", formatPercent(latest.roce_pct, 1), `장기 평균 ${formatPercent(averages.roce_pct, 1)}`)}
      ${summaryCard("영업이익률", formatPercent(latest.operating_margin_pct, 1), `장기 평균 ${formatPercent(averages.operating_margin_pct, 1)}`)}
      ${summaryCard("매출 CAGR", formatPercent(cagr.revenue_pct, 1), periodLabel)}
      ${summaryCard("영업이익 CAGR", formatPercent(cagr.operating_income_pct, 1), periodLabel)}
      ${summaryCard("순이익 CAGR", formatPercent(cagr.net_income_pct, 1), periodLabel)}
      ${summaryCard("EPS CAGR", formatPercent(cagr.eps_pct, 1), epsGrowthLabel)}
      ${summaryCard("현재 PER / PBR", `${formatNumber(valuation.per, 2)}× / ${formatNumber(valuation.pbr, 2)}×`, "현재 시장가격 기준")}
      ${summaryCard("장기 EPS PEG", formatNumber(valuation.peg_eps_cagr_long_term, 2), `현재 PER ÷ 보정 EPS CAGR`)}
      ${summaryCard("피터 린치식 PEG", formatNumber(valuation.lynch_peg_eps_cagr_long_term_plus_dividend, 2), `EPS 성장 + 배당 ${formatPercent(valuation.dividend_yield_pct, 1)}`)}
      ${summaryCard("이익 / 정상 FCF 수익률", `${formatPercent(valuation.earnings_yield_pct, 1)} / ${formatPercent(buffettValuation.fcf_yield_pct, 1)}`, fcfBasisLabel)}
      ${summaryCard("부채 / 자본", formatPercent(latest.debt_to_equity_pct, 1), "DART 최신 사업연도")}
      ${summaryCard("버핏 스타일 / 퀄리티", `${screenStatusLabel(stock.investmentScreen?.buffett?.watchlist_status)} / ${screenStatusLabel(stock.investmentScreen?.quality?.status)}`, stock.investmentScreen?.quality?.selected_for_basket ? "퀄리티 바스켓 포함" : "현재 판정")}
    </div>
    <div class="summary-method-note">
      연도별 PBR = 네이버 연말 종가 ÷ DART 해당 연도 지배주주 BPS · ROCE = 영업이익 ÷ (총자산 − 유동부채) · CAGR은 양수인 시작·종료값만 산출 · 주식분할 구간의 EPS 성장률은 지배주주 순이익 CAGR로 보정
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
        <div class="label">고ROE 지속기간 N</div>
        <div class="value">${formatYears(stock.estimatedNBase)}</div>
      </div>
      <div class="calc-item">
        <div class="label">시장 내재 N</div>
        <div class="value">${formatYears(stock.marketImpliedN)}</div>
      </div>
      <div class="calc-item">
        <div class="label">${stock.nModel.engine === "empirical_persistence" ? "지속기간 N 신뢰도" : "임시 N 점수"}</div>
        <div class="value">
          ${stock.nModel.engine === "empirical_persistence"
            ? `${escapeHtml(stock.nModel.confidence?.label || "low")} · ${formatNumber(stock.estimatedNScore, 1)}/100`
            : `${formatNumber(stock.estimatedNScore, 1)}점`}
        </div>
      </div>
      <div class="calc-item">
        <div class="label">지속기간 N 보정치</div>
        <div class="value">${formatSignedYears(state.durationOffset)}</div>
      </div>
      <div class="calc-item">
        <div class="label">ROE 평균 / 변동성</div>
        <div class="value">
          ${formatPercent(stock.nModel.avgRoe, 1)} /
          ${formatNumber(stock.nModel.roeStd, 1)}
        </div>
      </div>
      <div class="calc-item">
        <div class="label">고ROE 유지연수</div>
        <div class="value">${stock.nModel.highRoeYears}년</div>
      </div>
      <div class="calc-item">
        <div class="label">지속기간 산출 방식</div>
        <div class="value">${nEstimateMethodLabel(stock.nModel)}</div>
      </div>
    </div>
    <div class="calc-note">
      ${stock.nModel.engine === "empirical_persistence"
        ? `업종별 4년 ROE 자기상관, 고ROE 생존기간과 기업별 변동성·재투자율·GP/A 수정자를 결합한 향후 고ROE 지속기간입니다. 산출 상태는 ${nEstimateMethodLabel(stock.nModel)}입니다.`
        : "아직 실증 지속기간 데이터가 없는 종목이므로 기존 임시 점수표를 사용하며, 적정가에도 이 임시 N이 적용됩니다."}
      시장 내재 N은 현재 PBR과 현재 ROE를 할인율 10%로 역산한 값입니다.
      |ROE − 10%|가 2%p 미만이면 값이 발산하므로 N/A로 표시합니다.
      엔진 N과의 단순 대소 비교는 ROE가 10%보다 높은 구간에서만 유효하며, 그보다 낮으면 N이 클수록 시장이 부진을 더 오래 반영한다는 뜻입니다.
    </div>
  `;
}

function renderFairValuePanel(stock) {
  const container = document.getElementById("fair-value-panel");

  if (!stock) {
    container.innerHTML = "<div class='empty-state'>선택 종목이 없습니다.</div>";
    return;
  }

  const scenarios = [
    ["보수적", stock.scenarios.conservative],
    ["기준", stock.scenarios.base],
    ["낙관적", stock.scenarios.optimistic]
  ];

  container.innerHTML = `
    <div class="scenario-grid">
      ${scenarios.map(([label, scenario]) => `
        <div class="calc-item">
          <div class="label">${label} 시나리오</div>
          <div class="value">${formatPrice(scenario.fairPrice)}</div>
          <div class="table-subtext">
            ROE ${formatPercent(scenario.params.assumedRoe, 1)} ·
            N ${scenario.params.durationYears}년
          </div>
        </div>
      `).join("")}
    </div>
    <div class="calc-grid">
      <div class="calc-item">
        <div class="label">추정 ROE 범위</div>
        <div class="value">${formatRange(stock.recommendedRoeConservative, stock.recommendedRoeOptimistic, (value) => formatPercent(value, 1))}</div>
      </div>
      <div class="calc-item">
        <div class="label">추정 ROE 보정치</div>
        <div class="value">${formatSignedPercent(state.roeAdjustment, 1)}</div>
      </div>
      <div class="calc-item">
        <div class="label">고ROE 지속기간 N</div>
        <div class="value">${formatYears(stock.estimatedNBase)}</div>
      </div>
      <div class="calc-item">
        <div class="label">시장 내재 N</div>
        <div class="value">${formatYears(stock.marketImpliedN)}</div>
      </div>
      <div class="calc-item">
        <div class="label">할인율</div>
        <div class="value">${formatPercent(state.discountRate, 1)}</div>
      </div>
    </div>
    <div class="calc-note">
      기준 시나리오 입력값 · BPS <strong>${formatPrice(stock.bps)}</strong> · ROE <strong>${formatPercent(stock.scenarios.base.params.assumedRoe, 1)}</strong> · N <strong>${formatYears(stock.scenarios.base.params.durationYears)}</strong> · 할인율 <strong>${formatPercent(stock.scenarios.base.params.discountRate, 1)}</strong>
    </div>
  `;
}

function renderKellyPanel(stock) {
  const container = document.getElementById("kelly-panel");

  if (!stock) {
    container.innerHTML = "<div class='empty-state'>선택 종목이 없습니다.</div>";
    return;
  }

  const scenarios = [
    ["보수적", stock.scenarios.conservative],
    ["기준", stock.scenarios.base],
    ["낙관적", stock.scenarios.optimistic]
  ];

  container.innerHTML = `
    <div class="scenario-grid">
      ${scenarios.map(([label, scenario]) => {
        const payoutMultiple = scenario.fairPrice && stock.current_price
          ? scenario.fairPrice / stock.current_price
          : null;

        return `
          <div class="calc-item">
            <div class="label">${label} 켈리</div>
            <div class="value ${metricClass(scenario.kellyRatio)}">${scenario.kellyRatio === null ? "N/A" : formatPercent(scenario.kellyRatio * 100, 1)}</div>
            <div class="table-subtext">
              b ${payoutMultiple === null ? "N/A" : formatNumber(payoutMultiple, 2)} ·
              괴리율 ${formatPercent(scenario.gapRate, 1)}
            </div>
          </div>
        `;
      }).join("")}
    </div>
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
        <div class="label">괴리율 범위</div>
        <div class="value ${metricClass(stock.gapRateBase)}">${formatRange(stock.gapRateConservative, stock.gapRateOptimistic, (value) => formatPercent(value, 1))}</div>
      </div>
      <div class="calc-item">
        <div class="label">켈리 범위</div>
        <div class="value ${metricClass(stock.kellyRatioBase)}">${formatRange(stock.kellyRatioConservative, stock.kellyRatioOptimistic, (value) => formatPercent(value * 100, 1))}</div>
      </div>
    </div>
    <div class="calc-note">
      켈리 공식은 <strong>K = p - (1-p) / b</strong>를 사용합니다.
      현재 단계에서는 승률과 패배확률을 각각 50%로 두고, 고ROE 지속기간 N과 과거 ROE 추정치 기반의 적정가 범위로 켈리 범위를 계산합니다.
    </div>
  `;
}

function renderDashboard() {
  const stocks = getFilteredStocks();
  let selectedRawStock = state.rawStockByCode.get(state.selectedCode) || null;

  if (!state.selectedCode || !selectedRawStock) {
    state.selectedCode = stocks[0]?.code ?? null;
    selectedRawStock = state.rawStockByCode.get(state.selectedCode) || null;
  }

  const selectedStock = stocks.find((stock) => stock.code === state.selectedCode)
    || (selectedRawStock ? enrichStock(selectedRawStock) : null);

  renderPriorityCandidates(stocks);
  renderQualityCandidates(stocks);
  renderTable(stocks);
  renderSelectedSummary(selectedStock);
  renderDurationPanel(selectedStock);
  renderFairValuePanel(selectedStock);
  renderKellyPanel(selectedStock);
}

function syncControlLabels() {
  document.getElementById("discount-value").textContent = `${formatNumber(state.discountRate, 1)}%`;
  document.getElementById("duration-value").textContent = formatSignedYears(state.durationOffset);
}

function bindControls() {
  const thresholdSelect = document.getElementById("roe-threshold-select");
  const roaThresholdSelect = document.getElementById("roa-threshold-select");
  const financialRoaExemptInput = document.getElementById("financial-roa-exempt-input");
  const discountRange = document.getElementById("discount-range");
  const durationRange = document.getElementById("duration-range");
  const roeAdjustmentInput = document.getElementById("assumed-roe-input");

  thresholdSelect.value = String(state.threshold);
  roaThresholdSelect.value = String(state.minRoa);
  financialRoaExemptInput.checked = state.exemptFinancialRoa;
  discountRange.value = String(state.discountRate);
  durationRange.value = String(state.durationOffset);
  roeAdjustmentInput.value = String(state.roeAdjustment);
  syncControlLabels();

  thresholdSelect.addEventListener("change", (event) => {
    state.threshold = Number(event.target.value);
    renderDashboard();
  });

  roaThresholdSelect.addEventListener("change", (event) => {
    state.minRoa = Number(event.target.value);
    renderDashboard();
  });

  financialRoaExemptInput.addEventListener("change", (event) => {
    state.exemptFinancialRoa = event.target.checked;
    renderDashboard();
  });

  discountRange.addEventListener("input", (event) => {
    state.discountRate = Number(event.target.value);
    syncControlLabels();
    renderDashboard();
  });

  durationRange.addEventListener("input", (event) => {
    state.durationOffset = Number(event.target.value);
    syncControlLabels();
    renderDashboard();
  });

  roeAdjustmentInput.addEventListener("input", (event) => {
    state.roeAdjustment = Number(event.target.value);
    renderDashboard();
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

function renderError(message) {
  document.getElementById("priority-candidates-body").innerHTML = `<tr><td colspan="12" class="empty-state">${message}</td></tr>`;
  document.getElementById("quality-candidates-body").innerHTML = `<tr><td colspan="11" class="empty-state">${message}</td></tr>`;
  document.getElementById("roe-table-body").innerHTML = `<tr><td colspan="16" class="empty-state">${message}</td></tr>`;
  document.getElementById("selected-stock-summary").innerHTML = `<div class="empty-state">${message}</div>`;
  document.getElementById("duration-panel").innerHTML = `<div class="empty-state">${message}</div>`;
  document.getElementById("fair-value-panel").innerHTML = `<div class="empty-state">${message}</div>`;
  document.getElementById("kelly-panel").innerHTML = `<div class="empty-state">${message}</div>`;
}

function buildRoeHistoryMap(payload) {
  const map = new Map();
  const rows = payload?.stocks || [];

  rows.forEach((row) => {
    if (row?.code) {
      map.set(row.code, row);
    }
  });

  return map;
}

function buildDartMajorMap(payload) {
  const map = new Map();
  const rows = payload?.stocks || [];

  rows.forEach((row) => {
    if (row?.code) {
      map.set(row.code, row);
    }
  });

  return map;
}

function buildFinancialNMap(payload) {
  const map = new Map();
  const estimates = payload?.estimates || {};

  Object.entries(estimates).forEach(([code, estimate]) => {
    if (code && estimate) {
      map.set(code, estimate);
    }
  });

  return map;
}

function buildInvestmentScreenMap(payload) {
  const map = new Map();
  const results = payload?.results || {};

  Object.entries(results).forEach(([code, result]) => {
    if (code && result) {
      map.set(code, result);
    }
  });

  return map;
}

async function loadStocks() {
  try {
    const marketPromise = fetch(MARKET_DATA_URL).then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status} for market data`);
      }
      return response.json();
    });

    const roePromise = fetch(ROE_HISTORY_URL)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status} for ROE history`);
        }
        return response.json();
      })
      .catch(() => ({ stocks: [] }));

    const dartPromise = fetch(DART_MAJOR_URL)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status} for DART major holders`);
        }
        return response.json();
      })
      .catch(() => ({ stocks: [] }));

    const financialNPromise = fetch(`${FINANCIAL_N_URL}?v=${Date.now()}`, {
      cache: "no-store"
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status} for financial N`);
        }
        return response.json();
      })
      .catch(() => ({ estimates: {} }));

    const investmentScreensPromise = fetch(`${INVESTMENT_SCREENS_URL}?v=${Date.now()}`, {
      cache: "no-store"
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status} for investment screens`);
        }
        return response.json();
      })
      .catch(() => ({ results: {} }));

    const [
      marketPayload,
      roePayload,
      dartPayload,
      financialNPayload,
      investmentScreensPayload
    ] = await Promise.all([
      marketPromise,
      roePromise,
      dartPromise,
      financialNPromise,
      investmentScreensPromise
    ]);

    state.rawStocks = marketPayload.stocks || [];
    state.rawStockByCode = new Map(
      state.rawStocks.map((stock) => [stock.code, stock])
    );
    state.roeHistoryByCode = buildRoeHistoryMap(roePayload);
    state.dartMajorByCode = buildDartMajorMap(dartPayload);
    state.financialNByCode = buildFinancialNMap(financialNPayload);
    state.investmentScreenByCode = buildInvestmentScreenMap(investmentScreensPayload);
    state.investmentScreensPayload = investmentScreensPayload;
    updateLastUpdated(marketPayload.crawled_at_utc);
    bindControls();
    bindPrioritySortHeaders();
    bindTableSortHeaders();
    renderDashboard();
    renderPortfolioBoard();
  } catch (error) {
    renderError("데이터를 불러오지 못했습니다. 최신 JSON을 다시 생성한 뒤 서버에서 페이지를 열어주세요.");
    console.error(error);
  }
}

function formatKrwCompact(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    return "N/A";
  }
  const absolute = Math.abs(amount);
  const sign = amount < 0 ? "-" : "";
  if (absolute >= 1_0000_0000_0000) {
    return `${sign}${formatNumber(absolute / 1_0000_0000_0000, 2)}조원`;
  }
  if (absolute >= 1_0000_0000) {
    return `${sign}${formatNumber(absolute / 1_0000_0000, 1)}억원`;
  }
  if (absolute >= 1_0000) {
    return `${sign}${formatNumber(absolute / 1_0000, 1)}만원`;
  }
  return `${formatInteger(amount)}원`;
}

function formatUsdCompact(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    return "N/A";
  }
  if (Math.abs(amount) >= 1e12) {
    return `$${formatNumber(amount / 1e12, 2)}T`;
  }
  if (Math.abs(amount) >= 1e9) {
    return `$${formatNumber(amount / 1e9, 2)}B`;
  }
  if (Math.abs(amount) >= 1e6) {
    return `$${formatNumber(amount / 1e6, 1)}M`;
  }
  return `$${formatNumber(amount, 0)}`;
}

function metricTone(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number === 0) {
    return "";
  }
  return number > 0 ? "money-positive" : "money-negative";
}

function kpiCard(label, value, note = "") {
  return `
    <div class="kpi-card">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      ${note ? `<small>${escapeHtml(note)}</small>` : ""}
    </div>
  `;
}

function emptyFeature(message) {
  return `<div class="empty-state">${escapeHtml(message)}</div>`;
}

async function fetchOptionalJson(url, fallback = {}) {
  try {
    const response = await fetch(`${url}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    console.warn(`Optional data unavailable: ${url}`, error);
    return { ...fallback, _unavailable: true, _url: url };
  }
}

function setWorkspaceLoading(name, loading) {
  const view = document.querySelector(`[data-workspace-view="${name}"]`);
  if (!view) {
    return;
  }
  view.classList.toggle("is-loading", loading);
}

async function loadWorkspaceData(name, force = false) {
  if (name === "valuation" || name === "priority") {
    return;
  }
  if ((!force && state.loadedWorkspaces.has(name)) || state.loadingWorkspaces.has(name)) {
    return;
  }
  state.loadingWorkspaces.add(name);
  setWorkspaceLoading(name, true);
  try {
    if (name === "korea") {
      const [flow, short] = await Promise.all([
        fetchOptionalJson(KOREA_FLOW_URL, { markets: {} }),
        fetchOptionalJson(KOREA_SHORT_URL, { markets: {} })
      ]);
      state.featureData.koreaFlow = flow;
      state.featureData.koreaShort = short;
      renderKoreaWorkspace();
    } else if (name === "disclosures") {
      const [filings, events, insiders] = await Promise.all([
        fetchOptionalJson(DART_DISCLOSURES_URL, { filings: [], category_counts: {} }),
        fetchOptionalJson(DART_EVENTS_URL, {
          counts: {},
          dividends: [],
          contracts: [],
          buybacks: [],
          convertible_bonds: []
        }),
        fetchOptionalJson(DART_INSIDERS_URL, {
          rows: [],
          confirmed_purchases: [],
          purchase_candidates: []
        })
      ]);
      state.featureData.dartFilings = filings;
      state.featureData.dartEvents = events;
      state.featureData.dartInsiders = insiders;
      renderDisclosureWorkspace();
    } else if (name === "us") {
      const [market, interest, volume, finnhub] = await Promise.all([
        fetchOptionalJson(US_MARKET_URL, { stocks: [] }),
        fetchOptionalJson(US_SHORT_INTEREST_URL, { rows: [] }),
        fetchOptionalJson(US_SHORT_VOLUME_URL, { symbols: [] }),
        fetchOptionalJson(FINNHUB_URL, { stocks: {} })
      ]);
      state.featureData.usMarket = market;
      state.featureData.usShortInterest = interest;
      state.featureData.usShortVolume = volume;
      state.featureData.finnhub = finnhub;
      renderUsWorkspace();
    } else if (name === "intelligence") {
      const [news, briefing, sec, finnhub] = await Promise.all([
        fetchOptionalJson(NAVER_NEWS_URL, { items: [] }),
        fetchOptionalJson(AI_BRIEFING_URL, {}),
        fetchOptionalJson(SEC_FILINGS_URL, { filings: {}, category_counts: {} }),
        fetchOptionalJson(FINNHUB_URL, { stocks: {} })
      ]);
      state.featureData.news = news;
      state.featureData.briefing = briefing;
      state.featureData.sec = sec;
      state.featureData.finnhub = finnhub;
      renderIntelligenceWorkspace();
    } else if (name === "data") {
      state.featureData.manifest = await fetchOptionalJson(DATA_MANIFEST_URL, { files: [] });
      renderDataWorkspace();
    }
    state.loadedWorkspaces.add(name);
  } finally {
    state.loadingWorkspaces.delete(name);
    setWorkspaceLoading(name, false);
  }
}

function switchWorkspace(name, updateHash = true) {
  const target = document.querySelector(`[data-workspace-view="${name}"]`);
  if (!target) {
    return;
  }
  state.activeWorkspace = name;
  document.querySelectorAll("[data-workspace-view]").forEach((view) => {
    view.classList.toggle("is-active", view === target);
  });
  document.querySelectorAll("[data-workspace]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.workspace === name);
  });
  if (updateHash) {
    history.replaceState(null, "", `#${name}`);
  }
  loadWorkspaceData(name);
  window.scrollTo({ top: document.querySelector(".workspace-tabs").offsetTop - 8, behavior: "smooth" });
}

function institutionNetValue(row) {
  const direct = Number(row?.["기관합계"]);
  if (Number.isFinite(direct)) {
    return direct;
  }
  return ["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금"]
    .reduce((sum, key) => sum + (Number(row?.[key]) || 0), 0);
}

function investorHistoryValue(row, investor) {
  if (investor === "foreign") {
    return Number(row?.["외국인"] ?? row?.["외국인합계"]) || 0;
  }
  if (investor === "individual") {
    return Number(row?.["개인"]) || 0;
  }
  return institutionNetValue(row);
}

function renderMultiLineChart(container, history, series) {
  if (!container || !history.length) {
    if (container) {
      container.innerHTML = emptyFeature("표시할 시계열 데이터가 없습니다.");
    }
    return;
  }
  const width = 920;
  const height = 260;
  const padding = { left: 58, right: 20, top: 22, bottom: 32 };
  const values = series.flatMap((item) => history.map((row) => Number(item.value(row)) || 0));
  const maximum = Math.max(...values.map((value) => Math.abs(value)), 1);
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const x = (index) => padding.left + (history.length === 1 ? plotWidth / 2 : index / (history.length - 1) * plotWidth);
  const y = (value) => padding.top + plotHeight / 2 - (value / maximum) * (plotHeight / 2 - 8);
  const lines = series.map((item) => {
    const points = history.map((row, index) => `${x(index)},${y(item.value(row))}`).join(" ");
    return `<polyline points="${points}" fill="none" stroke="${item.color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>`;
  }).join("");
  const zeroY = y(0);
  const firstDate = formatCompactDate(history[0]?.date);
  const lastDate = formatCompactDate(history.at(-1)?.date);
  container.innerHTML = `
    <div class="chart-legend">
      ${series.map((item) => `<span><i class="legend-dot" style="background:${item.color}"></i>${escapeHtml(item.label)}</span>`).join("")}
    </div>
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img">
      <line x1="${padding.left}" x2="${width - padding.right}" y1="${zeroY}" y2="${zeroY}" stroke="rgba(71,55,40,.22)" stroke-dasharray="5 5"></line>
      <text x="${padding.left}" y="${height - 9}" fill="#6e655c" font-size="12">${escapeHtml(firstDate)}</text>
      <text x="${width - padding.right}" y="${height - 9}" text-anchor="end" fill="#6e655c" font-size="12">${escapeHtml(lastDate)}</text>
      <text x="${padding.left - 8}" y="${padding.top + 5}" text-anchor="end" fill="#6e655c" font-size="11">${escapeHtml(formatKrwCompact(maximum))}</text>
      <text x="${padding.left - 8}" y="${height - padding.bottom}" text-anchor="end" fill="#6e655c" font-size="11">${escapeHtml(formatKrwCompact(-maximum))}</text>
      ${lines}
    </svg>
  `;
}

function renderKoreaWorkspace() {
  const flow = state.featureData.koreaFlow || {};
  const short = state.featureData.koreaShort || {};
  const kpiNode = document.getElementById("korea-market-kpis");
  const latestKospi = (flow?.markets?.KOSPI?.daily_net_value || []).at(-1);
  const latestKosdaq = (flow?.markets?.KOSDAQ?.daily_net_value || []).at(-1);
  kpiNode.innerHTML = [
    kpiCard("수급 기준일", flow.trade_date || "연결 대기", "18시 이후 확정"),
    kpiCard("코스피 외국인", formatKrwCompact(investorHistoryValue(latestKospi, "foreign")), "순매수"),
    kpiCard("코스닥 외국인", formatKrwCompact(investorHistoryValue(latestKosdaq, "foreign")), "순매수"),
    kpiCard("공매도 기준일", short.transaction_date || "연결 대기", `잔고 ${short.balance_date || "-"}`)
  ].join("");
  renderFlowSummary();
  renderFlowTickerTable();
  renderKoreaShortTable();
}

function renderFlowSummary() {
  const market = state.featureData.koreaFlow?.markets?.[state.flowMarket] || {};
  const history = market.daily_net_value || [];
  const latest = history.at(-1);
  const container = document.getElementById("flow-summary-cards");
  container.innerHTML = [
    ["외국인", "foreign"],
    ["기관", "institution"],
    ["개인", "individual"]
  ].map(([label, key]) => {
    const value = investorHistoryValue(latest, key);
    return `<div class="kpi-card"><span>${label} 순매수</span><strong class="${metricTone(value)}">${escapeHtml(formatKrwCompact(value))}</strong><small>${escapeHtml(formatCompactDate(latest?.date))}</small></div>`;
  }).join("");
  renderMultiLineChart(document.getElementById("flow-chart"), history, [
    { label: "외국인", color: "#b85c38", value: (row) => investorHistoryValue(row, "foreign") },
    { label: "기관", color: "#0a7a5f", value: (row) => investorHistoryValue(row, "institution") },
    { label: "개인", color: "#4a73b8", value: (row) => investorHistoryValue(row, "individual") }
  ]);
}

function renderFlowTickerTable() {
  const market = state.featureData.koreaFlow?.markets?.[state.flowMarket] || {};
  const investor = state.flowInvestor;
  const query = state.flowSearch.trim().toLowerCase();
  let rows = [...(market.by_ticker || [])].filter((row) => {
    const text = `${row.ticker || ""} ${row.name || ""}`.toLowerCase();
    return !query || text.includes(query);
  });
  rows.sort((left, right) => {
    const a = Number(left?.[investor]?.net_value) || 0;
    const b = Number(right?.[investor]?.net_value) || 0;
    return state.flowDirection === "buy" ? b - a : a - b;
  });
  rows = rows.slice(0, 100);
  const body = document.getElementById("flow-ticker-body");
  if (!rows.length) {
    body.innerHTML = "<tr><td colspan='6' class='empty-state'>수급 데이터가 아직 없습니다.</td></tr>";
    return;
  }
  body.innerHTML = rows.map((row, index) => {
    const metric = row[investor] || {};
    return `
      <tr data-select-korea-code="${escapeHtml(row.ticker || "")}">
        <td>${index + 1}</td>
        <td><strong>${escapeHtml(row.name || row.ticker || "-")}</strong><div class="table-subtext">${escapeHtml(row.ticker || "")}</div></td>
        <td class="${metricTone(metric.net_value)}">${escapeHtml(formatKrwCompact(metric.net_value))}</td>
        <td class="${metricTone(metric.net_volume)}">${escapeHtml(formatInteger(metric.net_volume))}주</td>
        <td>${escapeHtml(formatKrwCompact(metric.buy_value))}</td>
        <td>${escapeHtml(formatKrwCompact(metric.sell_value))}</td>
      </tr>
    `;
  }).join("");
}

function renderKoreaShortTable() {
  const short = state.featureData.koreaShort || {};
  const market = short?.markets?.[state.shortMarket] || {};
  const query = state.shortSearch.trim().toLowerCase();
  const head = document.getElementById("short-table-head");
  const body = document.getElementById("short-table-body");
  document.getElementById("short-delay-note").textContent =
    `거래 ${short.transaction_date || "-"} · 잔고 ${short.balance_date || "-"} · 잔고는 거래소 공개 시차가 있습니다.`;
  if (state.shortMode === "balance") {
    head.innerHTML = "<tr><th>순위</th><th>종목</th><th>잔고 수량</th><th>잔고 금액</th><th>시가총액</th><th>잔고 비중</th></tr>";
    const rows = (market.balance_top50 || []).filter((row) =>
      !query || `${row.ticker || ""} ${row.name || ""}`.toLowerCase().includes(query)
    );
    body.innerHTML = rows.length ? rows.map((row, index) => `
      <tr data-select-korea-code="${escapeHtml(row.ticker || "")}">
        <td>${escapeHtml(row.rank ?? index + 1)}</td>
        <td><strong>${escapeHtml(row.name || row.ticker || "-")}</strong><div class="table-subtext">${escapeHtml(row.ticker || "")}</div></td>
        <td>${escapeHtml(formatInteger(row.short_balance))}주</td>
        <td>${escapeHtml(formatKrwCompact(row.short_balance_value))}</td>
        <td>${escapeHtml(formatKrwCompact(row.market_cap))}</td>
        <td class="money-negative">${escapeHtml(formatPercent(row.balance_ratio, 2))}</td>
      </tr>
    `).join("") : "<tr><td colspan='6' class='empty-state'>공매도 잔고 데이터가 아직 없습니다.</td></tr>";
  } else {
    head.innerHTML = "<tr><th>순위</th><th>종목</th><th>공매도 거래대금</th><th>총 거래대금</th><th>대금 비중</th><th>거래량 비중</th></tr>";
    const rows = [...(market.by_ticker || [])]
      .filter((row) => !query || `${row.ticker || ""} ${row.name || ""}`.toLowerCase().includes(query))
      .sort((a, b) => Number(b.value_ratio || 0) - Number(a.value_ratio || 0))
      .slice(0, 100);
    body.innerHTML = rows.length ? rows.map((row, index) => `
      <tr data-select-korea-code="${escapeHtml(row.ticker || "")}">
        <td>${index + 1}</td>
        <td><strong>${escapeHtml(row.name || row.ticker || "-")}</strong><div class="table-subtext">${escapeHtml(row.ticker || "")}</div></td>
        <td>${escapeHtml(formatKrwCompact(row.short_value))}</td>
        <td>${escapeHtml(formatKrwCompact(row.total_value))}</td>
        <td class="money-negative">${escapeHtml(formatPercent(row.value_ratio, 2))}</td>
        <td>${escapeHtml(formatPercent(row.volume_ratio, 2))}</td>
      </tr>
    `).join("") : "<tr><td colspan='6' class='empty-state'>공매도 거래 데이터가 아직 없습니다.</td></tr>";
  }
}

function eventImpact(row, type) {
  if (type === "dividends") {
    return Number(row.market_yield_common_pct || row.total_dividend_krw || 0);
  }
  if (type === "contracts") {
    return Number(row.sales_ratio_pct || row.contract_amount_krw || 0);
  }
  if (type === "convertible_bonds") {
    return Number(row.dilution_pct || row.amount_krw || 0);
  }
  return Number(row.amount_krw || row.shares || 0);
}

function eventMetrics(row, type) {
  if (type === "dividends") {
    return [
      ["주당 배당", row.dps_common_krw == null ? "N/A" : formatPrice(row.dps_common_krw)],
      ["시가배당률", formatPercent(row.market_yield_common_pct, 2)],
      ["배당 총액", formatKrwCompact(row.total_dividend_krw)],
      ["배당 기준일", row.record_date || "N/A"]
    ];
  }
  if (type === "contracts") {
    return [
      ["계약 금액", formatKrwCompact(row.contract_amount_krw)],
      ["매출 대비", formatPercent(row.sales_ratio_pct, 2)],
      ["계약 상대", row.counterparty || "N/A"],
      ["종료일", row.end_date || "N/A"]
    ];
  }
  if (type === "convertible_bonds") {
    return [
      ["발행 금액", formatKrwCompact(row.amount_krw)],
      ["희석률", formatPercent(row.dilution_pct, 2)],
      ["전환가", formatPrice(row.conversion_price_krw)],
      ["표면이자", formatPercent(row.coupon_pct, 2)]
    ];
  }
  return [
    ["예정 금액", formatKrwCompact(row.amount_krw)],
    ["예정 수량", row.shares == null ? "N/A" : `${formatInteger(row.shares)}주`],
    ["보유 비중", formatPercent(row.treasury_held_pct, 2)],
    ["방법", row.method || row.category || "N/A"]
  ];
}

function renderDisclosureWorkspace() {
  const events = state.featureData.dartEvents || {};
  const insiders = state.featureData.dartInsiders || {};
  const filings = state.featureData.dartFilings || {};
  const counts = events.counts || {};
  document.getElementById("disclosure-kpis").innerHTML = [
    kpiCard("자사주", `${counts.buybacks || 0}건`, "취득·처분·신탁"),
    kpiCard("배당·수주", `${(counts.dividends || 0) + (counts.contracts || 0)}건`, `배당 ${counts.dividends || 0} · 수주 ${counts.contracts || 0}`),
    kpiCard("CB", `${counts.convertible_bonds || 0}건`, "금액·전환가·희석률"),
    kpiCard("임원 매수", `${insiders.confirmed_purchase_count || 0}건`, `증가 후보 ${insiders.purchase_candidate_count || 0}`)
  ].join("");
  renderEventCards();
  renderInsiderTable();
  renderFilingFeed();
}

function renderEventCards() {
  const rows = [...(state.featureData.dartEvents?.[state.eventType] || [])];
  const query = state.eventSearch.trim().toLowerCase();
  const filtered = rows.filter((row) =>
    !query || `${row.ticker || ""} ${row.company || ""} ${row.report_name || ""}`.toLowerCase().includes(query)
  );
  filtered.sort((a, b) => state.eventSort === "date"
    ? String(b.file_date || "").localeCompare(String(a.file_date || ""))
    : eventImpact(b, state.eventType) - eventImpact(a, state.eventType));
  const container = document.getElementById("event-cards");
  if (!filtered.length) {
    container.innerHTML = emptyFeature("해당 유형의 상세 공시가 아직 없습니다.");
    return;
  }
  container.innerHTML = filtered.slice(0, 60).map((row) => `
    <article class="event-card">
      <div class="event-card-head">
        <div>
          <h3>${escapeHtml(row.company || row.ticker || "-")}</h3>
          <p>${escapeHtml(row.ticker || "")} · ${escapeHtml(row.file_date || "-")}</p>
        </div>
        <span class="status-chip ${state.eventType === "convertible_bonds" ? "is-warning" : "is-positive"}">${escapeHtml(state.eventType === "convertible_bonds" ? "희석" : state.eventType === "contracts" ? "수주" : state.eventType === "dividends" ? "배당" : row.category || "자사주")}</span>
      </div>
      <div class="event-metrics">
        ${eventMetrics(row, state.eventType).map(([label, value]) => `<div class="event-metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}
      </div>
      <div class="event-card-meta">
        <p>${escapeHtml(row.purpose || row.report_name || "")}</p>
        ${row.dart_url ? `<a class="source-link" href="${escapeHtml(row.dart_url)}" target="_blank" rel="noopener">DART ↗</a>` : ""}
      </div>
    </article>
  `).join("");
}

function renderInsiderTable() {
  const payload = state.featureData.dartInsiders || {};
  let rows = state.insiderMode === "confirmed"
    ? payload.confirmed_purchases || []
    : state.insiderMode === "candidate"
      ? payload.purchase_candidates || []
      : payload.rows || [];
  const query = state.insiderSearch.trim().toLowerCase();
  rows = rows.filter((row) =>
    !query || `${row.ticker || ""} ${row.company || ""} ${row.filer || ""}`.toLowerCase().includes(query)
  ).slice(0, 150);
  const body = document.getElementById("insider-table-body");
  if (!rows.length) {
    body.innerHTML = "<tr><td colspan='9' class='empty-state'>조건에 맞는 임원·주요주주 증감이 없습니다.</td></tr>";
    return;
  }
  body.innerHTML = rows.map((row) => {
    const change = Number(row.shares_change);
    const chip = row.confirmed_purchase
      ? "<span class='status-chip is-positive'>매수 확인</span>"
      : row.purchase_candidate
        ? "<span class='status-chip is-warning'>보유 증가</span>"
        : change < 0
          ? "<span class='status-chip is-negative'>보유 감소</span>"
          : "<span class='status-chip'>변동</span>";
    return `
      <tr data-select-korea-code="${escapeHtml(row.ticker || "")}">
        <td>${escapeHtml(formatCompactDate(row.file_date))}</td>
        <td><strong>${escapeHtml(row.company || row.ticker || "-")}</strong><div class="table-subtext">${escapeHtml(row.ticker || "")}</div></td>
        <td>${escapeHtml(row.filer || "-")}</td>
        <td>${escapeHtml(row.position || "-")}</td>
        <td>${chip}</td>
        <td class="${metricTone(change)}">${change > 0 ? "+" : ""}${escapeHtml(formatInteger(change))}주</td>
        <td>${escapeHtml(formatKrwCompact(row.estimated_change_value_krw))}</td>
        <td>${escapeHtml((row.change_reasons || []).join(", ") || "미확인")}</td>
        <td>${row.dart_url ? `<a class="source-link" href="${escapeHtml(row.dart_url)}" target="_blank" rel="noopener">원문 ↗</a>` : "-"}</td>
      </tr>
    `;
  }).join("");
}

function renderFilingFeed() {
  const rows = state.featureData.dartFilings?.filings || [];
  const query = state.filingSearch.trim().toLowerCase();
  const filtered = rows.filter((row) => {
    const categories = row.categories || [];
    const categoryMatch = state.filingCategory === "all" || categories.includes(state.filingCategory);
    const text = `${row.stock_code || ""} ${row.corp_name || ""} ${row.report_nm || ""}`.toLowerCase();
    return categoryMatch && (!query || text.includes(query));
  }).slice(0, 200);
  const container = document.getElementById("filing-feed");
  container.innerHTML = filtered.length ? filtered.map((row) => `
    <a class="feed-item source-link" href="${escapeHtml(row.dart_url || "#")}" target="_blank" rel="noopener">
      <span class="status-chip">${escapeHtml((row.categories || [])[0] || "공시")}</span>
      <span class="feed-item-main">
        <strong>${escapeHtml(row.report_nm || "-")}</strong>
        <span>${escapeHtml(row.corp_name || "")} · ${escapeHtml(row.stock_code || "")} · 제출 ${escapeHtml(row.flr_nm || "-")}</span>
      </span>
      <span class="feed-date">${escapeHtml(formatCompactDate(row.rcept_dt))}</span>
    </a>
  `).join("") : emptyFeature("최근 DART 공시 데이터가 아직 없습니다.");
}

function renderUsWorkspace() {
  const market = state.featureData.usMarket || {};
  const interest = state.featureData.usShortInterest || {};
  const volume = state.featureData.usShortVolume || {};
  document.getElementById("us-market-kpis").innerHTML = [
    kpiCard("미국 종목", `${formatInteger(market.count || 0)}개`, `차트 ${formatInteger(market.history_count || 0)}개`),
    kpiCard("상승 종목", `${(market.stocks || []).filter((row) => Number(row.change_pct) > 0).length}개`, "당일 기준"),
    kpiCard("공매도 잔고", `${formatInteger(interest.count || 0)}개`, interest.settlement_date || "-"),
    kpiCard("일일 숏볼륨", `${formatInteger(volume.symbol_count || 0)}개`, volume.trade_date || "-")
  ].join("");
  renderUsStockTable();
  renderUsShortTable();
}

function usStockSortValue(row) {
  if (state.usStockSort === "change") {
    return Math.abs(Number(row.change_pct) || 0);
  }
  if (state.usStockSort === "return_1m") {
    return Number(row.metrics?.return_1m) || -Infinity;
  }
  if (state.usStockSort === "rsi") {
    return Number(row.metrics?.rsi14) || -Infinity;
  }
  return Number(row.market_cap_usd) || 0;
}

function renderUsStockTable() {
  const query = state.usStockSearch.trim().toLowerCase();
  let rows = [...(state.featureData.usMarket?.stocks || [])].filter((row) =>
    !query || `${row.symbol || ""} ${row.name || ""} ${row.sector || ""}`.toLowerCase().includes(query)
  );
  rows.sort((a, b) => usStockSortValue(b) - usStockSortValue(a));
  rows = rows.slice(0, 150);
  if (!state.usSelectedSymbol || !rows.some((row) => row.symbol === state.usSelectedSymbol)) {
    state.usSelectedSymbol = rows[0]?.symbol || null;
  }
  const body = document.getElementById("us-stock-table-body");
  body.innerHTML = rows.length ? rows.map((row) => `
    <tr data-us-symbol="${escapeHtml(row.symbol || "")}" class="${row.symbol === state.usSelectedSymbol ? "is-selected" : ""}">
      <td><strong>${escapeHtml(row.symbol || "-")}</strong></td>
      <td>${escapeHtml(row.name || "-")}<div class="table-subtext">${escapeHtml(row.sector || "미분류")}</div></td>
      <td>$${escapeHtml(formatNumber(row.price, 2))}</td>
      <td class="${metricTone(row.change_pct)}">${escapeHtml(formatSignedPercent(row.change_pct, 2))}</td>
      <td class="${metricTone(row.metrics?.return_1m)}">${escapeHtml(formatSignedPercent(row.metrics?.return_1m, 1))}</td>
      <td>${escapeHtml(formatNumber(row.metrics?.rsi14, 1))}</td>
      <td>${escapeHtml(formatUsdCompact(row.market_cap_usd))}</td>
    </tr>
  `).join("") : "<tr><td colspan='7' class='empty-state'>조건에 맞는 미국 종목이 없습니다.</td></tr>";
  renderUsSelected();
}

function renderPriceLineChart(container, history) {
  if (!history.length) {
    container.innerHTML = emptyFeature("이 종목의 차트 이력이 수집되지 않았습니다.");
    return;
  }
  const width = 760;
  const height = 280;
  const pad = 25;
  const closes = history.map((row) => Number(row.close)).filter(Number.isFinite);
  if (!closes.length) {
    container.innerHTML = emptyFeature("유효한 종가 이력이 없습니다.");
    return;
  }
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = Math.max(max - min, 0.01);
  const points = closes.map((value, index) => {
    const x = pad + (index / Math.max(closes.length - 1, 1)) * (width - pad * 2);
    const y = pad + ((max - value) / range) * (height - pad * 2);
    return `${x},${y}`;
  }).join(" ");
  const positive = closes.at(-1) >= closes[0];
  container.innerHTML = `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img">
      <defs><linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${positive ? "#0a7a5f" : "#bf3d3d"}" stop-opacity=".24"/><stop offset="1" stop-color="${positive ? "#0a7a5f" : "#bf3d3d"}" stop-opacity="0"/></linearGradient></defs>
      <polygon points="${pad},${height - pad} ${points} ${width - pad},${height - pad}" fill="url(#priceFill)"></polygon>
      <polyline points="${points}" fill="none" stroke="${positive ? "#0a7a5f" : "#bf3d3d"}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
      <text x="${pad}" y="18" fill="#6e655c" font-size="12">$${escapeHtml(formatNumber(max, 2))}</text>
      <text x="${pad}" y="${height - 6}" fill="#6e655c" font-size="12">$${escapeHtml(formatNumber(min, 2))}</text>
    </svg>
  `;
}

function renderUsSelected() {
  const stock = (state.featureData.usMarket?.stocks || [])
    .find((row) => row.symbol === state.usSelectedSymbol);
  const summary = document.getElementById("us-selected-summary");
  const chart = document.getElementById("us-price-chart");
  const analyst = document.getElementById("us-analyst-summary");
  if (!stock) {
    summary.innerHTML = emptyFeature("종목을 선택하세요.");
    chart.innerHTML = "";
    analyst.innerHTML = "";
    return;
  }
  summary.innerHTML = `
    <div class="stock-detail-title">
      <div><p class="section-kicker">${escapeHtml(stock.symbol || "")}</p><h2>${escapeHtml(stock.name || "-")}</h2><p>${escapeHtml(stock.sector || "미분류")} · ${escapeHtml(stock.industry || "-")}</p></div>
      <div><strong class="${metricTone(stock.change_pct)}">${escapeHtml(formatSignedPercent(stock.change_pct, 2))}</strong><p>$${escapeHtml(formatNumber(stock.price, 2))}</p></div>
    </div>
    <div class="kpi-grid">
      ${kpiCard("1개월", formatSignedPercent(stock.metrics?.return_1m, 1), "수익률")}
      ${kpiCard("RSI 14", formatNumber(stock.metrics?.rsi14, 1), "기술적 강도")}
      ${kpiCard("52주 고가", stock.metrics?.week52_high == null ? "N/A" : `$${formatNumber(stock.metrics.week52_high, 2)}`, "일봉 기준")}
    </div>
  `;
  renderPriceLineChart(chart, stock.history || []);
  renderUsAnalystSummary(analyst, stock.symbol);
}

function renderUsAnalystSummary(container, symbol) {
  const row = state.featureData.finnhub?.stocks?.[symbol];
  if (!row) {
    container.innerHTML = emptyFeature("이 종목의 Finnhub 애널리스트 데이터가 아직 없습니다.");
    return;
  }
  const recommendation = Array.isArray(row.recommendations) ? row.recommendations[0] : null;
  const earnings = Array.isArray(row.earnings_surprises) ? row.earnings_surprises[0] : null;
  const metrics = row.metrics?.metric || {};
  const positive = Number(recommendation?.strongBuy || 0) + Number(recommendation?.buy || 0);
  const neutral = Number(recommendation?.hold || 0);
  const negative = Number(recommendation?.sell || 0) + Number(recommendation?.strongSell || 0);
  container.innerHTML = `
    <div class="analyst-heading">
      <div><p class="section-kicker">Finnhub</p><h3>애널리스트·기업 지표</h3></div>
      <span class="feed-date">${escapeHtml(formatCompactDate(recommendation?.period))}</span>
    </div>
    <div class="analyst-vote-grid">
      <div><span>매수</span><strong class="money-positive">${escapeHtml(formatInteger(positive))}</strong></div>
      <div><span>중립</span><strong>${escapeHtml(formatInteger(neutral))}</strong></div>
      <div><span>매도</span><strong class="money-negative">${escapeHtml(formatInteger(negative))}</strong></div>
    </div>
    <div class="event-metrics analyst-metrics">
      <div class="event-metric"><span>PER TTM</span><strong>${escapeHtml(formatNumber(metrics.peBasicExclExtraTTM, 2))}</strong></div>
      <div class="event-metric"><span>배당수익률</span><strong>${escapeHtml(formatPercent(metrics.dividendYieldIndicatedAnnual, 2))}</strong></div>
      <div class="event-metric"><span>베타</span><strong>${escapeHtml(formatNumber(metrics.beta, 2))}</strong></div>
      <div class="event-metric"><span>최근 EPS 서프라이즈</span><strong class="${metricTone(earnings?.surprisePercent)}">${escapeHtml(formatSignedPercent(earnings?.surprisePercent, 1))}</strong></div>
    </div>
  `;
}

function renderUsShortTable() {
  const query = state.usShortSearch.trim().toLowerCase();
  const head = document.getElementById("us-short-table-head");
  const body = document.getElementById("us-short-table-body");
  if (state.usShortMode === "volume") {
    head.innerHTML = "<tr><th>순위</th><th>티커</th><th>공매도량</th><th>총 거래량</th><th>공매도 비중</th><th>면제 거래량</th></tr>";
    const rows = [...(state.featureData.usShortVolume?.symbols || [])]
      .filter((row) => !query || String(row.symbol || "").toLowerCase().includes(query))
      .sort((a, b) => Number(b.short_volume_ratio || 0) - Number(a.short_volume_ratio || 0))
      .slice(0, 150);
    body.innerHTML = rows.length ? rows.map((row, index) => `
      <tr><td>${index + 1}</td><td><strong>${escapeHtml(row.symbol || "-")}</strong></td>
      <td>${escapeHtml(formatInteger(row.short_volume))}</td><td>${escapeHtml(formatInteger(row.total_volume))}</td>
      <td class="money-negative">${escapeHtml(formatPercent(row.short_volume_ratio, 2))}</td><td>${escapeHtml(formatInteger(row.short_exempt_volume))}</td></tr>
    `).join("") : "<tr><td colspan='6' class='empty-state'>FINRA 일일 공매도 데이터가 없습니다.</td></tr>";
  } else {
    head.innerHTML = "<tr><th>순위</th><th>티커</th><th>회사</th><th>공매도 잔고</th><th>이전 대비</th><th>변화율</th><th>Days to Cover</th></tr>";
    const rows = [...(state.featureData.usShortInterest?.rows || [])]
      .filter((row) => !query || `${row.symbol || row.symbolCode || ""} ${row.issueName || ""}`.toLowerCase().includes(query))
      .sort((a, b) => Number(b.calculated_days_to_cover || b.daysToCoverQuantity || 0) - Number(a.calculated_days_to_cover || a.daysToCoverQuantity || 0))
      .slice(0, 150);
    body.innerHTML = rows.length ? rows.map((row, index) => `
      <tr><td>${index + 1}</td><td><strong>${escapeHtml(row.symbol || row.symbolCode || "-")}</strong></td>
      <td>${escapeHtml(row.issueName || "-")}</td><td>${escapeHtml(formatInteger(row.currentShortPositionQuantity))}</td>
      <td class="${metricTone(row.changePreviousNumber)}">${escapeHtml(formatInteger(row.changePreviousNumber))}</td>
      <td class="${metricTone(row.changePercent)}">${escapeHtml(formatSignedPercent(row.changePercent, 2))}</td>
      <td>${escapeHtml(formatNumber(row.calculated_days_to_cover ?? row.daysToCoverQuantity, 2))}</td></tr>
    `).join("") : "<tr><td colspan='7' class='empty-state'>FINRA 공매도 잔고 데이터가 없습니다.</td></tr>";
  }
}

function renderBriefingInline(value) {
  const codeTokens = [];
  let text = escapeHtml(value || "").replace(/`([^`\n]+)`/g, (_, code) => {
    const token = `@@BRIEFING_CODE_${codeTokens.length}@@`;
    codeTokens.push(`<code>${code}</code>`);
    return token;
  });
  text = text
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_\n]+)__/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\n]+)\*(?=$|[\s).,!?:;])/g, "$1<em>$2</em>");
  return text.replace(
    /@@BRIEFING_CODE_(\d+)@@/g,
    (_, index) => codeTokens[Number(index)] || ""
  );
}

function renderBriefingMarkdown(markdown) {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const output = [];
  let paragraph = [];
  let listType = "";
  let codeLines = [];
  let inCodeBlock = false;

  const flushParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    output.push(`<p>${paragraph.join("<br>")}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (!listType) {
      return;
    }
    output.push(`</${listType}>`);
    listType = "";
  };
  const openList = (type) => {
    flushParagraph();
    if (listType === type) {
      return;
    }
    closeList();
    output.push(`<${type}>`);
    listType = type;
  };

  lines.forEach((rawLine) => {
    const line = rawLine.trimEnd();
    if (/^\s*```/.test(line)) {
      flushParagraph();
      closeList();
      if (inCodeBlock) {
        output.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
      }
      inCodeBlock = !inCodeBlock;
      return;
    }
    if (inCodeBlock) {
      codeLines.push(rawLine);
      return;
    }
    if (!line.trim()) {
      flushParagraph();
      closeList();
      return;
    }

    const heading = line.match(/^\s*(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      closeList();
      const level = Math.min(5, heading[1].length + 2);
      output.push(`<h${level}>${renderBriefingInline(heading[2])}</h${level}>`);
      return;
    }
    if (/^\s*(?:---+|\*\*\*+|___+)\s*$/.test(line)) {
      flushParagraph();
      closeList();
      output.push("<hr>");
      return;
    }

    const unordered = line.match(/^\s*[-+*]\s+(.+)$/);
    if (unordered) {
      openList("ul");
      output.push(`<li>${renderBriefingInline(unordered[1])}</li>`);
      return;
    }
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (ordered) {
      openList("ol");
      output.push(`<li>${renderBriefingInline(ordered[1])}</li>`);
      return;
    }
    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) {
      flushParagraph();
      closeList();
      output.push(`<blockquote>${renderBriefingInline(quote[1])}</blockquote>`);
      return;
    }

    closeList();
    paragraph.push(renderBriefingInline(line.trim()));
  });

  if (inCodeBlock && codeLines.length) {
    output.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
  }
  flushParagraph();
  closeList();
  return output.join("");
}

function renderIntelligenceWorkspace() {
  const news = state.featureData.news || {};
  const briefing = state.featureData.briefing || {};
  const sec = state.featureData.sec || {};
  const finnhub = state.featureData.finnhub || {};
  document.getElementById("intelligence-kpis").innerHTML = [
    kpiCard("뉴스", `${news.count || 0}건`, "NAVER 검색 API"),
    kpiCard("SEC 기업", `${sec.company_count || 0}개`, "주요 공시 추적"),
    kpiCard("Finnhub", `${finnhub.count || 0}개`, "지표·애널리스트"),
    kpiCard("AI 브리핑", briefing.generated_at_utc ? "생성 완료" : "연결 대기", formatCompactDate(briefing.generated_at_utc))
  ].join("");
  document.getElementById("ai-briefing-content").innerHTML =
    briefing.briefing
      ? renderBriefingMarkdown(briefing.briefing)
      : "<p class='briefing-empty'>AI 브리핑 데이터가 아직 없습니다.</p>";
  populateNewsCategories();
  renderNewsFeed();
  populateSecCategories();
  renderSecFeed();
}

function populateNewsCategories() {
  const select = document.getElementById("news-category-select");
  const categories = new Set((state.featureData.news?.items || []).flatMap((row) => row.categories || []));
  const current = state.newsCategory;
  select.innerHTML = `<option value="all">전체</option>${[...categories].sort().map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(newsCategoryLabel(category))}</option>`).join("")}`;
  select.value = categories.has(current) ? current : "all";
  state.newsCategory = select.value;
}

function renderNewsFeed() {
  const query = state.newsSearch.trim().toLowerCase();
  const rows = (state.featureData.news?.items || []).filter((row) => {
    const categoryMatch = state.newsCategory === "all" || (row.categories || []).includes(state.newsCategory);
    const text = `${row.title || ""} ${row.description || ""}`.toLowerCase();
    return categoryMatch && (!query || text.includes(query));
  }).slice(0, 100);
  document.getElementById("news-feed").innerHTML = rows.length ? rows.map((row) => `
    <a class="feed-item source-link" href="${escapeHtml(row.link || "#")}" target="_blank" rel="noopener">
      <span class="status-chip">${escapeHtml((row.categories || [])[0] || "뉴스")}</span>
      <span class="feed-item-main"><strong>${escapeHtml(row.title || "-")}</strong><span>${escapeHtml(row.description || "")}</span></span>
      <span class="feed-date">${escapeHtml(formatCompactDate(row.published_at))}</span>
    </a>
  `).join("") : emptyFeature("조건에 맞는 뉴스가 없습니다.");
}

function populateSecCategories() {
  const select = document.getElementById("sec-category-select");
  const categories = Object.keys(state.featureData.sec?.filings || {});
  const current = state.secCategory;
  select.innerHTML = `<option value="all">전체</option>${categories.map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`).join("")}`;
  select.value = categories.includes(current) ? current : "all";
  state.secCategory = select.value;
}

function renderSecFeed() {
  const groups = state.featureData.sec?.filings || {};
  const rows = state.secCategory === "all"
    ? Object.values(groups).flat()
    : groups[state.secCategory] || [];
  const seen = new Set();
  const query = state.secSearch.trim().toLowerCase();
  const filtered = rows.filter((row) => {
    const key = `${row.accessionNumber || ""}:${row.symbol || ""}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    const text = `${row.symbol || ""} ${row.company || ""} ${row.form || ""} ${row.primaryDocument || ""}`.toLowerCase();
    return !query || text.includes(query);
  }).sort((a, b) => String(b.filingDate || "").localeCompare(String(a.filingDate || ""))).slice(0, 150);
  document.getElementById("sec-filing-feed").innerHTML = filtered.length ? filtered.map((row) => `
    <a class="feed-item source-link" href="${escapeHtml(row.filing_url || "#")}" target="_blank" rel="noopener">
      <span class="status-chip">${escapeHtml(row.form || "SEC")}</span>
      <span class="feed-item-main"><strong>${escapeHtml(row.company || row.symbol || "-")}</strong><span>${escapeHtml(row.symbol || "")} · ${escapeHtml((row.categories || []).join(", "))}</span></span>
      <span class="feed-date">${escapeHtml(formatCompactDate(row.filingDate))}</span>
    </a>
  `).join("") : emptyFeature("SEC 주요 공시 데이터가 아직 없습니다.");
}

function friendlyDataName(path) {
  const names = {
    "data/korea_investor_flow.json": "국내 투자자 수급",
    "data/korea_short_selling.json": "국내 공매도",
    "data/dart_event_details.json": "DART 이벤트 상세",
    "data/dart_insider_trades.json": "DART 임원매수",
    "data/dart_disclosures.json": "DART 최근 공시",
    "data/us_market_snapshot.json": "미국 시장 스냅샷",
    "data/us_finnhub.json": "Finnhub 기업·애널리스트",
    "data/us_sec_filings.json": "SEC 주요 공시",
    "data/us_finra_short_interest.json": "FINRA 공매도 잔고",
    "data/us_finra_short_volume.json": "FINRA 일일 공매도",
    "data/naver_news.json": "NAVER 뉴스",
    "data/ai_market_briefing.json": "AI 시장 브리핑",
    "data/treasury_yields.json": "한·미 국채 금리",
    "data/market_indices.json": "주요 지수·가상자산 차트",
    "data/market_heatmap.json": "한·미 시장 히트맵",
    "data/portfolio.json": "공개 포트폴리오 전술판",
    "data/naver_etf_brands.json": "KoAct·TIME ETF",
    "data/market_sum.json": "국내 종목 시세",
    "data/market_sum_by_roe.json": "국내 가치평가 원본",
    "data/fnguide_roe_history.json": "FnGuide ROE 이력",
    "data/dart_major_holders.json": "DART 주요주주",
    "data/financial_n_estimates.json": "고ROE 지속기간 N 엔진",
    "data/investment_screens.json": "버핏·퀄리티 스크리닝"
  };
  return names[path] || path.replace("data/", "").replace(".json", "");
}

function renderDataWorkspace() {
  const manifest = state.featureData.manifest || {};
  const files = manifest.files || [];
  const totalBytes = files.reduce((sum, row) => sum + (Number(row.bytes) || 0), 0);
  const healthy = files.filter((row) => !row.error && Number(row.bytes) > 2).length;
  document.getElementById("data-trust-kpis").innerHTML = [
    kpiCard("수집 파일", `${files.length}개`, "manifest 기준"),
    kpiCard("정상 파일", `${healthy}개`, healthy === files.length ? "모두 읽기 가능" : "일부 확인 필요"),
    kpiCard("총 용량", `${formatNumber(totalBytes / 1024 / 1024, 1)}MB`, "JSON 합계"),
    kpiCard("상태 기준", formatCompactDate(manifest.generated_at_utc), "브라우저 로드 기준")
  ].join("");
  const expected = [
    "data/market_sum.json",
    "data/market_sum_by_roe.json",
    "data/fnguide_roe_history.json",
    "data/dart_major_holders.json",
    "data/financial_n_estimates.json",
    "data/investment_screens.json",
    "data/treasury_yields.json",
    "data/market_indices.json",
    "data/market_heatmap.json",
    "data/portfolio.json",
    "data/naver_etf_brands.json",
    "data/korea_investor_flow.json",
    "data/korea_short_selling.json",
    "data/dart_disclosures.json",
    "data/dart_event_details.json",
    "data/dart_insider_trades.json",
    "data/us_market_snapshot.json",
    "data/us_finnhub.json",
    "data/us_sec_filings.json",
    "data/us_finra_short_interest.json",
    "data/us_finra_short_volume.json",
    "data/naver_news.json",
    "data/ai_market_briefing.json"
  ];
  const known = new Set(files.map((row) => row.file));
  const rows = [
    ...files,
    ...expected.filter((path) => !known.has(path)).map((file) => ({ file, missing: true }))
  ];
  const container = document.getElementById("data-status-grid");
  container.innerHTML = rows.length ? rows.map((row) => {
    const ok = !row.missing && !row.error && Number(row.bytes) > 2;
    const source = Array.isArray(row.source) ? row.source.join(" + ") : row.source;
    return `
      <article class="data-status-card">
        <div class="data-status-head">
          <h3>${escapeHtml(friendlyDataName(row.file || "-"))}</h3>
          <span class="status-chip ${ok ? "is-positive" : "is-warning"}">${ok ? "정상" : "대기"}</span>
        </div>
        <dl>
          <dt>파일</dt><dd>${escapeHtml(row.file || "-")}</dd>
          <dt>기준일</dt><dd>${escapeHtml(formatCompactDate(row.data_date))}</dd>
          <dt>건수</dt><dd>${escapeHtml(row.count == null ? "-" : formatInteger(row.count))}</dd>
          <dt>크기</dt><dd>${row.bytes ? `${formatNumber(row.bytes / 1024, 1)}KB` : "-"}</dd>
          <dt>출처</dt><dd title="${escapeHtml(source || "")}">${escapeHtml(source || "-")}</dd>
        </dl>
      </article>
    `;
  }).join("") : emptyFeature("데이터 manifest가 아직 없습니다.");
}

function bindFeatureControls() {
  document.querySelectorAll("[data-workspace]").forEach((button) => {
    button.addEventListener("click", () => switchWorkspace(button.dataset.workspace));
  });

  const bindings = [
    ["flow-market-select", "change", (event) => { state.flowMarket = event.target.value; state.shortMarket = state.flowMarket; document.getElementById("short-market-select").value = state.shortMarket; renderFlowSummary(); renderFlowTickerTable(); renderKoreaShortTable(); }],
    ["flow-investor-select", "change", (event) => { state.flowInvestor = event.target.value; renderFlowTickerTable(); }],
    ["flow-direction-select", "change", (event) => { state.flowDirection = event.target.value; renderFlowTickerTable(); }],
    ["flow-search-input", "input", (event) => { state.flowSearch = event.target.value; renderFlowTickerTable(); }],
    ["short-market-select", "change", (event) => { state.shortMarket = event.target.value; renderKoreaShortTable(); }],
    ["short-mode-select", "change", (event) => { state.shortMode = event.target.value; renderKoreaShortTable(); }],
    ["short-search-input", "input", (event) => { state.shortSearch = event.target.value; renderKoreaShortTable(); }],
    ["event-type-select", "change", (event) => { state.eventType = event.target.value; renderEventCards(); }],
    ["event-sort-select", "change", (event) => { state.eventSort = event.target.value; renderEventCards(); }],
    ["event-search-input", "input", (event) => { state.eventSearch = event.target.value; renderEventCards(); }],
    ["insider-mode-select", "change", (event) => { state.insiderMode = event.target.value; renderInsiderTable(); }],
    ["insider-search-input", "input", (event) => { state.insiderSearch = event.target.value; renderInsiderTable(); }],
    ["filing-category-select", "change", (event) => { state.filingCategory = event.target.value; renderFilingFeed(); }],
    ["filing-search-input", "input", (event) => { state.filingSearch = event.target.value; renderFilingFeed(); }],
    ["us-stock-sort-select", "change", (event) => { state.usStockSort = event.target.value; renderUsStockTable(); }],
    ["us-stock-search-input", "input", (event) => { state.usStockSearch = event.target.value; renderUsStockTable(); }],
    ["us-short-mode-select", "change", (event) => { state.usShortMode = event.target.value; renderUsShortTable(); }],
    ["us-short-search-input", "input", (event) => { state.usShortSearch = event.target.value; renderUsShortTable(); }],
    ["news-category-select", "change", (event) => { state.newsCategory = event.target.value; renderNewsFeed(); }],
    ["news-search-input", "input", (event) => { state.newsSearch = event.target.value; renderNewsFeed(); }],
    ["sec-category-select", "change", (event) => { state.secCategory = event.target.value; renderSecFeed(); }],
    ["sec-search-input", "input", (event) => { state.secSearch = event.target.value; renderSecFeed(); }]
  ];
  bindings.forEach(([id, eventName, handler]) => {
    document.getElementById(id)?.addEventListener(eventName, handler);
  });

  document.getElementById("refresh-data-status")?.addEventListener("click", () => {
    state.loadedWorkspaces.delete("data");
    loadWorkspaceData("data", true);
  });

  document.addEventListener("click", (event) => {
    const usRow = event.target.closest("[data-us-symbol]");
    if (usRow) {
      state.usSelectedSymbol = usRow.dataset.usSymbol;
      renderUsStockTable();
      return;
    }
    const koreaRow = event.target.closest("[data-select-korea-code]");
    if (koreaRow) {
      const code = koreaRow.dataset.selectKoreaCode;
      if (state.rawStocks.some((row) => row.code === code)) {
        state.selectedCode = code;
        switchWorkspace("valuation");
        renderDashboard();
        document.getElementById("selected-stock-workbench")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  });
}

function syncResponsiveTableLabels(table) {
  const headers = Array.from(table.querySelectorAll("thead th")).map(
    (header) => header.textContent.trim()
  );
  const hasSortableColumns = table.querySelector(
    "th[data-sort-key], th[data-priority-sort-key]"
  );
  table.classList.toggle("has-mobile-sort", Boolean(hasSortableColumns));

  table.querySelectorAll("tbody tr").forEach((row) => {
    Array.from(row.cells).forEach((cell, index) => {
      const label = headers[index];
      if (label) {
        cell.dataset.label = label;
      } else {
        cell.removeAttribute("data-label");
      }
    });
  });
}

function initResponsiveTables() {
  const root = document.querySelector(".dashboard-layout");
  if (!root) {
    return;
  }

  let syncFrame = null;
  const syncAll = () => {
    syncFrame = null;
    root.querySelectorAll(".table-wrap table").forEach(syncResponsiveTableLabels);
  };
  const scheduleSync = () => {
    if (syncFrame === null) {
      syncFrame = requestAnimationFrame(syncAll);
    }
  };

  syncAll();
  new MutationObserver(scheduleSync).observe(root, {
    childList: true,
    subtree: true
  });
}

bindFeatureControls();
bindMarketOverview();
bindTodayNews();
bindMarketMap();
bindPortfolioBoard();
bindScreenPendingModal();
initResponsiveTables();
const initialWorkspace = location.hash.replace("#", "");
if (["priority", "valuation", "korea", "disclosures", "us", "intelligence", "data"].includes(initialWorkspace)) {
  switchWorkspace(initialWorkspace, false);
}
loadTreasuryTicker();
loadEtfBrandTickers();
loadMarketOverview();
loadTodayNews();
loadMarketMap();
loadPortfolio();
loadStocks();
