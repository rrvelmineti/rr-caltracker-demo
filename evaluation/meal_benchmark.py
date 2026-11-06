"""Measure calorie estimates against meals whose calories are known.

Runs the app's own pipeline on each photo: the photo model names the foods and estimates grams,
optionally the local FoodCNN model rescales the total weight, USDA supplies nutrition, and calories
are scaled to the estimated grams using each food's first USDA match. No portion is corrected, so
this measures the estimate a user sees before reviewing it.

    python evaluation/meal_benchmark.py evaluation/data/my_meals.csv

Manifest CSV columns (header required):
    image_path      photo of the whole plate, relative to the manifest or absolute
    known_kcal      calories of the meal as served (from labels, recipes or weighed USDA values)
    measured_food_g optional: total food weight, container tared
    description     optional: what you would type into the app, e.g. "chicken, rice, broccoli"
    source          optional: "own" (default) or "nutrition5k"

Needs GEMINI_API_KEY and USDA_API_KEY, the same settings as the app. Results are written to
evaluation/results/ with per-meal rows (row numbers, not image paths) and summary metrics.
"""
import argparse
import csv
import io
import json
import math
import statistics
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FOODCNN_NOTE = ("FoodCNN was trained on frames of almost every Nutrition5k dish, so hybrid-mode results on "
                "Nutrition5k photos are not a fair test of the weight model. Use visual mode, or your own meals.")


def read_manifest(path):
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for n, row in enumerate(csv.DictReader(handle), start=2):
            kcal = float(row["known_kcal"])
            if not math.isfinite(kcal) or not 1 <= kcal <= 10_000:
                raise ValueError(f"Row {n}: known_kcal must be between 1 and 10,000.")
            grams = row.get("measured_food_g", "").strip()
            image = Path(row["image_path"])
            rows.append({"row": n, "image": image if image.is_absolute() else path.parent / image, "known_kcal": kcal,
                         "measured_g": float(grams) if grams else None, "description": row.get("description", "").strip(),
                         "source": (row.get("source") or "own").strip().lower()})
    if not rows:
        raise ValueError("The manifest has no meals.")
    return rows


def meal_calories(foods, candidates):
    """Calories of the foods at their estimated grams, using the first USDA match for each food."""
    from nutrition import scale_nutrients
    total, matched, unmatched = 0.0, 0, []
    for food, options in zip(foods, candidates):
        kcal = scale_nutrients(options[0], food.grams).get("Calories") if options else None
        if kcal is None:
            unmatched.append(food.name)
        else:
            total += kcal
            matched += 1
    return total, matched, unmatched


def estimate(row, modes, keys, app, portions):
    raw = row["image"].read_bytes()
    images = app.prepare_meal_photos([io.BytesIO(raw)])
    meal = app.identify_foods(images, row["description"], keys["vision"])
    out = {"row": row["row"], "source": row["source"], "known_kcal": row["known_kcal"], "measured_g": row["measured_g"],
           "foods": [f.name for f in meal.foods]}
    candidates, errors = app.lookup_nutrition(meal.foods, keys["usda"])
    if errors:
        out["usda_errors"] = errors
    for mode in modes:
        foods = meal.foods
        if mode == "hybrid":
            try:
                foods = portions.apply_portions(meal, portions.predict_mass(images[0]))[0].foods
            except portions.PortionError as exc:
                out[mode] = {"error": str(exc)}
                continue
        kcal, matched, unmatched = meal_calories(foods, candidates)
        out[mode] = {"kcal": round(kcal, 1), "grams": round(sum(f.grams for f in foods), 1),
                     "foods_matched": matched, "foods_unmatched": unmatched}
    return out


def metrics(rows, mode):
    usable = [r for r in rows if isinstance(r.get(mode), dict) and "kcal" in r[mode] and not r[mode]["foods_unmatched"]]
    if not usable:
        return {"meals": 0}
    err = [r[mode]["kcal"] - r["known_kcal"] for r in usable]
    pct = [abs(e) / r["known_kcal"] * 100 for e, r in zip(err, usable)]
    out = {"meals": len(usable), "skipped_unmatched_or_failed": len(rows) - len(usable),
           "kcal_mae": round(sum(abs(e) for e in err) / len(err), 1),
           "kcal_mape_percent": round(sum(pct) / len(pct), 1),
           "kcal_median_ape_percent": round(statistics.median(pct), 1),
           "mean_signed_kcal_error": round(sum(err) / len(err), 1),
           "within_20_percent": sum(p <= 20 for p in pct), "within_30_percent": sum(p <= 30 for p in pct)}
    weighed = [r for r in usable if r["measured_g"]]
    if weighed:
        gpct = [abs(r[mode]["grams"] - r["measured_g"]) / r["measured_g"] * 100 for r in weighed]
        out["weight_mape_percent"] = round(sum(gpct) / len(gpct), 1)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--modes", default="visual,hybrid", help="visual, hybrid or both (default both)")
    parser.add_argument("--delay", type=float, default=4.0, help="seconds between meals, for API rate limits")
    parser.add_argument("--name", help="results file name (default: manifest name)")
    args = parser.parse_args(argv)
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if not set(modes) <= {"visual", "hybrid"}:
        raise SystemExit("--modes takes visual, hybrid or both.")
    import app
    import portion_estimator
    keys = {"vision": app.app_setting("GEMINI_API_KEY"), "usda": app.app_setting("USDA_API_KEY")}
    if not keys["vision"] or not keys["usda"]:
        raise SystemExit("Set GEMINI_API_KEY and USDA_API_KEY, as for the app.")
    rows = read_manifest(args.manifest)
    if "hybrid" in modes and any(r["source"] == "nutrition5k" for r in rows):
        print("Note: " + FOODCNN_NOTE)
    results = []
    for i, row in enumerate(rows):
        try:
            results.append(estimate(row, modes, keys, app, portion_estimator))
        except Exception as exc:  # report every failure and keep going; one bad photo should not stop the run
            results.append({"row": row["row"], "source": row["source"], "known_kcal": row["known_kcal"],
                            "measured_g": row["measured_g"], "error": f"{type(exc).__name__}: {exc}"[:300]})
        r = results[-1]
        shown = "  ".join(f"{m} {r[m]['kcal']:.0f}" for m in modes if isinstance(r.get(m), dict) and "kcal" in r[m])
        print(f"row {row['row']}: known {row['known_kcal']:.0f} kcal  {shown or r.get('error', 'no estimate')}")
        if i + 1 < len(rows):
            time.sleep(args.delay)
    summary = {"run_on": date.today().isoformat(), "manifest": args.manifest.name, "meals": len(rows),
               "photo_model": app.app_setting("GEMINI_MODEL", "gemini-3.5-flash-lite"),
               "method": "Uncorrected app estimate: first USDA match per food at the estimated grams.",
               **{mode: metrics(results, mode) for mode in modes}}
    if "hybrid" in modes and any(r["source"] == "nutrition5k" for r in rows):
        summary["hybrid_caveat"] = FOODCNN_NOTE
    out_dir = ROOT / "evaluation" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or args.manifest.stem
    (out_dir / f"{name}.json").write_text(json.dumps({"summary": summary, "meals": results}, indent=2) + "\n",
                                          encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Wrote evaluation/results/{name}.json")


if __name__ == "__main__":
    main()
