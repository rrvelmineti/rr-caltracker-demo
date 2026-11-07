# Integration spec: daily meal summaries to the wellness platform

**For:** the health plan's integration developers. **Version:** 1.0, 7 November 2026.
**Reference implementation:** [`wellness_export.py`](../wellness_export.py). **Schema:**
[`meal-summary.schema.json`](meal-summary.schema.json). Privacy rules come from
[privacy-and-consent.md](privacy-and-consent.md).

## Requirements

| ID | Requirement | Section |
| --- | --- | --- |
| IN-01 | Every batch matches schema 1.0 exactly; unknown fields are not allowed | §3 |
| IN-02 | Daily totals are summed and rounded as specified; missing values stay null and mark the day incomplete | §3 |
| IN-03 | A resent day is never double counted (idempotency) | §2, §3 |
| IN-04 | Busy or unreachable partner: retry with backoff, then dead letter; never drop a batch silently | §4 |
| IN-05 | A rejected batch is not retried | §4 |
| IN-06 | An invalid batch is never sent | §4 |
| IN-07 | The published schema file and the code agree | §3 |

## 1. Flow

```
member's diary (browser) ─> consent check ─> one minimised record per day ─> validate ─> POST batch ─> plan
                                 │ no consent: nothing built, nothing sent          │ 429/5xx: retry with backoff
                                 └─ reason shown to the member                      └─ 400/401/403/422: stop, log
```

In the pilot, a **"Share with my health plan"** button in the app's History page will run this export
for the days the member chooses. Until then, `wellness_export.py` runs the same logic from a diary file
in the app's browser-storage format (`rr-caltracker:diary:v1`).

## 2. Endpoint

| | |
| --- | --- |
| Method and path | `POST /v1/meal-summaries` (base URL given by the plan per environment) |
| Auth | `Authorization: Bearer <token>`, a client-credentials token issued by the plan, rotated every 90 days |
| Content type | `application/json`, UTF-8 |
| Idempotency | `Idempotency-Key: <batch_id>` header; the plan also de-duplicates records on `idempotency_key` |
| Size | At most 500 records per batch |
| Transport | TLS 1.2 or higher. No data in URLs or query strings. |

## 3. Payload

```json
{
  "schema_version": "1.0",
  "partner": "rr-caltracker",
  "batch_id": "1d1f6f7e-6b6e-4e8e-9d0b-5a8f3c2b7e11",
  "generated_at": "2026-11-05T21:04:10+00:00",
  "records": [{
    "member_ref": "d22c0bb0fa29…(64 hex)",
    "date": "2026-11-02",
    "meals_logged": 3,
    "meal_types": {"Breakfast": 1, "Lunch": 1, "Dinner": 1, "Snack": 0},
    "calories_kcal": 1640,
    "calories_range_kcal": [1320, 1990],
    "protein_g": 87.2, "carbs_g": 182.8, "fat_g": 54.8, "fiber_g": 18.3,
    "complete": true,
    "estimated": true,
    "consent_version": "2026-11",
    "idempotency_key": "…(64 hex)"
  }]
}
```

### Field rules

| Field | Rule |
| --- | --- |
| `member_ref` | `HMAC-SHA256(secret, member_id)` as lowercase hex. The secret is at least 32 characters, shared out of band and never logged. |
| `date` | The member's local date, `YYYY-MM-DD`. Never before consent, never in the future. |
| `meal_types` | All four keys present; the counts add up to `meals_logged`. |
| `calories_kcal` | Sum for the day, rounded to 10. **Null** if any meal that day has no calorie value. |
| `calories_range_kcal` | Sum of each meal's portion-based range, rounded to 10. Null if any meal lacks one. |
| Macros | Sum, rounded to 0.1 g. Null if any meal lacks that macro. |
| `complete` | False if any food that day was unmatched or excluded, or any value is null. |
| `estimated` | Always `true`. |
| `idempotency_key` | SHA-256 of the record's other fields. A resend of the same day with the same data has the same key; a corrected day has a new key and replaces the old record. |

Unknown fields are **not allowed**, in either direction. Adding a field needs a new `schema_version`
and a privacy review (PR-05).

## 4. Responses and error handling

| Response | Meaning | Sender does |
| --- | --- | --- |
| `202 Accepted` (any 2xx) | Received | Done |
| `409 Conflict` | This `batch_id` was already received | Treat as delivered |
| `400` / `422` | Batch breaks the contract | **Do not retry.** Log the batch ID and the plan's error, fix, and send a new batch. |
| `401` / `403` | Token missing, expired or not allowed | **Do not retry.** Refresh the credentials, then resend. |
| `429` / `5xx` / network error | Busy or unavailable | Retry after 1, 2, 4, 8 and 16 minutes (6 attempts in total) with the same `batch_id` |
| Still failing after 6 attempts | | Hold the batch as a dead letter for manual resend, and alert support. Never drop it silently. |

The sender validates every batch against the contract **before** sending, and never sends an invalid one.

## 5. Plan-side expectations

- Validate against `meal-summary.schema.json`, and reject with `422` and a list of problems.
- Upsert records on (`member_ref`, `date`). Newer content replaces older content for the same day.
- When a member withdraws, stop accepting their records and apply PR-11 retention.
- Never use the data for underwriting, premiums, claims or eligibility (privacy §5).

## 6. Test cases the plan can run

The reference implementation's tests (`tests/test_wellness_export.py`) double as contract tests: a
valid batch, every contract break the validator rejects, retry and backoff timing, `409` handling,
no retry on `400`, the dead letter after 6 attempts, and an invalid batch never sent.
