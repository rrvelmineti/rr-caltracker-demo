"""Acceptance check: is the AI accurate enough to roll out? Reads a benchmark result and decides per portion mode.

    python evaluation/meal_benchmark.py evaluation/data/my_meals.csv      # first, needs the API keys
    python evaluation/acceptance.py evaluation/results/my_meals.json

Writes evaluation/results/<name>-acceptance.md. Exit code 0 = ACCEPT (at least one mode),
1 = REJECT, 2 = NOT READY (too few meals, or no valid evidence).

The criteria are agreed with the client before the benchmark is run, so the result is not argued
afterwards. A mode whose results are known to be inflated (FoodCNN hybrid on Nutrition5k, which it
was trained on) is never accepted on that evidence.
"""
import argparse
import json
import sys
from pathlib import Path

ACCEPT, REJECT, NOT_READY = "ACCEPT", "REJECT", "NOT READY"
WORST = 5

CRITERIA = [
    {"id": "sample", "label": "Meals scored", "blocking": True, "min": 20,
     "value": lambda m, s: m.get("meals", 0)},
    {"id": "median_error", "label": "Median calorie error", "blocking": True, "max_percent": 20,
     "value": lambda m, s: m.get("kcal_median_ape_percent")},
    {"id": "within_20", "label": "Meals within 20% of the true calories", "blocking": True, "min_share": 0.5,
     "value": lambda m, s: (m.get("within_20_percent"), m.get("meals"))},
    {"id": "bias", "label": "Average over- or under-estimate (bias)", "blocking": False, "max_abs_percent": 10,
     "value": lambda m, s: (m.get("mean_signed_kcal_error"), s.get("_mean_known_kcal"))},
    {"id": "skipped", "label": "Meals skipped (no USDA match or failed)", "blocking": False, "max_share": 0.1,
     "value": lambda m, s: (m.get("skipped_unmatched_or_failed"), s.get("meals"))},
]


def judge(c, mode_metrics, summary):
    v = c["value"](mode_metrics, summary)
    row = {"id": c["id"], "label": c["label"], "blocking": c["blocking"]}
    if "min" in c:
        return {**row, "result": str(v), "target": f"at least {c['min']}", "status": "pass" if v >= c["min"] else "fail"}
    if "max_percent" in c:
        if v is None:
            return {**row, "result": "not measured", "target": f"at most {c['max_percent']}%", "status": "missing"}
        return {**row, "result": f"{v}%", "target": f"at most {c['max_percent']}%",
                "status": "pass" if v <= c["max_percent"] else "fail"}
    n, total = v
    if n is None or not total:
        target = (f"at least {c['min_share']:.0%}" if "min_share" in c else
                  f"within ±{c['max_abs_percent']}%" if "max_abs_percent" in c else f"at most {c['max_share']:.0%}")
        return {**row, "result": "not measured", "target": target, "status": "missing"}
    if "min_share" in c:
        share = n / total
        return {**row, "result": f"{n} of {total} ({share:.0%})", "target": f"at least {c['min_share']:.0%}",
                "status": "pass" if share >= c["min_share"] else "fail"}
    if "max_abs_percent" in c:
        pct = n / total * 100
        word = "over" if pct > 0 else "under"
        return {**row, "result": f"{abs(pct):.1f}% {word} ({n:+.0f} kcal per meal)",
                "target": f"within ±{c['max_abs_percent']}%", "status": "pass" if abs(pct) <= c["max_abs_percent"] else "fail"}
    share = n / total
    return {**row, "result": f"{n} of {total} ({share:.0%})", "target": f"at most {c['max_share']:.0%}",
            "status": "pass" if share <= c["max_share"] else "fail"}


