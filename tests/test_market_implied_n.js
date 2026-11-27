const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

class SnapshotDate extends Date {
  constructor(...args) { super(...(args.length ? args : ["2026-11-28T00:00:00Z"])); }
}
const context = { console, Intl, Date: SnapshotDate };
vm.createContext(context);
const script = fs.readFileSync(process.argv[2] || "script.js", "utf8").split("\nbindFeatureControls();")[0];
vm.runInContext(script + "\nglobalThis.api = { marketImpliedN, marketImpliedDurationResult, applyValuationMetrics, state, enrichStock, renderTable, renderDurationPanel, renderFairValuePanel };", context);
const api = context.api;

// Below-book N is an explicitly labeled comparison convention, including
// low-ROE and near-required-return cases where a raw inverse has other meanings.
for (const pbr of [0.2, 0.8, 0.999999]) {
  for (const roe of [5, 10, 11, 15, 25]) {
    const result = api.marketImpliedDurationResult(roe, pbr);
    assert.equal(result.years, 1);
    assert.equal(result.status, "fixed_below_book");
  }
}
assert.equal(api.marketImpliedN(15, 1), 0);
assert.equal(api.marketImpliedN(5, 1), 0);
assert.equal(api.marketImpliedN(10, 1), null);
assert.equal(api.marketImpliedN(11, 2), null);
assert.equal(api.marketImpliedN(5, 2), null);
assert.equal(api.marketImpliedDurationResult(5, 2).status, "incompatible_assumptions");
for (const [roe, pbr, discount] of [[15, 0, 10], [15, -1, 10], [null, 0.8, 10], [15, 0.8, -100]]) {
  assert.equal(api.marketImpliedN(roe, pbr, discount), null);
}
const impliedYears = api.marketImpliedN(20, 2);
assert.ok(Math.abs(impliedYears - 7.9661672363) < 1e-9);
assert.ok(Math.abs((1.2 / 1.1) ** impliedYears - 2) < 1e-12);

const elements = new Map();
context.document = { getElementById(id) {
  if (!elements.has(id)) elements.set(id, { innerHTML: "", textContent: "", querySelectorAll: () => [] });
  return elements.get(id);
}, querySelectorAll: () => [] };
const dailyQuote = { code: "000001", name: "N 검증", current_price: 200 };
const dartMetrics = { metrics: { "000001": { eligible: true, roe_pct: 15, roa_pct: 12,
  bps: 100, eps: 10, period_end: "2026-09-30" } } };
const dartStock = api.applyValuationMetrics(dailyQuote, dartMetrics);
api.state.rawStocks = [dartStock];
api.state.financialNByCode.set("000001", { estimate: { base_years: 7, conservative_years: 5, optimistic_years: 9 } });

// The one-year market marker never replaces the seven-year company estimate
// used for fair price and long-term return; the fixed market marker is separate.
const belowBook = api.enrichStock(api.applyValuationMetrics({ ...dailyQuote, current_price: 80 }, dartMetrics));
const aboveBook = api.enrichStock(dartStock);
assert.equal(belowBook.marketImpliedN, 1);
assert.equal(belowBook.marketImpliedDuration.status, "fixed_below_book");
assert.equal(belowBook.estimatedNBase, 7);
const expectedFairPrice = 100 * (1.15 / 1.10) ** 7;
assert.ok(Math.abs(belowBook.fairPriceBase - expectedFairPrice) < 1e-9);
assert.equal(belowBook.fairPriceBase, aboveBook.fairPriceBase);
assert.ok(Math.abs(belowBook.expectedReturnBase - ((1.15 / (0.8 ** (1 / 7))) - 1) * 100) < 1e-9);
api.renderTable([belowBook], [belowBook]);
api.renderDurationPanel(belowBook);
api.renderFairValuePanel(belowBook);
for (const id of ["roe-table-body", "duration-panel", "fair-value-panel"]) {
  assert.match(elements.get(id).innerHTML, /1년 고정/);
  assert.match(elements.get(id).innerHTML, /PBR 1배 미만 · 비교용 가정/);
}
const incompatible = api.enrichStock({ ...dartStock, roe: 5 });
api.renderDurationPanel(incompatible);
assert.match(elements.get("duration-panel").innerHTML, /역산 불가/);
assert.equal(api.enrichStock({ ...belowBook, valuationEligible: false }).marketImpliedN, null);
for (const stock of api.state.rawStocks.filter(stock => stock.valuationEligible)) {
  const n = api.enrichStock(stock).marketImpliedN;
  assert.ok(n === null || n >= 0, `Negative market N for ${stock.code}`);
}
console.log("Below-book N badges, inverse boundaries, and independent fair-price/long-term-return calculations passed.");
