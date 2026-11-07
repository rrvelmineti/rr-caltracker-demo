# RR Drimatra — v0.9.0

**Snap your meal. Know your calories.**

A Streamlit food-photo app that estimates portions, matches foods to USDA data, and tracks calories, macros, vitamins and minerals. Gemini analyses the photos in this version.

Docs: [rollout playbook](docs/vendor-evaluation-playbook.md) · [privacy and consent](docs/privacy-and-consent.md) · [integration spec](docs/integration-spec.md) · [pilot UAT plan](docs/pilot-uat-plan.md) · [problem statement](docs/problem-statement.md) · [user stories](docs/user-stories.md) · [accuracy evaluation](evaluation/README.md)

## The implementation case: a health plan's member wellness benefit

**Client.** A health insurer (hypothetical) wants to offer photo meal logging to its members as an
optional wellness benefit, with members able to share daily nutrition totals with the plan's coaching
platform.

**The three questions, and how each is answered:**

1. **Is it accurate enough?** The acceptance criteria are agreed first: at least 20 meals, median
   calorie error at most 20%, and at least half of meals within 20%. The app's real pipeline is then
   benchmarked on meals with known calories, and the decision is made in code (`evaluation/acceptance.py`).
   The review found the FoodCNN weight model was trained on the public Nutrition5k dishes, so testing it
   there would overstate its accuracy, and the check refuses that evidence.
2. **Is member data handled properly?** [Privacy and consent requirements](docs/privacy-and-consent.md)
   for the plan's compliance team. They cover a data inventory checked against the code, 12 requirements,
   and what the data must never be used for. Sharing is opt-in and versioned, and stops on withdrawal.
   Only one minimised record per day leaves the device, with no photos, food names or times of day, and
   the member ID is replaced by an HMAC reference.
3. **Does it integrate safely?** An [integration spec](docs/integration-spec.md) with a
   [JSON Schema](docs/meal-summary.schema.json), plus a tested reference implementation,
   `wellness_export.py`. It validates before sending, makes resends idempotent, retries with backoff,
   never retries a rejected batch, and holds undeliverable batches as dead letters.

A [pilot UAT plan](docs/pilot-uat-plan.md) has 31 cases, each traced to a requirement and an automated
test. The [rollout playbook](docs/vendor-evaluation-playbook.md) ties it all together.

```bash
# Build the daily summary batch for the sample member (synthetic diary and consent)
WELLNESS_SHARED_SECRET=$(python -c "print('x'*40)") \
  python wellness_export.py examples/wellness/diary_sample.json --member-id M-1001 \
  --consent examples/wellness/consent_sample.json --out batch.json --today 2026-11-05
```

On the sample, it shares 3 days. It leaves out the meal from before consent and the demo meal, and
marks the day with an unmatched food as incomplete, with calories left null rather than guessed.

## What you can do

1. Upload up to five views of the same meal, or capture photos with the camera. Add food names, preparation or ingredients when known.
2. Analyze the meal and review the selected USDA matches and grams. Correct the weight or mark a kitchen-scale weight. Nutrition updates without another photo-analysis call.
3. Inspect calories, protein, carbs, fat, fiber, 13 vitamins, 11 minerals and choline. Expand **Nutrition for this portion** for each food, or **Vitamins, minerals & fiber** for the meal.
4. Enable browser history and save the meal. The top daily summary counts saved meals for the browser-local date. It shows macros and selected micronutrients, with a full vitamins/minerals table beneath it.
5. Open **History**. The **Nutrient tracker** lets you switch between Macros, Vitamins, Minerals and Other, with a row per meal and a day total. Individual saved meals and foods retain their nutrient details. Wide tables scroll horizontally on phones.
6. Download a meal PDF with the nutrient amounts and coverage, or delete a saved meal. Re-saving the same reviewed meal updates its entry without duplicating it.

## Nutrient meaning and completeness

USDA supplies nutrient values per 100 g. `nutrition.py` uses explicit USDA nutrient IDs and units, then scales values to reviewed weights. It supports both search-response and food-detail response shapes. The existing search endpoint already includes these nutrients, so no extra provider key or per-food detail request is required.

- Vitamin A uses RAE; E uses alpha-tocopherol; K uses phylloquinone; D uses D2 + D3 in micrograms. B9 is total folate, not dietary folate equivalents. Different forms are not added together or substituted as equivalent.
- Vitamins B1, B2, B3, B5, B6, B7, B9 and B12 have separate rows. Biotin and iodine may be unreported for many matches.
- Units remain explicit: g, mg and mcg (micrograms). Small positive amounts are never rounded into an apparent zero.
- **Not reported** means no data for that nutrient. A reported numeric zero remains zero.
- **Partial · 1/2 foods** means the displayed amount sums only the one food with data; the other food is missing. Unmatched/excluded foods count toward missing coverage. Zero-gram portions do not dilute coverage.
- The existing strict macro totals and exported `totals` map remain unavailable if a matched food is missing the nutrient. Coverage tables separately show known amounts and completeness, derived from saved per-food values.
- These are estimated intake amounts, not personalized requirements, adequacy scores, or medical measurements. Food identification, recipes, cooking and portion uncertainty affect all results.

