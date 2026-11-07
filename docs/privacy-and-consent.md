# Privacy and consent requirements

**For:** the health plan's privacy and compliance team.
**Context:** a health insurer offers photo meal logging to members as an optional wellness benefit.
Members who opt in can share **daily nutrition totals** with the plan's wellness platform. The insurer
is a hypothetical client; the data flows below are the app's real behaviour, checked against the code.

This document states requirements and how the app meets them. It is not legal advice. The plan's
privacy counsel should confirm which laws apply, in particular whether HIPAA applies to the data the
app sends on the plan's behalf, which would make the app's operator a business associate needing a
business associate agreement.

## 1. Data inventory: what leaves the member's device

| Data | Where it goes | Why | Kept by the app? |
| --- | --- | --- | --- |
| Meal photos (resized, re-encoded as JPEG; EXIF and GPS metadata removed) | Google Gemini API | Identify foods and estimate portions | No. In memory for the current session only, never stored. |
| Optional meal description typed by the member | Google Gemini API | Context for identification | No |
| Food search terms, such as "grilled salmon" | USDA FoodData Central API | Nutrition values | No |
| Meal diary: foods, grams, nutrients, meal type, date | **Stays in the member's browser** (local storage) | History and daily totals | Opt-in, 1, 7 or 14 days, deleted automatically after that |
| **Daily nutrition summary** (see §3) | The plan's wellness platform | The wellness benefit | Only if the member consents |

The app has no server database and no user accounts. The FoodCNN portion model runs on the app's own
server, and its photos go nowhere else.

## 2. Requirements

| ID | Requirement | How it is met | Verified by |
| --- | --- | --- | --- |
| PR-01 | Sharing with the plan is opt-in. Nothing is shared without a current, specific consent record. | `check_consent` requires `granted: true`, the scope `daily_nutrition_summary`, the member's own ID and the current consent version (`2026-11`). Otherwise the export stops and sends nothing. | UAT-01, UAT-02 |
| PR-02 | A member can withdraw consent at any time, and nothing is shared from that date on. | `withdrawn_at` on or before today stops the export. An unreadable withdrawal date counts as withdrawn. | UAT-02, UAT-03 |
| PR-03 | Nothing recorded before consent is shared. | Meals dated before `granted_at` are left out. | UAT-04 |
| PR-04 | A changed consent text needs fresh consent. | A consent version other than the current one stops the export. | UAT-02 |
| PR-05 | Data minimisation: the summary carries only what the wellness benefit needs. | One record per day: number of meals, meal types, calories and its range, protein, carbs, fat, fiber, and completeness flags. No photos, food names, descriptions, micronutrients, times of day or device data. | UAT-05, UAT-06 |
| PR-06 | The member's ID is never sent. | It is replaced with an HMAC-SHA256 under a secret shared with the plan, at least 32 characters, so only the plan can link a record to a member. | UAT-06, UAT-07 |
| PR-07 | Estimates are never presented as measurements. | Every record has `estimated: true`. Days with a missing value are `complete: false`, with the value left null rather than guessed. | UAT-09, UAT-10 |
| PR-08 | Photos are not stored, and their metadata is removed before any AI call. | Photos are re-encoded without EXIF and held in the session only. The diary allowlist excludes image bytes. | Existing tests `test_app`, `test_history` |
| PR-09 | Diary retention is limited and member-controlled. | History is off by default. When on, the member chooses 1, 7 or 14 days, older entries are deleted automatically, and the member can clear it at any time. | Existing tests `test_browser_history.mjs` |
| PR-10 | Demo or test data never reaches the plan. | The built-in sample meal is excluded from exports. | UAT-08 |
| PR-11 | The plan keeps summaries only as long as the benefit needs them. | **Plan-side requirement:** recommended at most 13 months, deleted on withdrawal on request, in line with the plan's records policy. | Plan's sign-off |
| PR-12 | AI providers do not train on member data. | **Operator requirement:** use Gemini under paid-tier or enterprise terms that exclude training on prompts, and record the terms version in the vendor file. Confirm before go-live. | Go-live checklist |

## 3. The shared record, field by field

| Field | Purpose | Why it is needed |
| --- | --- | --- |
| `member_ref` | Pseudonymous link to the member | The plan matches the record to its member list |
| `date` | Local date, no time | Daily engagement and trends |
| `meals_logged`, `meal_types` | Count of meals by type | Engagement measures, such as "logged breakfast 5 days this week" |
| `calories_kcal`, `calories_range_kcal` | Day's estimated energy, rounded to 10 kcal, with its portion range | Wellness coaching; the range shows the uncertainty |
| `protein_g`, `carbs_g`, `fat_g`, `fiber_g` | Macronutrients | Coaching goals |
| `complete`, `estimated` | Quality flags | Stop the plan treating partial or estimated data as exact |
| `consent_version` | The consent this record was shared under | Audit |
| `idempotency_key` | Content hash | Prevents duplicate records when a batch is resent |

## 4. Member rights

- **See:** the member sees every meal and daily total in the app before anything is shared.
- **Withdraw:** withdrawal in the plan's consent service stops all further sharing, starting with the
  next export.
- **Delete:** clearing app history deletes the diary on the device. Deleting summaries already shared is
  done by the plan (PR-11).

## 5. Must not be used for

The plan must not use these summaries for underwriting, premiums, claims decisions or eligibility.
The data is an AI estimate from photos and is unsuitable for those purposes. This restriction belongs
in the consent text and in the data-sharing agreement.

## 6. Sign-off

| Role | Name | Date |
| --- | --- | --- |
| Plan privacy officer | | |
| Plan compliance | | |
| App operator | | |
