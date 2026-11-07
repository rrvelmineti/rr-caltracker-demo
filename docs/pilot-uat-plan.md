# Pilot UAT plan: member wellness benefit

User acceptance testing for the health plan's pilot. It covers three sets of requirements: the
[privacy and consent requirements](privacy-and-consent.md) (PR), the
[integration spec](integration-spec.md) (IN), and the accuracy criteria below (AC), which come from the
[vendor evaluation playbook](vendor-evaluation-playbook.md). Every case names the automated test that
repeats it. `tests/test_traceability.py` fails if a requirement has no case, or if a case names a test
that doesn't exist.

## Accuracy criteria

Agreed with the plan before any meal is scored, and checked by `evaluation/acceptance.py`.

| ID | Criterion | Blocking |
| --- | --- | --- |
| AC-01 | At least 20 meals scored; fewer means NOT READY | Yes |
| AC-02 | Median calorie error at most 20% | Yes |
| AC-03 | At least half of meals within 20% of the true calories | Yes |
| AC-04 | The weight model is never accepted on Nutrition5k results, because it was trained on them | Yes |
| AC-05 | Bias (average over- or under-estimate) reported, within ±10% | No |

## Pilot setup

- 10 volunteer members, 2 weeks, real meals. 5 of them also weigh their meals, for the accuracy test.
- Plan staging endpoint and test credentials; a test member list with consent records.
- Exit: every blocking case passes, the accuracy decision is ACCEPT for at least one portion mode, and
  the plan's privacy officer signs [privacy-and-consent.md](privacy-and-consent.md).

## Cases

