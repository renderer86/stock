"""Reproduce the before/after audit against the saved repair baseline."""
from collections import Counter
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from build_valuation_metrics import RawReports
from dart_financial_storage import load_financial_panel


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    output = Path(__file__).resolve().parent
    before = read(output / "before.json")
    after = read(ROOT / "data/valuation_metrics.json")
    quotes = {s["code"]: s for s in read(ROOT / "data/market_sum.json")["stocks"]}
    panel = load_financial_panel(ROOT / "data/dart_financial_panel.json")
    annual_rows = {r["ticker"]: r for r in panel["observations"] if r["fiscal_year"] == 2025}
    interim = read(ROOT / "data/dart_financial_interim.json")["companies"]
    store = RawReports(ROOT / "data")
    annual, prior, current = [store.bulk(y, c) for y, c in
                              [(2025, "11011"), (2025, "11014"), (2026, "11014")]]
    restored, lost, residual = [], [], []
    resolved, patterns = Counter(), Counter()
    checked = 0
    for ticker, metric in after["metrics"].items():
        original = before["metrics"][ticker]
        resolved.update(set(original["quality_reasons"]) - set(metric["quality_reasons"]))
        item = {"ticker": ticker, "name": quotes[ticker]["name"],
                "roe_pct": metric["roe_pct"], "roa_pct": metric["roa_pct"],
                "before_reasons": original["quality_reasons"], "after_reasons": metric["quality_reasons"]}
        if metric["eligible"] and not original["eligible"]:
            restored.append(item)
        if original["eligible"] and not metric["eligible"]:
            lost.append(item)
        financial_ticker, basis = metric.get("financial_ticker", ticker), metric.get("basis")
        key = (financial_ticker, basis)
        if metric["eligible"]:
            assert metric["period_end"] >= metric["required_period_end"]
            assert not metric["quality_reasons"]
            roe = metric["owners_net_income"] / ((metric["start_owners_equity"] + metric["owners_equity"]) / 2) * 100
            roa = metric["net_income"] / ((metric["start_assets"] + metric["financials"]["assets"]) / 2) * 100
            assert metric["roe_pct"] == round(roe, 4) and metric["roa_pct"] == round(roa, 4), ticker
            if metric["method"] == "ttm":
                inputs = metric["income_inputs"]
                for field in ("net_income", "owners_net_income"):
                    assert metric[field] == inputs["annual"][field] + inputs["current_ytd"][field] - inputs["previous_ytd"][field], ticker
            checked += 1
        if "missing_income" not in metric["quality_reasons"]:
            continue
        fields = ["net_income", "owners_net_income", "continuing_net_income", "discontinued_net_income"]
        gaps = {name + ":" + str(source.get("period_end")): [f for f in fields if source.get(f) is None]
                for name, source in metric.get("income_inputs", {}).items()}
        patterns[json.dumps(gaps, sort_keys=True)] += 1
        residual.append({**item, "missing_fields_by_period": gaps})
    pharma = after["metrics"]["214450"]
    a, p, c = [r[("214450", "CFS")]["current"] for r in (annual, prior, current)]
    assert pharma["owners_net_income"] == a["owners_net_income"] + c["owners_net_income"] - p["owners_net_income"] == 166670004807
    assert pharma["net_income"] == a["net_income"] + c["net_income"] - p["net_income"] == 174540853599
    assert pharma["eligible"] and pharma["roe_pct"] == 23.139 and pharma["roa_pct"] == 16.331
    report = {
        "as_of": after["as_of"], "source_url": "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do",
        "annual_source_files": {s: v["filename"] for s, v in panel["bulk_financial_enrichment"]["year_results"]["2025"]["sources"].items()},
        "before_summary": before["summary"], "after_summary": after["summary"],
        "eligible_arithmetic_checks_passed": checked, "restored_count": len(restored), "lost_count": len(lost),
        "resolved_reasons": dict(resolved), "pharmaresearch": {**pharma,
            "annual_owners_net_income": a["owners_net_income"], "current_ytd_owners_net_income": c["owners_net_income"],
            "previous_ytd_owners_net_income": p["owners_net_income"], "start_owners_equity": p["owners_equity"],
            "current_price": quotes["214450"]["current_price"]},
        "restored": restored, "newly_excluded": lost, "remaining_missing_income_count": len(residual),
        "remaining_missing_income_patterns": [{"count": n, "missing_fields_by_period": json.loads(k)} for k, n in patterns.most_common()],
        "remaining_missing_income": residual,
    }
    baseline_path = output / "remaining196_baseline.json"
    if baseline_path.exists():
        baseline = read(baseline_path)
        report["followup_196"] = {
            "baseline_count": len(baseline),
            "income_gap_resolved_count": sum("missing_income" not in after["metrics"][r["ticker"]]["quality_reasons"] for r in baseline),
            "eligible_count": sum(after["metrics"][r["ticker"]]["eligible"] for r in baseline),
            "still_missing_income": [{"ticker": r["ticker"], "name": r["name"],
                "quality_reasons": after["metrics"][r["ticker"]]["quality_reasons"],
                "income_inputs": after["metrics"][r["ticker"]].get("income_inputs", {}),
                "sources": after["metrics"][r["ticker"]].get("sources", [])}
                for r in baseline if "missing_income" in after["metrics"][r["ticker"]]["quality_reasons"]],
        }
    (output / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for filename, rows in [("restored.csv", restored), ("remaining_missing_income.csv", residual)]:
        with (output / filename).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                              for k, v in row.items()} for row in rows)
    print(json.dumps({k: report[k] for k in ["restored_count", "lost_count", "eligible_arithmetic_checks_passed",
                                            "resolved_reasons", "remaining_missing_income_count"]}))


if __name__ == "__main__":
    main()
