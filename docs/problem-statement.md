# Problem statement

People tracking what they eat usually can't weigh food when they eat out, at work or with friends.
Typing every ingredient into a tracker takes long enough that most people give up.

**Goal:** log a meal from a photo in under a minute, with an honest estimate the user can correct,
and nutrition from a trusted source.

**Users:** people tracking calories or nutrients casually, away from a kitchen scale.

**Approach:**
- A photo model names the foods and estimates portions; a local model estimates total plate weight.
- USDA FoodData Central supplies nutrition per 100 g, scaled to the portion.
- The user reviews every food and weight before saving, and can enter a weighed portion.
- Missing data is shown as "not reported", never as zero.

**Trade-off:** convenience over precision. A photo can't see hidden oil, sauce or what's under the
rice, so results are labelled as estimates and portions stay editable.

**Out of scope:** medical or dietary advice, personalised requirements, barcode scanning.

**How we will know it works:** calorie error measured on meals with known calories
(`evaluation/meal_benchmark.py`), reported as median percentage error and the share of meals within
20%.
