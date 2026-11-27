const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

// Load the actual dashboard functions while leaving browser event binding to
// the browser. Fix the clock so archived reporting-period tests are repeatable.
class SnapshotDate extends Date {
  constructor(...args) { super(...(args.length ? args : ["2026-11-28T00:00:00Z"])); }
}
const context = { console, Intl, Date: SnapshotDate };
vm.createContext(context);
const script = fs.readFileSync("script.js", "utf8").split("\nbindFeatureControls();")[0];
vm.runInContext(script + "\nglobalThis.api = { applyValuationMetrics, requiredValuationPeriod, inferRoeRange, getFilteredStocks, state, enrichStock, renderTable, renderFairValuePanel, renderPositionRiskPanel, loadStocks };", context);
const api = context.api;

for (const [stamp, expected] of [
  ["2026-01-01", "2025-09-30"], ["2026-04-15", "2025-12-31"],
  ["2026-05-15", "2026-03-31"], ["2026-11-28", "2026-09-30"]
]) {
  assert.equal(api.requiredValuationPeriod(new Date(`${stamp}T00:00:00Z`)), expected);
}
const payload = JSON.parse(fs.readFileSync("data/valuation_metrics.json", "utf8"));
const market = JSON.parse(fs.readFileSync("data/market_sum.json", "utf8"));
api.state.rawStocks = market.stocks.map(stock => api.applyValuationMetrics(stock, payload));
const hyosung = api.state.rawStocks.find(stock => stock.code === "298000");
assert.equal(hyosung.valuationEligible, false);
assert.ok(hyosung.roe < 0);
assert.equal(api.enrichStock(hyosung).fairPriceBase, null);
assert.equal(api.applyValuationMetrics({ code: "298000", roe: 260.94 }, null).valuationEligible, false);
const stale = api.applyValuationMetrics({ code: "000001", roe: 500 }, { metrics: {
  "000001": { eligible: true, roe_pct: 500, period_end: "2025-12-31" }
}});
assert.equal(stale.valuationEligible, false);
assert.ok(stale.valuationMetrics.quality_reasons.includes("stale_report"));
const filtered = api.getFilteredStocks();
assert.ok(filtered.length > 0);
assert.ok(!filtered.some(stock => stock.code === "298000"));
assert.ok(filtered.every(stock => stock.valuationEligible));

const elements = new Map();
context.document = { getElementById(id) {
  if (!elements.has(id)) elements.set(id, { innerHTML: "", textContent: "", querySelectorAll: () => [] });
  return elements.get(id);
}, querySelectorAll: () => [] };
api.renderTable(filtered.slice(0, 3), filtered);
const html = elements.get("roe-table-body").innerHTML;
assert.match(html, /2025-10-01~2026-09-30 TTM/);
assert.doesNotMatch(html, /효성화학/);
assert.match(elements.get("valuation-exclusion-details").innerHTML, /최근 자본잠식/);
api.renderFairValuePanel(api.enrichStock(hyosung));
api.renderPositionRiskPanel(api.enrichStock(hyosung));
assert.match(elements.get("fair-value-panel").innerHTML, /산출 제외/);
assert.match(elements.get("position-risk-panel").innerHTML, /산출 제외/);
console.log(`Valuation dashboard passed: ${filtered.length} ranked stocks; Hyosung excluded.`);

// A low vendor ROE must not prevent a stock with verified DART returns from
// entering the table. Daily price changes affect multiples, not reported ROE.
const dailyQuote = { code: "000001", name: "전 종목 검증", roe: 1, current_price: 200,
  eps: 999, sales_increasing_rate: 999, reserve_ratio: 99999, property_total_krw_100m: 999 };
const dartMetrics = { metrics: { "000001": { eligible: true, roe_pct: 15, roa_pct: 12,
  bps: 100, eps: 10, period_end: "2026-09-30", financials: { assets: 5e9, liabilities: 2e9,
  revenue_yoy_pct: 20, operating_income_yoy_pct: -5 } } } };
const dartStock = api.applyValuationMetrics(dailyQuote, dartMetrics);
assert.equal(dartStock.roe, 15);
assert.equal(dartStock.pbr, 2);
assert.equal(dartStock.per, 20);
assert.equal(dartStock.eps, 10);
assert.equal(dartStock.property_total_krw_100m, 50);
assert.equal(dartStock.sales_increasing_rate, 20);
assert.equal(dartStock.reserve_ratio, null);
assert.equal(api.getFilteredStocks([api.enrichStock(dartStock)]).length, 1);
const repriced = api.applyValuationMetrics({ ...dailyQuote, current_price: 400 }, dartMetrics);
assert.equal(repriced.pbr, 4);
assert.equal(repriced.per, 40);
assert.equal(repriced.roe, 15);
const noQuote = api.applyValuationMetrics({ ...dailyQuote, current_price: null }, dartMetrics);
assert.equal(noQuote.pbr, null);
assert.equal(noQuote.per, null);
api.state.financialNByCode.set("000001", { estimate: { base_years: 7, conservative_years: 5, optimistic_years: 9 } });
const preferred = api.applyValuationMetrics({ ...dailyQuote, code: "000005" }, { metrics: {
  "000005": { ...dartMetrics.metrics["000001"], financial_ticker: "000001" }
} });
assert.equal(api.enrichStock(preferred).estimatedNBase, 7);
assert.equal(api.enrichStock(preferred).nModel.engine, "empirical_persistence");

api.state.financialNByCode.clear();

(async () => {
  const requested = [];
  context.fetch = async (url, options) => {
    requested.push({ url, options });
    const payload = url.startsWith("./data/market_sum.json")
      ? { stocks: [dailyQuote], crawled_at_utc: "2026-11-28T00:00:00Z" }
      : url.startsWith("./data/valuation_metrics.json") ? dartMetrics : {};
    return { ok: true, json: async () => payload };
  };
  for (const name of ["updateLastUpdated", "bindControls", "bindPrioritySortHeaders",
    "bindTableSortHeaders", "renderDashboard", "renderPortfolioBoard"]) context[name] = () => {};
  await api.loadStocks();
  assert.equal(api.state.rawStocks.length, 1);
  assert.equal(api.state.rawStocks[0].roe, 15);
  assert.ok(requested.some(({ url, options }) => url.startsWith("./data/market_sum.json?") && options.cache === "no-store"));
  assert.ok(!requested.some(({ url }) => /market_sum_by_roe|fnguide/.test(url)));
  console.log("DART financials and full-market daily quote loading passed.");
})().catch(error => { console.error(error); process.exitCode = 1; });