def assess(result):
    """Decision per portion mode found in a meal_benchmark result."""
    summary = dict(result["summary"])
    known = [m["known_kcal"] for m in result.get("meals", []) if m.get("known_kcal")]
    summary["_mean_known_kcal"] = sum(known) / len(known) if known else None
    modes = {}
    for mode in ("visual", "hybrid"):
        if mode not in summary:
            continue
        checks = [judge(c, summary[mode], summary) for c in CRITERIA]
        blocking = [c for c in checks if c["blocking"]]
        invalid = mode == "hybrid" and bool(summary.get("hybrid_caveat"))
        if invalid or any(c["status"] == "missing" for c in blocking) or \
                next(c for c in checks if c["id"] == "sample")["status"] == "fail":
            decision = NOT_READY
        else:
            decision = ACCEPT if all(c["status"] == "pass" for c in blocking) else REJECT
        modes[mode] = {"decision": decision, "checks": checks, "invalid_evidence": invalid,
                       "worst": worst_meals(result.get("meals", []), mode)}
    return modes


def worst_meals(meals, mode, n=WORST):
    scored = [(abs(m[mode]["kcal"] - m["known_kcal"]) / m["known_kcal"] * 100, m) for m in meals
              if isinstance(m.get(mode), dict) and "kcal" in m[mode] and m.get("known_kcal")]
    return [{"row": m["row"], "known_kcal": m["known_kcal"], "estimated_kcal": round(m[mode]["kcal"]),
             "error_percent": round(p, 1)} for p, m in sorted(scored, key=lambda x: -x[0])[:n]]


def overall(modes):
    decisions = [m["decision"] for m in modes.values()]
    if ACCEPT in decisions:
        return ACCEPT
    return REJECT if REJECT in decisions else NOT_READY


def report(result, modes):
    s = result["summary"]
    status = {"pass": "Pass", "fail": "**Fail**", "missing": "Not measured"}
    lines = ["# Accuracy acceptance", "", f"**Overall: {overall(modes)}**", "",
             f"Benchmark `{s.get('manifest')}`, run on {s.get('run_on')}, photo model `{s.get('photo_model')}`, "
             f"{s.get('meals')} meals. {s.get('method', '')}", ""]
    for mode, m in modes.items():
        lines += [f"## {mode.capitalize()} portions: {m['decision']}", ""]
        if m["invalid_evidence"]:
            lines += [f"Not valid evidence: {s['hybrid_caveat']}", ""]
        lines += ["| Check | Result | Target | Blocking | Status |", "| --- | --- | --- | --- | --- |"]
        lines += [f"| {c['label']} | {c['result']} | {c['target']} | {'yes' if c['blocking'] else 'no'} | "
                  f"{status[c['status']]} |" for c in m["checks"]]
        if m["worst"]:
            lines += ["", "Largest errors, to review by hand (manifest row numbers):", "",
                      "| Row | Known kcal | Estimated kcal | Error |", "| --- | ---: | ---: | ---: |"]
            lines += [f"| {w['row']} | {w['known_kcal']:.0f} | {w['estimated_kcal']} | {w['error_percent']}% |" for w in m["worst"]]
        lines += [""]
    lines += [{
        ACCEPT: "At least one portion mode meets every blocking criterion. Roll out with that mode, keep portions "
                "editable, and label results as estimates.",
        REJECT: "No portion mode meets the agreed accuracy. Review the largest errors for patterns (hidden oils, "
                "mixed dishes, portion size) before deciding whether to retest or not roll out.",
        NOT_READY: "There is not enough valid evidence for a decision. Score at least 20 meals, and test the "
                   "weight model on your own weighed meals rather than Nutrition5k.",
    }[overall(modes)], "", "Sign-off: ______________________  (client owner)   Date: __________", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", type=Path, help="JSON written by evaluation/meal_benchmark.py")
    parser.add_argument("--out", type=Path, help="default: next to the results, ending -acceptance.md")
    args = parser.parse_args(argv)
    result = json.loads(args.results.read_text(encoding="utf-8"))
    modes = assess(result)
    if not modes:
        raise SystemExit("The results file has no visual or hybrid summary.")
    out = args.out or args.results.with_name(args.results.stem + "-acceptance.md")
    out.write_text(report(result, modes), encoding="utf-8")
    for mode, m in modes.items():
        print(f"{mode}: {m['decision']}")
    decision = overall(modes)
    print(f"\nOverall: {decision}. Wrote {out}")
    return {ACCEPT: 0, REJECT: 1, NOT_READY: 2}[decision]


if __name__ == "__main__":
    sys.exit(main())