Older browser history stays readable. Entries saved before v0.9.0 retain their macros but do not gain invented micronutrients. A day combining old and new entries can therefore show partial micronutrient totals. Re-analyze and save a meal if you want new data; delete the old entry to avoid counting the meal twice. A sample meal remains illustrative and cannot be saved as real intake.

## Run locally or on Streamlit

Use Python 3.11 or later with the repository requirements:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The app reads settings from environment variables or Streamlit Secrets. Keep actual key values out of the repository:

- `USDA_API_KEY`: FoodData Central key for nutrition lookup.
- `GEMINI_API_KEY` and optional `GEMINI_MODEL`: the photo provider. `app.py` sets `VISION_PROVIDER = "gemini"`; the Groq code path remains in the code but `RR_VISION_PROVIDER` is not read in this version.
- `RR_PORTION_MODE=visual`: optional original visual-only portion method. Otherwise the existing local whole-dish model is used when available.

A provider error never silently switches to another provider. Diagnostics show a safe error code without exposing raw provider responses or keys. This micronutrient update does not change the working model or credentials. For another account, verify the configured model against that account's available models.

Keep `assets/fonts`, `models`, `requirements.txt` and the Streamlit configuration. This update adds no runtime dependencies. Photo limits remain 10 MB each and 12 MB combined after preparation.

## Privacy and retention

No app account or personal profile is required. Photos and optional descriptions go to the selected photo provider; food-search terms go to USDA. The local portion model runs on the app server. Photo metadata is removed before analysis. Hidden oils, mixed recipes and similar-looking foods can change estimates.

History is off until enabled. Only explicitly saved meals are stored in this browser's localStorage, without photos, keys or free-form analysis notes. Choose 1, 7 or 14 days; expiry runs while the app is open or on the next visit. Updating a meal does not reset its retention timestamp. Browser/site-data clearing also removes history. There is no cross-device sync, and anyone using the same browser profile can see it.

Viewing, saving and deleting browser history does not send the diary to Python. An explicit saved-meal PDF request sends only that snapshot to the app temporarily. Downloaded PDFs remain until you remove them. Hosting and provider operational logs are outside this app's diary controls. This update does not change Streamlit sharing settings.

## Accuracy

Calorie accuracy is measured with [`evaluation/meal_benchmark.py`](evaluation/README.md), which runs this
app's own pipeline on meals whose calories are known and reports median percentage error and the share
of meals within 20%, for photo-only portions and for FoodCNN-weighted portions. It supports your own
weighed meals and a reproducible sample of Nutrition5k test dishes. FoodCNN was trained on almost all
Nutrition5k dishes, so Nutrition5k is used with photo-only portions; your own meals are the fair test
of the weight model. No accuracy figure is claimed until a run is recorded here.

Then turn a run into a decision against the agreed criteria:

```bash
python evaluation/acceptance.py evaluation/results/my_meals.json
```

It writes `evaluation/results/my_meals-acceptance.md`: ACCEPT, REJECT or NOT READY for each portion
mode, the 5 largest errors to review by hand, and a sign-off line.

## Portion estimation

The experimental local FoodCNN model predicts total meal weight from the first photo. The selected photo provider supplies identities and visual shares; Python allocates that weight and uses reviewed grams for nutrition. It does not independently measure each food. Missing model files produce an explicit visual-estimate fallback. No calibrated accuracy claim is made. See `models/NOTICE.md` for attribution.

The optional portion benchmark is `benchmark_portions.py` at the repository root.

## Verification

```bash
python tests/run_offline.py
node --test tests/test_browser_history.mjs
```

Browser DOM checks use the development-only `jsdom` package:

```bash
RR_JSDOM_MODULE=/absolute/path/to/jsdom/lib/api.js node --test tests/test_history_dom.mjs
```

The Python runner prohibits live network calls; both photo providers use explicit test fixtures. New checks cover micronutrient units, small amounts, missing-vs-zero values, partial coverage, legacy entries, portion corrections and the Groq review/save path (`test_groq_review_portion_change_and_saved_snapshot` fails while `app.py` sets Gemini, because it selects Groq through `RR_VISION_PROVIDER`). The calorie benchmark has its own offline checks in `tests/test_meal_benchmark.py`. Browser checks cover save, reload, update, deletion, daily boundaries, nutrient-group selection and PDF payloads.

## USDA sources

- [FoodData Central API guide](https://fdc.nal.usda.gov/api-guide/)
- [Download field descriptions: per-100-g nutrient amounts](https://fdc.nal.usda.gov/portal-data/external/dataDictionary)
- [Downloadable data and nutrient.csv](https://fdc.nal.usda.gov/download-datasets/)

Nutrient IDs and unit labels were checked against USDA's supporting-data nutrient table. Missing data is not evidence that a food contains none of the nutrient.