| Case | Requirements | What the tester does | Expected result | Automated test | Result |
| --- | --- | --- | --- | --- | --- |
| UAT-01 | PR-01 | Export a member's diary with valid consent | 3 daily records for the sample diary | `test_wellness_export.ConsentTests.test_valid_consent_allows_sharing` | Pass |
| UAT-02 | PR-01, PR-02, PR-04 | Export with consent not granted, another member's, wrong scope, old version, withdrawn, future-dated, missing | Nothing exported; reason given each time | `test_wellness_export.ConsentTests.test_every_invalid_consent_stops_the_export` | Pass |
| UAT-03 | PR-02 | Withdrawal dated after today | Today still shared | `test_wellness_export.ConsentTests.test_withdrawal_dated_after_today_still_allows_today` | Pass |
| UAT-04 | PR-03 | Diary holds a meal from before consent | Not shared | `test_wellness_export.ConsentTests.test_nothing_from_before_consent_is_shared` | Pass |
| UAT-05 | PR-05, IN-01 | Inspect every record | Exactly the agreed fields | `test_wellness_export.MinimisationTests.test_records_hold_only_the_agreed_fields` | Pass |
| UAT-06 | PR-05, PR-06 | Search the batch for the member ID, food names, photos and timestamps | None found | `test_wellness_export.MinimisationTests.test_no_member_id_food_names_photos_or_times_leave_the_device` | Pass |
| UAT-07 | PR-06 | Export twice, then with another secret, then with a short secret | Same reference; different reference; refused | `test_wellness_export.MinimisationTests.test_member_ref_is_stable_and_depends_on_the_secret` | Pass |
| UAT-08 | PR-10 | Diary holds the demo meal and a future day | Neither shared | `test_wellness_export.MinimisationTests.test_demo_meals_and_future_days_are_never_sent` | Pass |
| UAT-09 | PR-07, IN-02 | Check a full day's totals | Summed, rounded, complete, marked as an estimate | `test_wellness_export.RecordTests.test_daily_totals_are_summed_and_rounded` | Pass |
| UAT-10 | PR-07, IN-02 | A day where one food was not matched | Calories null, day incomplete; known macros still summed | `test_wellness_export.RecordTests.test_a_day_with_a_missing_food_is_incomplete_not_guessed` | Pass |
| UAT-11 | PR-08 | Prepare a photo carrying GPS and camera metadata | All metadata removed; photo resized | `test_privacy.PhotoPrivacyTests.test_location_and_camera_metadata_are_removed_before_any_ai_call` | Pass |
| UAT-12 | PR-08 | Save a meal to history | Image bytes, keys and free-text notes are not stored | `test_history.BrowserBoundaryChecks.test_allowlist_removes_images_keys_and_freeform_notes` | Pass |
| UAT-13 | PR-09 | Shorten history to 1 or 7 days; clear it | Older meals deleted; clearing removes everything | `node --test tests/test_browser_history.mjs` | Pass |
| UAT-14 | PR-09 | History switched off | Nothing kept, nothing shared | `test_wellness_export.MinimisationTests.test_history_switched_off_shares_nothing` | Pass |
| UAT-15 | IN-03 | Resend the same day; change a meal and resend | Same key; new key | `test_wellness_export.RecordTests.test_idempotency_key_is_stable_and_changes_with_content` | Pass |
| UAT-16 | IN-01 | Validate a built batch, then a broken one | Valid; every break listed | `test_wellness_export.BatchContractTests.test_validator_catches_contract_breaks` | Pass |
| UAT-17 | IN-07 | Compare the schema file with the code | Same fields, versions and limits | `test_wellness_export.BatchContractTests.test_schema_file_matches_the_code` | Pass |
| UAT-18 | IN-04 | Partner answers 503, 429, then is unreachable, then accepts | Delivered on attempt 4 after 1, 2 and 4 minutes | `test_wellness_export.DeliveryTests.test_busy_or_unreachable_partner_is_retried_with_backoff` | Pass |
| UAT-19 | IN-04 | Partner is down for every attempt | Gives up after 6 attempts; dead letter | `test_wellness_export.DeliveryTests.test_gives_up_after_six_attempts_for_manual_resend` | Pass |
| UAT-20 | IN-03 | Partner says 409 (already received) | Treated as delivered | `test_wellness_export.DeliveryTests.test_already_received_counts_as_delivered` | Pass |
| UAT-21 | IN-05 | Partner rejects with 400 | No retry | `test_wellness_export.DeliveryTests.test_rejected_batch_is_not_retried` | Pass |
| UAT-22 | IN-06 | Try to send a batch with an extra field | Never sent | `test_wellness_export.DeliveryTests.test_an_invalid_batch_is_never_sent` | Pass |
| UAT-23 | IN-04 | Send a real batch to the plan's staging endpoint | 202; record visible in the plan's test console | Manual: needs the plan's staging endpoint | Not yet run |
| UAT-24 | AC-02, AC-03 | Acceptance check on a good run | ACCEPT | `test_acceptance.AcceptanceTests.test_a_good_run_is_accepted` | Pass |
| UAT-25 | AC-02 | Median error 27.5% | REJECT | `test_acceptance.AcceptanceTests.test_high_median_error_is_rejected` | Pass |
| UAT-26 | AC-03 | Only 42% of meals within 20% | REJECT | `test_acceptance.AcceptanceTests.test_too_few_meals_in_the_20_percent_band_is_rejected` | Pass |
| UAT-27 | AC-01 | Only 12 meals scored | NOT READY | `test_acceptance.AcceptanceTests.test_too_few_meals_is_not_ready` | Pass |
| UAT-28 | AC-04 | Weight model scored on Nutrition5k | Never accepted | `test_acceptance.AcceptanceTests.test_hybrid_on_nutrition5k_is_never_accepted` | Pass |
| UAT-29 | AC-05 | Run with an 18% over-estimate | Reported as failing bias; does not block | `test_acceptance.AcceptanceTests.test_bias_is_reported_but_does_not_block` | Pass |
| UAT-30 | AC-01, AC-02, AC-03 | Benchmark the 5 weighing members' meals, then run `evaluation/acceptance.py` | ACCEPT for at least one portion mode | Manual: needs pilot meals and API keys | Not yet run |
| UAT-31 | PR-11, PR-12 | Plan confirms summary retention; operator confirms Gemini terms exclude training | Both recorded in the go-live checklist | Manual: plan and operator sign-off | Not yet run |

## Sign-off

| Role | Name | Date |
| --- | --- | --- |
| Plan wellness product owner | | |
| Plan privacy officer | | |
| App operator | | |
