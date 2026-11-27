const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const saved = new Map();
const context = { console, Intl, localStorage: {
  getItem: key => saved.get(key) ?? null,
  setItem: (key, value) => saved.set(key, value)
} };
vm.createContext(context);
vm.runInContext(fs.readFileSync("script.js", "utf8").split("\nbindFeatureControls();")[0]
  + "\nglobalThis.api = { state, estimateLongTermReturn, calculatePositionRisk, calculateBinaryKelly, loadPositionRiskInputs, savePositionRiskInput, enrichStock, renderPositionRiskPanel };", context);
const a = context.api;
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} != ${expected}`);
const quote = { code: "000001", name: "수익률 검증", pbr: 2, roe: 20, current_price: 200,
  valuationEligible: true, valuationMetrics: { bps: 100, period_end: "2026-09-30" } };
a.state.financialNByCode.set(quote.code, { estimate: { conservative_years: 8, base_years: 10, optimistic_years: 12 } });
close(a.estimateLongTermReturn(quote, { assumedRoe: 20, durationYears: 10 }), 11.96395898441689);
assert.equal(a.estimateLongTermReturn({ ...quote, valuationEligible: false }, { assumedRoe: 20, durationYears: 10 }), null);
assert.equal(a.estimateLongTermReturn(quote, { assumedRoe: 20, durationYears: 0 }), null);
const stock = a.enrichStock(quote);
a.state.discountRate = 15;
close(a.enrichStock(quote).expectedReturnBase, stock.expectedReturnBase);
a.state.discountRate = 10;
const belowBook = a.enrichStock({ ...quote, pbr: 0.8, current_price: 80 });
assert.equal(belowBook.marketImpliedN, 1);
close(belowBook.expectedReturnBase, (1.2 / (0.8 ** 0.1) - 1) * 100);
assert.ok(belowBook.expectedReturnLow <= belowBook.expectedReturnHigh);
assert.equal("kellyRatioBase" in belowBook, false);

const risk = a.calculatePositionRisk({ failureLossPct: "50", lossBudgetPct: "1", positionWeightPct: "5" });
close(risk.maxWeightPct, 2);
close(risk.portfolioLossPct, 2.5);
assert.equal(risk.budgetExceeded, true);
assert.equal(a.calculatePositionRisk({}).maxWeightPct, null);
assert.equal(a.calculatePositionRisk({ failureLossPct: 50, lossBudgetPct: "" }).maxWeightPct, null);
assert.equal(a.calculatePositionRisk({ failureLossPct: 0, lossBudgetPct: 1 }).maxWeightPct, null);
assert.equal(a.calculatePositionRisk({ failureLossPct: 101, lossBudgetPct: 1 }).maxWeightPct, null);
assert.equal(a.calculatePositionRisk({ failureLossPct: 50, lossBudgetPct: -1 }).maxWeightPct, null);
close(a.calculatePositionRisk({ failureLossPct: 100, lossBudgetPct: 0, positionWeightPct: 0 }).maxWeightPct, 0);
close(a.calculatePositionRisk({ failureLossPct: 1, lossBudgetPct: 5 }).maxWeightPct, 100);

const bet = { horizonYears: 3, upsidePct: 30, failureLossPct: 25, winProbabilityPct: 50 };
const k = a.calculateBinaryKelly(bet);
close(k.fullWeightPct, 100 / 3);
close(k.halfWeightPct, 50 / 3);
close(k.quarterWeightPct, 25 / 3);
const growth = f => 0.5 * Math.log1p(f * 0.30) + 0.5 * Math.log1p(-f * 0.25);
assert.ok(growth(k.fullWeightPct / 100) > growth(0.2));
assert.ok(growth(k.fullWeightPct / 100) > growth(0.5));
for (const missing of ["horizonYears", "upsidePct", "failureLossPct", "winProbabilityPct"]) {
  assert.equal(a.calculateBinaryKelly({ ...bet, [missing]: "" }), null);
}
assert.equal(a.calculateBinaryKelly({ ...bet, winProbabilityPct: 100 }), null);
assert.equal(a.calculateBinaryKelly({ ...bet, horizonYears: 0 }), null);
assert.equal(a.calculateBinaryKelly({ ...bet, failureLossPct: 101 }), null);
close(a.calculateBinaryKelly({ ...bet, winProbabilityPct: 10 }).fullWeightPct, 0);
const capped = a.calculateBinaryKelly({ ...bet, upsidePct: 10, failureLossPct: 10, winProbabilityPct: 60 });
close(capped.fullWeightPct, 100);
close(capped.halfWeightPct, 100);
close(capped.quarterWeightPct, 50);
assert.equal(capped.capped, true);

// Exercise actual input handlers: keep the form/focus in place while results update.
const elements = new Map();
const makeElement = () => ({ _html: "", fields: [],
  get innerHTML() { return this._html; },
  set innerHTML(html) {
    this._html = html;
    this.fields = [...html.matchAll(/data-position-risk-field="([^"]+)"[^>]*value="([^"]*)"/g)].map(match => ({
      dataset: { positionRiskField: match[1] }, value: match[2],
      addEventListener(name, callback) { this[name] = callback; }
    }));
  },
  querySelectorAll() { return this.fields; }
});
context.document = { getElementById(id) {
  if (!elements.has(id)) elements.set(id, makeElement());
  return elements.get(id);
} };
a.renderPositionRiskPanel(stock);
const panel = elements.get("position-risk-panel");
assert.equal(panel.fields.length, 6);
assert.ok(panel.fields.every(field => field.value === ""));
assert.doesNotMatch(elements.get("kelly-reference-results").innerHTML, /풀 켈리 참고/);
const formBefore = panel.innerHTML;
function enter(field, value) {
  const element = panel.fields.find(input => input.dataset.positionRiskField === field);
  element.value = value;
  element.input();
}
enter("failureLossPct", "50"); enter("lossBudgetPct", "1"); enter("positionWeightPct", "5");
assert.equal(panel.innerHTML, formBefore);
assert.match(elements.get("position-risk-results").innerHTML, /2\.0%/);
assert.match(elements.get("position-risk-results").innerHTML, /초과/);
assert.doesNotMatch(elements.get("kelly-reference-results").innerHTML, /풀 켈리 참고/);
enter("horizonYears", "3"); enter("upsidePct", "30"); enter("winProbabilityPct", "50");
assert.match(elements.get("kelly-reference-results").innerHTML, /풀 켈리 참고/);
assert.equal(a.loadPositionRiskInputs().get(quote.code).positionWeightPct, "5");
a.savePositionRiskInput("00088K", "failureLossPct", "40");
assert.equal(a.loadPositionRiskInputs().get("00088K").failureLossPct, "40");
a.renderPositionRiskPanel({ ...stock, code: "000002" });
assert.ok(panel.fields.every(field => field.value === ""));
a.renderPositionRiskPanel(stock);
assert.equal(panel.fields.find(field => field.dataset.positionRiskField === "failureLossPct").value, "50");
context.localStorage.setItem = () => { throw new Error("storage disabled"); };
a.savePositionRiskInput(quote.code, "positionWeightPct", "6");
assert.equal(a.state.positionRiskByCode.get(quote.code).positionWeightPct, "6");
context.localStorage.getItem = () => "not-json";
assert.equal(a.loadPositionRiskInputs().size, 0);
a.renderPositionRiskPanel({ ...stock, valuationEligible: false });
assert.match(panel.innerHTML, /산출 제외/);
console.log("Long-term returns, loss budgets, conditional Kelly, input events and stock-specific storage passed.");
