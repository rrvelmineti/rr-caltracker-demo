# Playbook: validating an AI feature before a client rolls it out

How an implementation consultant would use this app's benchmark to answer one client question: *is
photo calorie logging accurate enough to give to our users?* The client is a **hypothetical**
example; the benchmark, datasets and acceptance check are the real ones in this repository.

## The engagement in one paragraph

A corporate wellness provider wants to add photo meal logging to its employee app. The vendor
demo looks impressive, but nobody has measured accuracy on real meals, and a feature that is
confidently wrong would damage trust in the whole app. The job is to agree what "accurate enough"
means, measure it fairly, and give a clear accept or reject with the evidence behind it.

## Stakeholders

| Who | Role | Responsible for |
| --- | --- | --- |
| Product owner (client) | Sponsor | Agrees the acceptance criteria, makes the rollout decision |
| Registered dietitian (client) | Subject expert | Says what error is acceptable for casual tracking |
| Privacy / legal (client) | Approver | Photos and food descriptions sent to external AI providers |
| 10 volunteer employees | Testers | Weigh and photograph their own meals |
| Implementation consultant (me) | Delivery lead | Criteria, test design, benchmark runs, the recommendation |

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

- **Use the client's own kind of meals.** Volunteers weigh each plate and take one phone photo
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

## 7. After rollout

Rerun the benchmark and the acceptance check whenever the photo model changes. A new model version
can move accuracy in either direction.
