"""The accuracy acceptance check in evaluation/acceptance.py. Offline; reads only synthetic results."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation"))
import acceptance  # noqa: E402


def result(n=24, median=15.0, within=16, signed=20.0, skipped=1, modes=("visual",), caveat=None, known=500.0):
    metrics = {"meals": n, "skipped_unmatched_or_failed": skipped, "kcal_mae": 60.0, "kcal_mape_percent": 18.0,
               "kcal_median_ape_percent": median, "mean_signed_kcal_error": signed,
               "within_20_percent": within, "within_30_percent": n}
    summary = {"run_on": "2026-11-06", "manifest": "my_meals.csv", "meals": n + skipped, "photo_model": "m",
               "method": "Uncorrected app estimate.", **{m: metrics for m in modes}}
    if caveat:
        summary["hybrid_caveat"] = caveat
    meals = [{"row": i + 2, "known_kcal": known, "measured_g": None,
              **{m: {"kcal": known * (1 + (i % 5) / 10), "grams": 300, "foods_unmatched": 0} for m in modes}}
             for i in range(n)]
    return {"summary": summary, "meals": meals}


class AcceptanceTests(unittest.TestCase):
    def test_a_good_run_is_accepted(self):
        modes = acceptance.assess(result())
        self.assertEqual(modes["visual"]["decision"], acceptance.ACCEPT)
        self.assertEqual(acceptance.overall(modes), acceptance.ACCEPT)

    def test_high_median_error_is_rejected(self):
        self.assertEqual(acceptance.assess(result(median=27.5))["visual"]["decision"], acceptance.REJECT)

    def test_too_few_meals_in_the_20_percent_band_is_rejected(self):
        self.assertEqual(acceptance.assess(result(within=10))["visual"]["decision"], acceptance.REJECT)   # 42%

    def test_too_few_meals_is_not_ready(self):
        self.assertEqual(acceptance.assess(result(n=12, within=10))["visual"]["decision"], acceptance.NOT_READY)

    def test_bias_is_reported_but_does_not_block(self):
        modes = acceptance.assess(result(signed=90.0))                     # 18% over on 500 kcal meals
        checks = {c["id"]: c for c in modes["visual"]["checks"]}
        self.assertEqual(checks["bias"]["status"], "fail")
        self.assertIn("18.0% over", checks["bias"]["result"])
        self.assertEqual(modes["visual"]["decision"], acceptance.ACCEPT)

    def test_hybrid_on_nutrition5k_is_never_accepted(self):
        modes = acceptance.assess(result(modes=("visual", "hybrid"), caveat="FoodCNN was trained on Nutrition5k."))
        self.assertEqual(modes["hybrid"]["decision"], acceptance.NOT_READY)
        self.assertTrue(modes["hybrid"]["invalid_evidence"])
        self.assertEqual(modes["visual"]["decision"], acceptance.ACCEPT)

    def test_worst_meals_are_listed_largest_first(self):
        worst = acceptance.assess(result())["visual"]["worst"]
        self.assertEqual(len(worst), acceptance.WORST)
        self.assertEqual(worst[0]["error_percent"], 40.0)
        self.assertEqual([w["error_percent"] for w in worst], sorted((w["error_percent"] for w in worst), reverse=True))

    def test_report_is_written_with_a_decision_and_sign_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "my_meals.json"
            path.write_text(json.dumps(result(median=27.5)))
            with redirect_stdout(io.StringIO()):
                code = acceptance.main([str(path)])
            text = (Path(tmp) / "my_meals-acceptance.md").read_text()
        self.assertEqual(code, 1)
        self.assertIn("**Overall: REJECT**", text)
        self.assertIn("| Median calorie error | 27.5% | at most 20% | yes | **Fail** |", text)
        self.assertIn("Sign-off:", text)


if __name__ == "__main__":
    unittest.main()
