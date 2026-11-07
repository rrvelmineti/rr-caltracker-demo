# Playbook: rolling out photo meal logging as a health plan's member wellness benefit

How an implementation consultant would take this app to a health insurer's members. That means
answering three questions in order: *is it accurate enough? Is member data handled lawfully and
minimally? Does it integrate cleanly with the plan's wellness platform?* The insurer is a
**hypothetical** client. The benchmark, acceptance check, data flows, export and tests are the real ones
in this repository.

## The engagement in one paragraph

A health insurer wants to offer photo meal logging as an optional wellness benefit, with members able
to share daily nutrition totals with the plan's wellness coaching platform. The demo looks impressive,
but nobody has measured accuracy on real meals. Health data held by an insurer carries strict privacy
duties, and a feature that is confidently wrong would damage trust in the whole plan. The job is to
agree what "accurate enough" means and measure it fairly. Member data must leave the device only with
consent and only in minimal form, and integration with the plan's platform has to fail safely.

## Stakeholders

| Who | Role | Responsible for |
| --- | --- | --- |
| Wellness product owner (plan) | Sponsor | Agrees the acceptance criteria, makes the rollout decision |
| Registered dietitian (plan) | Subject expert | Says what error is acceptable for wellness coaching |
| Privacy officer and compliance (plan) | Approver | Signs off [privacy and consent](privacy-and-consent.md): consent, minimisation, retention, HIPAA position |
| Integration team (plan) | Builder | Builds the endpoint in the [integration spec](integration-spec.md) and runs its contract tests |
| 10 volunteer members | Testers | Use the app for 2 weeks; 5 also weigh their meals |
| Implementation consultant (me) | Delivery lead | Criteria, test design, privacy and integration documents, the pilot, the recommendation |

## 1. Agree "accurate enough" before testing

The criteria are written down **before** any meal is scored, so the result is not argued afterwards.
They live in [`evaluation/acceptance.py`](../evaluation/acceptance.py):

| Check | Target | Blocks rollout |
| --- | --- | --- |
| Meals scored | at least 20 | Yes (otherwise NOT READY) |
| Median calorie error | at most 20% | Yes |
| Meals within 20% of the true calories | at least 50% | Yes |
| Average over- or under-estimate | within ±10% | No: reported, and it decides the wording in the app |
| Meals skipped (no nutrition match) | at most 10% | No |

## 2. Design a fair test

- **Use the client's own kind of meals.** Volunteer members weigh each plate and take one phone photo
  ([how](../evaluation/README.md)). This is the test that counts.
- **Use public data only where it is fair.** Nutrition5k gives quick, reproducible results for
  photo-only portions. The FoodCNN weight model was trained on almost all Nutrition5k dishes, so its
  results there would be inflated. The acceptance check never accepts the weight model on that evidence.
- **Measure the uncorrected estimate.** Users can edit portions, but the decision is about what the AI
  gets right on its own.

## 3. Run and decide

```
python evaluation/meal_benchmark.py evaluation/data/my_meals.csv
python evaluation/acceptance.py evaluation/results/my_meals.json
```

The acceptance report gives ACCEPT, REJECT or NOT READY for each portion mode, lists the 5 largest
errors to review by hand, and ends with a sign-off line for the product owner.

## 4. Read the largest errors before recommending

Patterns matter more than the average. Typical causes to check for in the worst meals are hidden oil
or sauce, mixed dishes like curries and casseroles, and food stacked on other food. If one pattern
dominates, the recommendation can be "accept, with a prompt to add ingredients for mixed dishes"
rather than a flat yes or no.

## 5. Recommendation and rollout conditions

| Result | Recommendation |
| --- | --- |
| ACCEPT | Roll out with the accepted portion mode. Keep portions editable, show results as estimates, and say "not reported" rather than zero when nutrition data is missing (the app already does). |
| ACCEPT with bias | Roll out, and tell users the direction: for example, "photo estimates tend to run low; check portion sizes". |
| REJECT | Don't roll out the photo estimate as-is. Offer photo logging with manual weights only, or retest after the vendor improves. |
| NOT READY | Score more meals before deciding. |

## 6. Findings already made in this repository

Reviewing the code before benchmarking found two things a client would want to know:

1. The weight model's training data overlaps the public benchmark (above).
2. The documentation named a different AI provider from the one the code actually used. It was
   corrected. Checking documentation against behaviour is part of any vendor review.

## 7. Privacy and consent

Before any member data moves, the plan's privacy officer reviews
[privacy-and-consent.md](privacy-and-consent.md). It contains:

- A data inventory checked against the code. Photos go to Gemini with location and camera metadata
  removed. The diary stays in the member's browser and expires after 1 to 14 days. There is no server
  database.
- 12 requirements: opt-in, versioned consent; withdrawal; nothing from before consent; one minimised
  record per day; a pseudonymous member reference instead of the member ID; estimates flagged as
  estimates.
- What the data must never be used for: underwriting, premiums, claims or eligibility.

## 8. Integration

The plan's developers build against the [integration spec](integration-spec.md) and the JSON Schema
[meal-summary.schema.json](meal-summary.schema.json). The reference implementation,
`wellness_export.py`, checks consent, builds the records, validates the batch, and sends it. It retries
busy or unreachable endpoints with backoff, never retries a rejected batch, and holds undeliverable
batches as dead letters. Its tests double as contract tests for the plan.

## 9. Pilot and sign-off

The [pilot UAT plan](pilot-uat-plan.md) has 31 cases across privacy, integration and accuracy. Each is
traced to a requirement and to an automated test, and a test fails if any requirement is left uncovered.
Three cases are run by hand during the pilot: a live send to the plan's staging endpoint, the accuracy
benchmark on members' weighed meals, and the retention and AI-terms sign-offs.

## 10. After rollout

Rerun the benchmark and the acceptance check whenever the photo model changes. A new model version
can move accuracy in either direction.
