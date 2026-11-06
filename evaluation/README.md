# Calorie accuracy evaluation

`meal_benchmark.py` runs the app's own pipeline on meals whose calories are known and reports how far
the **uncorrected** estimate is from the truth: the photo model names the foods and estimates grams,
USDA supplies nutrition, and calories are scaled to those grams. It scores two portion modes:

- **visual**: grams from the photo model alone
- **hybrid**: the local FoodCNN model estimates the total weight, split by the photo model's shares
  (the app's default)

Metrics: mean absolute error in kcal, mean and median absolute percentage error, signed bias, and how
many meals land within 20% and 30%. When a weight is given, weight error is reported too. Meals with a
food that has no USDA match are counted as skipped, not scored.

Both data options need `GEMINI_API_KEY` and `USDA_API_KEY`, as the app does. Photos stay on your
computer: anything under `evaluation/data/` is ignored by git, and results record row numbers, not
image paths.

## Option 1: your own meals (the fair test)

1. Before eating, weigh the food on a kitchen scale with the plate tared, and take one overhead phone
   photo of the whole plate.
2. Work out the calories from package labels, or from USDA values at the weighed grams for each food.
3. Put the photos in `evaluation/data/photos/` and copy `own_meals_template.csv` to
   `evaluation/data/my_meals.csv`, one row per meal. 20 to 30 varied meals give a usable result.
4. Run:

   ```
   python evaluation/meal_benchmark.py evaluation/data/my_meals.csv
   ```

## Option 2: Nutrition5k test dishes (quick, public, visual mode only)

[Nutrition5k](https://github.com/google-research-datasets/Nutrition5k) (Google Research, CC BY 4.0)
has real cafeteria dishes with weighed ingredients and calories.

```
python evaluation/fetch_nutrition5k.py
python evaluation/meal_benchmark.py evaluation/data/nutrition5k/manifest.csv --modes visual
```

The sampler takes 30 dishes from the dataset's official test split, with a fixed seed.

**Use visual mode only on Nutrition5k.** The FoodCNN weight model was trained on frames extracted from
videos of almost every Nutrition5k dish, split at random by image (see its
[training notebook](https://github.com/FoodCNN/FoodCNN/blob/main/src/02_weight_estimation/DeepWeightCNN.ipynb)),
so hybrid results on these photos would overstate it. The benchmark prints this warning if hybrid mode
is run on Nutrition5k rows. Nutrition5k photos are also taken by a fixed overhead camera in a
cafeteria, unlike a phone photo at home, so the own-meals test remains the better measure.

## Results

Results are written to `evaluation/results/<manifest name>.json`. Record the headline numbers in the
main README once you have run a set.

## Acceptance decision

```
python evaluation/acceptance.py evaluation/results/my_meals.json
```

The check compares a run with criteria agreed before testing: at least 20 meals scored, median calorie
error at most 20%, and at least half of meals within 20% (blocking); bias within ±10% and at most 10%
skipped (reported). It decides ACCEPT, REJECT or NOT READY for each portion mode, and never accepts
hybrid mode on Nutrition5k. See the [vendor evaluation playbook](../docs/vendor-evaluation-playbook.md).
