const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const stored = new Map();
const context = { console, Intl, localStorage: {
  getItem: key => stored.get(key) ?? null,
  setItem: (key, value) => stored.set(key, value)
} };
vm.createContext(context);
vm.runInContext(fs.readFileSync("script.js", "utf8").split("\nbindFeatureControls();")[0]
  + "\nglobalThis.api = { state, enrichStock, saveValuationScenarios, loadValuationScenarios, renderFairValuePanel, renderTable, portfolioScenarioReturn };", context);
const a = context.api;
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} != ${expected}`);
const quote = { code: "000001", name: "시나리오 검증", pbr: 1.5, roe: 16, current_price: 15000,
  valuationEligible: true, valuationMetrics: { bps: 10000, period_end: "2026-09-30",
    clean_roe_history: [{ roe: 12 }, { roe: 20 }] } };
a.state.rawStocks = [quote];
a.state.financialNByCode.set(quote.code, { estimate: { conservative_years: 3, base_years: 6, optimistic_years: 10 } });
const automatic = a.enrichStock(quote);
assert.equal(automatic.scenarioMode, "automatic");
close(automatic.fairPriceBase, 10000 * (1.16 / 1.1) ** 6);

const assumptions = {
  conservative: { assumedRoe: "12", durationYears: "3", rationale: "경쟁 심화", reviewTrigger: "고객 이탈" },
  base: { assumedRoe: "16", durationYears: "6", rationale: "계약 및 재투자 기회", reviewTrigger: "신규 계약 감소" },
  optimistic: { assumedRoe: "20", durationYears: "10", rationale: "경쟁 우위 확대", reviewTrigger: "경쟁사 진입" }
};
assert.equal(a.saveValuationScenarios(quote.code, assumptions).persisted, true);
const manual = a.enrichStock(quote);
assert.equal(manual.scenarioMode, "manual");
close(manual.fairPriceLow, 10555.432006010522);
close(manual.fairPriceBase, 13752.822075085187);
close(manual.fairPriceHigh, 23871.824275727347);
close(manual.gapRateLow, (manual.fairPriceLow / 15000 - 1) * 100);
close(manual.gapRateHigh, (manual.fairPriceHigh / 15000 - 1) * 100);
assert.equal(a.loadValuationScenarios().get(quote.code).base.rationale, "계약 및 재투자 기회");
close(a.portfolioScenarioReturn(manual, "base", 3), ((manual.fairPriceBase / 15000) ** (1 / 3) - 1) * 100);

// Saved ROE and N are absolute assumptions, independent of automatic offsets
// and market-implied N. The common required return still changes valuation.
a.state.roeAdjustment = 5;
a.state.durationOffset = 3;
close(a.enrichStock(quote).fairPriceBase, manual.fairPriceBase);
a.state.discountRate = 12;
close(a.enrichStock(quote).fairPriceBase, 10000 * (1.16 / 1.12) ** 6);
close(a.enrichStock(quote).expectedReturnBase, manual.expectedReturnBase);
a.state.discountRate = 10;
const belowBook = a.enrichStock({ ...quote, pbr: 0.8, current_price: 8000 });
assert.equal(belowBook.marketImpliedN, 1);
assert.equal(belowBook.scenarios.base.params.durationYears, 6);
close(belowBook.fairPriceBase, manual.fairPriceBase);
assert.equal(a.enrichStock({ ...quote, valuationEligible: false }).fairPriceBase, null);
assert.equal(a.enrichStock({ ...quote, code: "000002" }).scenarioMode, "automatic");
assert.equal(a.saveValuationScenarios("00088K", assumptions).ok, true);
assert.equal(a.loadValuationScenarios().get("00088K").base.durationYears, 6);

// Bounds must include all three values, even if names and economic outcomes
// disagree. Negative ROE is a supported stress assumption, not clamped to 1%.
const inverted = {
  conservative: { assumedRoe: 5, durationYears: 1 },
  base: { assumedRoe: -10, durationYears: 7 },
  optimistic: { assumedRoe: 5, durationYears: 20 }
};
assert.equal(a.saveValuationScenarios(quote.code, inverted).ok, true);
const stress = a.enrichStock(quote);
assert.equal(stress.scenarios.base.params.assumedRoe, -10);
close(stress.fairPriceLow, Math.min(stress.fairPriceBase, stress.fairPriceConservative, stress.fairPriceOptimistic));
close(stress.gapRateHigh, Math.max(stress.gapRateBase, stress.gapRateConservative, stress.gapRateOptimistic));
assert.equal(stress.fairPriceLow, stress.fairPriceBase);

for (const [field, bad] of [["assumedRoe", ""], ["assumedRoe", -100], ["assumedRoe", 101],
  ["assumedRoe", [12]], ["durationYears", 0], ["durationYears", 31], ["durationYears", "Infinity"]]) {
  assert.equal(a.saveValuationScenarios(quote.code, { ...assumptions, base: { ...assumptions.base, [field]: bad } }).ok, false);
  assert.equal(a.enrichStock(quote).fairPriceBase, stress.fairPriceBase);
}
assert.equal(a.saveValuationScenarios("invalid", assumptions).ok, false);
assert.equal(a.saveValuationScenarios(quote.code, {}).ok, false);

// Exercise the actual form submit/reset handlers and rendered source labels.
const elements = new Map();
context.document = { getElementById(id) {
  if (!elements.has(id)) elements.set(id, { innerHTML: "", textContent: "", values: new Map(),
    addEventListener(name, callback) { this[name] = callback; }, querySelectorAll: () => [] });
  return elements.get(id);
}, querySelectorAll: () => [] };
context.FormData = class { constructor(form) { this.values = form.values; } get(key) { return this.values.get(key); } };
let renders = 0;
context.renderDashboard = () => { renders++; a.renderFairValuePanel(a.enrichStock(quote)); };
context.renderPortfolioBoard = () => {};
a.renderFairValuePanel(stress);
assert.match(elements.get("fair-value-panel").innerHTML, /가치가 보수 ≤ 기준 ≤ 낙관 순서가 아닙니다/);
assert.match(elements.get("fair-value-panel").innerHTML, /판단 근거나 가정 변경 조건이 비어/);
const form = elements.get("valuation-scenario-form");
for (const [scenario, inputs] of Object.entries(assumptions)) {
  for (const [field, value] of Object.entries(inputs)) form.values.set(`${scenario}-${field}`, value);
}
form.input();
assert.match(elements.get("valuation-scenario-feedback").textContent, /수정 중/);
form.submit({ preventDefault() {} });
assert.equal(renders, 1);
assert.match(elements.get("valuation-scenario-feedback").textContent, /저장했습니다/);
close(a.enrichStock(quote).fairPriceBase, manual.fairPriceBase);
a.renderTable([a.enrichStock(quote)], [a.enrichStock(quote)]);
assert.match(elements.get("roe-table-body").innerHTML, /직접 설정/);
assert.match(elements.get("roe-table-body").innerHTML, /-29\.6% ~ 59\.1%/);
form.values.set("base-durationYears", "");
form.submit({ preventDefault() {} });
assert.equal(renders, 1);
assert.match(elements.get("valuation-scenario-feedback").textContent, /기존 계산은 유지/);

// Escape notes when returning to the form; stored inputs never become markup.
a.saveValuationScenarios(quote.code, { ...assumptions, base: { ...assumptions.base, rationale: '</textarea><img src=x onerror="alert(1)">' } });
a.renderFairValuePanel(a.enrichStock(quote));
assert.doesNotMatch(elements.get("fair-value-panel").innerHTML, /<img src=x/);
assert.match(elements.get("fair-value-panel").innerHTML, /&lt;\/textarea&gt;/);
elements.get("valuation-scenario-reset").click();
assert.equal(a.enrichStock(quote).scenarioMode, "automatic");
assert.equal(a.loadValuationScenarios().has(quote.code), false);
assert.equal(a.loadValuationScenarios().has("00088K"), true);
assert.match(elements.get("fair-value-panel").innerHTML, /자동 초깃값 · 미검토/);

context.localStorage.setItem = () => { throw new Error("storage disabled"); };
assert.equal(a.saveValuationScenarios(quote.code, assumptions).persisted, false);
assert.equal(a.enrichStock(quote).scenarioMode, "manual");
context.localStorage.getItem = () => "not-json";
assert.equal(a.loadValuationScenarios().size, 0);
context.localStorage.getItem = () => JSON.stringify({ [quote.code]: { ...assumptions, base: { durationYears: 5 } } });
assert.equal(a.loadValuationScenarios().size, 0);
console.log("Scenario formulas, actual bounds, common return, market N independence, validation, form events and per-stock storage passed.");
