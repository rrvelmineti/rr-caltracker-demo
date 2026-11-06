# User stories

First drafted with an AI assistant from a short brief, then reviewed. Record changes in the review
log below.

**Brief given to the AI:** "A user eating away from home photographs a meal and wants calories and
nutrients without weighing anything. Write user stories with acceptance criteria. The estimate must be
honest and correctable."

### US-1 Log a meal from a photo
As a user, I want to photograph my plate and get its foods and calories so that I can log a meal
without weighing it.
- Up to five photos of the same meal can be added; duplicates are included once.
- Photo metadata is removed before analysis.

### US-2 Correct the estimate
As a user, I want to change any food's weight, or enter a weighed amount, so that the totals match
what I actually ate.
- Nutrition updates immediately without another photo analysis.
- A weighed portion is marked as measured.

### US-3 Trust the nutrition source
As a user, I want nutrition from USDA data so that the numbers come from a recognised source.
- Each food is matched to USDA FoodData Central; I can pick a different match.
- Nutrients with no data show "not reported", not zero; partial totals say how many foods they cover.

### US-4 Keep and share a record
As a user, I want to save meals and download a summary so that I can review my day or share it.
- History is off until I turn it on, stays in my browser, and expires after 1, 7 or 14 days.
- A meal can be downloaded as a PDF.

### US-5 Know how accurate it is
As the developer, I want calorie error measured on meals with known calories so that I can state the
app's accuracy honestly.
- The benchmark runs the app's own pipeline on a list of meals and reports error metrics.
- Results on data the weight model was trained on are flagged as not a fair test.

## Review log

| Story | What changed after review | Why |
| --- | --- | --- |
| | | |
