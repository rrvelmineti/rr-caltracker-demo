"""Insurer integration: consent, data minimisation, the batch contract and delivery retries. Offline."""
import copy
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import wellness_export as wx  # noqa: E402

EXAMPLES = ROOT / "examples" / "wellness"
DIARY = json.loads((EXAMPLES / "diary_sample.json").read_text())
CONSENT = json.loads((EXAMPLES / "consent_sample.json").read_text())
SECRET = "s" * 40
TODAY = date(2026, 11, 5)


def records(diary=DIARY, consent=CONSENT, member="M-1001", today=TODAY, secret=SECRET):
    return wx.daily_records(copy.deepcopy(diary), member, secret, consent, today)


class ConsentTests(unittest.TestCase):
    def test_valid_consent_allows_sharing(self):
        self.assertEqual(len(records()), 3)

    def test_every_invalid_consent_stops_the_export(self):
        cases = {
            "not granted": {**CONSENT, "granted": False},
            "other member": {**CONSENT, "member_id": "M-9999"},
            "wrong scope": {**CONSENT, "scope": ["marketing"]},
            "old version": {**CONSENT, "version": "2025-01"},
            "withdrawn": {**CONSENT, "withdrawn_at": "2026-11-04T10:00:00+00:00"},
            "future": {**CONSENT, "granted_at": "2026-12-01T00:00:00+00:00"},
            "bad date": {**CONSENT, "granted_at": "soon"},
        }
        for name, consent in cases.items():
            with self.subTest(name), self.assertRaises(wx.ConsentError):
                records(consent=consent)
        with self.assertRaises(wx.ConsentError):
            records(consent=None)

    def test_withdrawal_dated_after_today_still_allows_today(self):
        self.assertEqual(len(records(consent={**CONSENT, "withdrawn_at": "2026-11-30T00:00:00+00:00"})), 3)

    def test_nothing_from_before_consent_is_shared(self):
        self.assertNotIn("2026-10-30", {r["date"] for r in records()})


class MinimisationTests(unittest.TestCase):
    def test_records_hold_only_the_agreed_fields(self):
        for r in records():
            self.assertEqual(tuple(r), wx.RECORD_FIELDS)

    def test_no_member_id_food_names_photos_or_times_leave_the_device(self):
        text = json.dumps(wx.build_batch(records()))
        for secret_thing in ("M-1001", "Oatmeal", "Salmon", "Chutney", "inlineData", "savedAt", "1793900000"):
            self.assertNotIn(secret_thing, text)

    def test_member_ref_is_stable_and_depends_on_the_secret(self):
        a, b = records()[0]["member_ref"], records(secret="t" * 40)[0]["member_ref"]
        self.assertEqual(a, records()[0]["member_ref"])
        self.assertNotEqual(a, b)
        with self.assertRaises(ValueError):
            records(secret="short")

    def test_demo_meals_and_future_days_are_never_sent(self):
        dates = {r["date"]: r for r in records()}
        self.assertEqual(dates["2026-11-04"]["meals_logged"], 1)               # the demo meal is excluded
        self.assertEqual(records(today=date(2026, 11, 3))[-1]["date"], "2026-11-03")

    def test_history_switched_off_shares_nothing(self):
        self.assertEqual(records(diary={**DIARY, "enabled": False}), [])


class RecordTests(unittest.TestCase):
    def test_daily_totals_are_summed_and_rounded(self):
        day = {r["date"]: r for r in records()}["2026-11-02"]
        self.assertEqual(day["meals_logged"], 3)
        self.assertEqual(day["meal_types"], {"Breakfast": 1, "Lunch": 1, "Dinner": 1, "Snack": 0})
        self.assertEqual(day["calories_kcal"], 1640)                           # 395 + 512 + 734 = 1641
        self.assertEqual(day["calories_range_kcal"], [1320, 1990])
        self.assertEqual(day["protein_g"], 87.2)
        self.assertTrue(day["complete"] and day["estimated"])

    def test_a_day_with_a_missing_food_is_incomplete_not_guessed(self):
        day = {r["date"]: r for r in records()}["2026-11-03"]
        self.assertIsNone(day["calories_kcal"])
        self.assertIsNone(day["calories_range_kcal"])
        self.assertEqual(day["protein_g"], 46.1)                               # known for both meals
        self.assertFalse(day["complete"])

    def test_idempotency_key_is_stable_and_changes_with_content(self):
        first = records()[0]["idempotency_key"]
        self.assertEqual(first, records()[0]["idempotency_key"])
        changed = copy.deepcopy(DIARY)
        changed["meals"][1]["snapshot"]["totals"]["Calories"] = 500
        self.assertNotEqual(first, records(diary=changed)[0]["idempotency_key"])

    def test_not_a_diary_is_a_clear_error(self):
        with self.assertRaises(ValueError):
            records(diary={"meals": "nope"})


