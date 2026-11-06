"""Download a small, reproducible sample of Nutrition5k test dishes for the calorie benchmark.

    python evaluation/fetch_nutrition5k.py            # 30 dishes into evaluation/data/nutrition5k/
    python evaluation/meal_benchmark.py evaluation/data/nutrition5k/manifest.csv --modes visual

Nutrition5k (Google Research, CC BY 4.0) has real cafeteria dishes with weighed ingredients and
calories. Dishes come from the dataset's official RGB test split, with overhead photos only.
Files are downloaded over HTTPS from the public Cloud Storage bucket and are not committed.

Important: the app's FoodCNN weight model was trained on frames of almost every Nutrition5k dish,
so use --modes visual for this sample. Hybrid results here would overstate the weight model.

Citation: Thames et al., "Nutrition5k: Towards Automatic Nutritional Understanding of Generic Food",
CVPR 2021. https://github.com/google-research-datasets/Nutrition5k
"""
import argparse
import csv
import io
import random
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://storage.googleapis.com/nutrition5k_dataset/nutrition5k_dataset/"
OUT = Path(__file__).resolve().parent / "data" / "nutrition5k"
SEED = 2026


def get(path, timeout=60):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as response:
        return response.read()


def dish_metadata():
    """dish_id -> (total_calories, total_mass_g, ingredient names), from both cafeterias."""
    dishes = {}
    for cafe in ("dish_metadata_cafe1.csv", "dish_metadata_cafe2.csv"):
        for row in csv.reader(io.StringIO(get("metadata/" + cafe).decode("utf-8"))):
            if len(row) < 6 or not row[0].startswith("dish_"):
                continue
            names = [row[i] for i in range(7, len(row), 7)]       # per ingredient: id, name, grams, kcal, fat, carb, protein
            dishes[row[0]] = (float(row[1]), float(row[2]), names)
    return dishes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--min-kcal", type=float, default=100, help="skip near-empty plates")
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    test_ids = get("dish_ids/splits/rgb_test_ids.txt").decode().split()
    meta = dish_metadata()
    pool = sorted(d for d in test_ids if d in meta and meta[d][0] >= args.min_kcal)
    random.Random(SEED).shuffle(pool)
    rows = []
    for dish in pool:
        if len(rows) == args.count:
            break
        target = OUT / f"{dish}.png"
        if not target.exists():
            try:
                target.write_bytes(get(f"imagery/realsense_overhead/{dish}/rgb.png"))
            except urllib.error.HTTPError:
                continue                                          # some test dishes have no overhead image
        kcal, grams, names = meta[dish]
        rows.append({"image_path": target.name, "known_kcal": round(kcal, 1), "measured_food_g": round(grams, 1),
                     "description": "", "source": "nutrition5k", "dish_id": dish, "ingredients": "; ".join(names)})
        print(f"{len(rows):>2}. {dish}: {kcal:.0f} kcal, {grams:.0f} g")
    with (OUT / "manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} dishes and manifest.csv to {OUT}")


if __name__ == "__main__":
    main()
