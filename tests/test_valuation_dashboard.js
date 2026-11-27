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
vm.runInContext(script + "\nglobalThis.api = { applyValuationMetrics, requiredValuationPeriod, inferRoeRange, getFilteredStocks, state, enrichStock, renderTable, renderFairValuePanel, renderKellyPanel };", context);
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
api.renderKellyPanel(api.enrichStock(hyosung));
assert.match(elements.get("fair-value-panel").innerHTML, /산출 제외/);
assert.match(elements.get("kelly-panel").innerHTML, /산출 제외/);
console.log(`Valuation dashboard passed: ${filtered.length} ranked stocks; Hyosung excluded.`);