class BatchContractTests(unittest.TestCase):
    def test_a_built_batch_is_valid(self):
        self.assertEqual(wx.validate_batch(wx.build_batch(records())), [])

    def test_validator_catches_contract_breaks(self):
        batch = wx.build_batch(records())
        bad = copy.deepcopy(batch)
        bad["records"][0]["food_names"] = ["Oatmeal"]
        bad["records"][1]["member_ref"] = "M-1001"
        bad["records"][2]["meal_types"]["Snack"] = 5
        text = "\n".join(wx.validate_batch(bad))
        for expected in ("unexpected fields ['food_names']", "member_ref must be 64", "add up to meals_logged"):
            self.assertIn(expected, text)
        resent = copy.deepcopy(batch)
        resent["records"].append(copy.deepcopy(batch["records"][0]))
        self.assertIn("records[3].idempotency_key repeats an earlier record", wx.validate_batch(resent))

    def test_schema_file_matches_the_code(self):
        schema = json.loads((ROOT / "docs" / "meal-summary.schema.json").read_text())
        record = schema["properties"]["records"]["items"]
        self.assertEqual(record["required"], list(wx.RECORD_FIELDS))
        self.assertEqual(set(record["properties"]), set(wx.RECORD_FIELDS))
        self.assertEqual(record["properties"]["consent_version"]["const"], wx.CONSENT_VERSION)
        self.assertEqual(schema["properties"]["records"]["maxItems"], wx.MAX_RECORDS)
        self.assertEqual(schema["properties"]["schema_version"]["const"], wx.SCHEMA_VERSION)


class Response:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_from(*outcomes):
    """Fake urlopen: each outcome is a status code (or an exception to raise)."""
    calls = []

    def opener(req, timeout):
        calls.append(req)
        out = outcomes[len(calls) - 1]
        if isinstance(out, Exception):
            raise out
        if out >= 400:
            raise urllib.error.HTTPError(req.full_url, out, "x", {}, None)
        return Response(out)
    return opener, calls


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.batch = wx.build_batch(records())
        self.slept = []

    def send(self, *outcomes):
        opener, self.calls = opener_from(*outcomes)
        return wx.send_batch(self.batch, "https://partner.example/v1", "tok", opener=opener, sleep=self.slept.append)

    def test_accepted_first_time_with_headers(self):
        self.assertEqual(self.send(202), {"status": 202, "attempts": 1})
        req = self.calls[0]
        self.assertEqual(req.get_header("Idempotency-key"), self.batch["batch_id"])
        self.assertEqual(req.get_header("Authorization"), "Bearer tok")

    def test_busy_or_unreachable_partner_is_retried_with_backoff(self):
        result = self.send(503, 429, urllib.error.URLError("down"), 202)
        self.assertEqual(result["attempts"], 4)
        self.assertEqual(self.slept, [60, 120, 240])

    def test_already_received_counts_as_delivered(self):
        self.assertEqual(self.send(500, 409)["status"], 409)

    def test_rejected_batch_is_not_retried(self):
        with self.assertRaises(wx.DeliveryError) as ctx:
            self.send(400)
        self.assertEqual((ctx.exception.status, ctx.exception.retryable, ctx.exception.attempts), (400, False, 1))
        self.assertEqual(self.slept, [])

    def test_gives_up_after_six_attempts_for_manual_resend(self):
        with self.assertRaises(wx.DeliveryError) as ctx:
            self.send(*[503] * 6)
        self.assertEqual(ctx.exception.attempts, 6)
        self.assertIn("dead letter", str(ctx.exception))
        self.assertEqual(self.slept, list(wx.RETRY_DELAYS))

    def test_an_invalid_batch_is_never_sent(self):
        self.batch["records"][0]["food_names"] = ["x"]
        with self.assertRaises(wx.DeliveryError):
            self.send(202)
        self.assertEqual(self.calls, [])


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *extra, consent=EXAMPLES / "consent_sample.json"):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "batch.json"
            with patch.dict("os.environ", {"WELLNESS_SHARED_SECRET": SECRET}), redirect_stdout(io.StringIO()) as s:
                code = wx.main([str(EXAMPLES / "diary_sample.json"), "--member-id", "M-1001", "--consent", str(consent),
                                "--out", str(out), "--today", "2026-11-05", *extra])
            return code, s.getvalue(), json.loads(out.read_text()) if out.exists() else None

    def test_writes_a_valid_batch(self):
        code, _, batch = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(len(batch["records"]), 3)
        self.assertEqual(wx.validate_batch(batch), [])

    def test_no_consent_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c.json"
            p.write_text(json.dumps({**CONSENT, "granted": False}))
            code, out, batch = self.run_cli(consent=p)
        self.assertEqual((code, batch), (3, None))
        self.assertIn("Not shared", out)


if __name__ == "__main__":
    unittest.main()
