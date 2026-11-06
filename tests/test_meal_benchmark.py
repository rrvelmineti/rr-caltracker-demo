"""Offline checks for the calorie benchmark and the Nutrition5k sampler. No network is used."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evaluation"))

import app  # noqa: E402
import fetch_nutrition5k  # noqa: E402
import meal_benchmark  # noqa: E402


def usda_food(kcal_per_100g):
    return {"description": "test food", "fdcId": 1,
            "foodNutrients": [{"nutrientId": 1008, "value": kcal_per_100g, "unitName": "KCAL"}]}


def meal(*foods):
    return app.Meal(foods=[app.Food(name=n, search_query=n, grams=g, grams_low=g * .8, grams_high=g * 1.2)
                           for n, g in foods], assumptions=[])


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        Image.new("RGB", (64, 64), "white").save(self.dir / "plate.jpg")

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self, text):
        path = self.dir / "meals.csv"
        path.write_text(text, encoding="utf-8")
        return path

    def test_manifest_resolves_paths_and_rejects_bad_calories(self):
        rows = meal_benchmark.read_manifest(self.manifest(
            "image_path,known_kcal,measured_food_g,description\nplate.jpg,650,420,rice and chicken\n"))
        self.assertEqual((rows[0]["image"], rows[0]["known_kcal"], rows[0]["measured_g"], rows[0]["source"]),
                         (self.dir / "plate.jpg", 650.0, 420.0, "own"))
        for bad in ("0", "nan", "20000"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                meal_benchmark.read_manifest(self.manifest(f"image_path,known_kcal\nplate.jpg,{bad}\n"))

    def test_calories_scale_to_estimated_grams_and_unmatched_foods_are_reported(self):
        foods = meal(("rice", 200), ("chicken", 150), ("sauce", 30)).foods
        total, matched, unmatched = meal_benchmark.meal_calories(foods, [[usda_food(130)], [usda_food(165)], []])
        self.assertAlmostEqual(total, 200 * 1.30 + 150 * 1.65)
        self.assertEqual((matched, unmatched), (2, ["sauce"]))

    def test_metrics(self):
        rows = [{"row": 2, "known_kcal": 500, "measured_g": 400,
                 "visual": {"kcal": 600, "grams": 440, "foods_unmatched": []}},
                {"row": 3, "known_kcal": 800, "measured_g": None,
                 "visual": {"kcal": 720, "grams": 500, "foods_unmatched": []}},
                {"row": 4, "known_kcal": 300, "measured_g": None,
                 "visual": {"kcal": 100, "grams": 90, "foods_unmatched": ["gravy"]}},     # excluded: incomplete
                {"row": 5, "known_kcal": 300, "error": "photo failed"}]
        m = meal_benchmark.metrics(rows, "visual")
        self.assertEqual((m["meals"], m["skipped_unmatched_or_failed"]), (2, 2))
        self.assertEqual((m["kcal_mae"], m["kcal_mape_percent"], m["mean_signed_kcal_error"]), (90.0, 15.0, 10.0))
        self.assertEqual((m["within_20_percent"], m["weight_mape_percent"]), (2, 10.0))

    def test_full_run_uses_the_app_pipeline_and_writes_results_without_image_paths(self):
        path = self.manifest("image_path,known_kcal,measured_food_g,source\nplate.jpg,600,380,own\n")
        with patch.object(meal_benchmark, "ROOT", self.dir), \
             patch.dict("os.environ", {"GEMINI_API_KEY": "test", "USDA_API_KEY": "test"}), \
             patch.object(app, "identify_foods", return_value=meal(("rice", 200), ("chicken", 150))) as vision, \
             patch.object(app, "lookup_nutrition", return_value=([[usda_food(130)], [usda_food(165)]], [])), \
             patch("portion_estimator.predict_mass", return_value=app.portion_estimator.PortionEstimate(420.0)):
            meal_benchmark.main([str(path), "--delay", "0", "--name", "unit"])
        self.assertEqual(vision.call_count, 1)                        # one photo call serves both modes
        result = json.loads((self.dir / "evaluation" / "results" / "unit.json").read_text())
        visual, hybrid = result["meals"][0]["visual"], result["meals"][0]["hybrid"]
        self.assertAlmostEqual(visual["kcal"], 507.5)
        self.assertAlmostEqual(hybrid["grams"], 420.0)                 # FoodCNN total, split by visual shares
        self.assertAlmostEqual(hybrid["kcal"], 240 * 1.30 + 180 * 1.65)
        self.assertNotIn("plate.jpg", json.dumps(result))

    def test_failures_are_recorded_and_the_run_continues(self):
        path = self.manifest("image_path,known_kcal\nplate.jpg,600\nmissing.jpg,400\n")
        with patch.object(meal_benchmark, "ROOT", self.dir), \
             patch.dict("os.environ", {"GEMINI_API_KEY": "test", "USDA_API_KEY": "test"}), \
             patch.object(app, "identify_foods", return_value=meal(("rice", 200))), \
             patch.object(app, "lookup_nutrition", return_value=([[usda_food(130)]], [])):
            meal_benchmark.main([str(path), "--modes", "visual", "--delay", "0", "--name", "unit"])
        meals = json.loads((self.dir / "evaluation" / "results" / "unit.json").read_text())["meals"]
        self.assertIn("visual", meals[0])
        self.assertIn("FileNotFoundError", meals[1]["error"])


class Nutrition5kSamplerTests(unittest.TestCase):
    def test_metadata_parsing_reads_totals_and_ingredient_names(self):
        csv_text = ("dish_1556572657,300.79,193.0,12.4,30.2,15.9,"
                    "ingr_0000000508,soy sauce,3.4,2.1,0.0,0.2,0.3,"
                    "ingr_0000000122,white rice,120.0,156.0,0.4,34.0,3.2\n")
        with patch.object(fetch_nutrition5k, "get", side_effect=[csv_text.encode(), b""]):
            meta = fetch_nutrition5k.dish_metadata()
        self.assertEqual(meta["dish_1556572657"], (300.79, 193.0, ["soy sauce", "white rice"]))

    def test_benchmark_warns_about_foodcnn_on_nutrition5k(self):
        self.assertIn("trained on", meal_benchmark.FOODCNN_NOTE)


if __name__ == "__main__":
    unittest.main()
