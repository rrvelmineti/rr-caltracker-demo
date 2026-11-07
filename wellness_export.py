"""Daily nutrition summaries for a health insurer's member wellness platform: consented, minimised, retried safely.

Reference implementation of docs/integration-spec.md. It reads a member's diary in the format the app
keeps in browser storage (`rr-caltracker:diary:v1`), checks the member's consent, and builds one
summary record per day with only the fields the insurer needs. Photos, food names, free text, times of
day and micronutrients never leave the member's device.

    python wellness_export.py diary.json --member-id M-1001 --consent consent.json --out batch.json
    python wellness_export.py diary.json --member-id M-1001 --consent consent.json --send https://partner.example/v1/meal-summaries

The member ID is never sent. It is replaced by an HMAC of the ID under a secret shared with the insurer
(WELLNESS_SHARED_SECRET), so only the insurer, who holds the ID-to-member link, can match records.
"""
import argparse
import hashlib
import hmac
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"
CONSENT_VERSION = "2026-11"          # the consent text members agreed to; a new version needs new consent
CONSENT_SCOPE = "daily_nutrition_summary"
PARTNER = "rr-caltracker"
MEAL_TYPES = ("Breakfast", "Lunch", "Dinner", "Snack")
MACROS = {"Protein": "protein_g", "Carbs": "carbs_g", "Fat": "fat_g", "Fiber": "fiber_g"}
MAX_RECORDS = 500
RETRY_DELAYS = (60, 120, 240, 480, 960)   # seconds; five retries after the first attempt
RECORD_FIELDS = ("member_ref", "date", "meals_logged", "meal_types", "calories_kcal", "calories_range_kcal",
                 "protein_g", "carbs_g", "fat_g", "fiber_g", "complete", "estimated", "consent_version",
                 "idempotency_key")


class ConsentError(ValueError):
    """The member has not given valid, current consent. Nothing is exported."""


class DeliveryError(RuntimeError):
    def __init__(self, message, status=None, retryable=False, attempts=1):
        super().__init__(message)
        self.status, self.retryable, self.attempts = status, retryable, attempts


def check_consent(consent, member_id, today):
    """Return the consent version if this member may share today; otherwise raise ConsentError."""
    if not isinstance(consent, dict):
        raise ConsentError("No consent record.")
    if consent.get("member_id") != member_id:
        raise ConsentError("The consent record is for a different member.")
    if consent.get("granted") is not True:
        raise ConsentError("The member has not granted consent.")
    if CONSENT_SCOPE not in (consent.get("scope") or []):
        raise ConsentError(f"Consent does not cover {CONSENT_SCOPE}.")
    if consent.get("version") != CONSENT_VERSION:
        raise ConsentError(f"Consent was given to version {consent.get('version')!r}; the current version is "
                           f"{CONSENT_VERSION}. Ask the member to review and consent again.")
    try:
        granted = datetime.fromisoformat(str(consent.get("granted_at"))).date()
    except ValueError:
        raise ConsentError("The consent record has no valid granted_at date.") from None
    if granted > today:
        raise ConsentError("Consent is dated in the future.")
    withdrawn = consent.get("withdrawn_at")
    if withdrawn:
        try:
            if datetime.fromisoformat(str(withdrawn)).date() <= today:
                raise ConsentError("The member withdrew consent. Nothing is shared from that date on.")
        except ValueError:
            raise ConsentError("The consent record has an unreadable withdrawn_at date; treating as withdrawn.") from None
    return CONSENT_VERSION, granted


def member_ref(member_id, secret):
    if not secret or len(secret) < 32:
        raise ValueError("WELLNESS_SHARED_SECRET must be set and at least 32 characters.")
    return hmac.new(secret.encode(), member_id.encode(), hashlib.sha256).hexdigest()


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


def daily_records(diary, member_id, secret, consent, today=None):
    """One minimised record per day from consent onward. Raises ConsentError if sharing is not allowed."""
    today = today or date.today()
    version, granted = check_consent(consent, member_id, today)
    if not isinstance(diary, dict) or diary.get("version") != 1 or not isinstance(diary.get("meals"), list):
        raise ValueError("Not a diary file from this app (expected version 1 with a meals list).")
    if not diary.get("enabled"):
        return []                                    # history switched off: nothing was kept, nothing to send
    ref = member_ref(member_id, secret)
    days = {}
    for m in diary["meals"]:
        try:
            day = date.fromisoformat(m["date"])
            snap = m["snapshot"]
        except (KeyError, TypeError, ValueError):
            continue                                 # unreadable entries are skipped, never guessed
        if day < granted or day > today or snap.get("demo") or m.get("category") not in MEAL_TYPES:
            continue                                 # nothing from before consent, the future, or the demo meal
        days.setdefault(day, []).append(m)
    records = []
    for day in sorted(days):
        meals = days[day]
        totals = [m["snapshot"].get("totals") or {} for m in meals]
        incomplete = any(m["snapshot"].get("partial") or m["snapshot"].get("excluded_foods") for m in meals)

        def total(name):
            values = [t.get(name) for t in totals]
            return None if any(not _finite(v) for v in values) else sum(values)
        kcal = total("Calories")
        ranges = [m["snapshot"].get("calorie_range") for m in meals]
        rng = None
        if all(isinstance(r, list) and len(r) == 2 and all(_finite(x) for x in r) for r in ranges):
            rng = [round(sum(r[0] for r in ranges), -1), round(sum(r[1] for r in ranges), -1)]
        rec = {
            "member_ref": ref,
            "date": day.isoformat(),
            "meals_logged": len(meals),
            "meal_types": {t: sum(m["category"] == t for m in meals) for t in MEAL_TYPES},
            "calories_kcal": None if kcal is None else round(kcal, -1),
            "calories_range_kcal": rng,
            **{field: (None if (v := total(name)) is None else round(v, 1)) for name, field in MACROS.items()},
            "complete": not incomplete and kcal is not None and all(total(n) is not None for n in MACROS),
            "estimated": True,
            "consent_version": version,
        }
        content = json.dumps({k: rec[k] for k in rec}, sort_keys=True)
        rec["idempotency_key"] = hashlib.sha256(content.encode()).hexdigest()
        records.append(rec)
    return records


def build_batch(records, now=None):
    now = now or datetime.now(timezone.utc)
    if len(records) > MAX_RECORDS:
        raise ValueError(f"At most {MAX_RECORDS} records per batch; split the export.")
    return {"schema_version": SCHEMA_VERSION, "partner": PARTNER, "batch_id": str(uuid.uuid4()),
            "generated_at": now.isoformat(timespec="seconds"), "records": records}


def validate_batch(batch):
    """Every problem in a batch, mirroring docs/meal-summary.schema.json. Empty list means valid."""
    problems = []
    if set(batch) != {"schema_version", "partner", "batch_id", "generated_at", "records"}:
        problems.append(f"batch fields must be exactly schema_version, partner, batch_id, generated_at, records; got {sorted(batch)}")
    if batch.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version must be " + SCHEMA_VERSION)
    recs = batch.get("records")
    if not isinstance(recs, list) or len(recs) > MAX_RECORDS:
        return problems + [f"records must be a list of at most {MAX_RECORDS}"]
    seen = set()
    for i, r in enumerate(recs):
        where = f"records[{i}]"
        if set(r) != set(RECORD_FIELDS):
            extra, missing = set(r) - set(RECORD_FIELDS), set(RECORD_FIELDS) - set(r)
            problems.append(f"{where}: unexpected fields {sorted(extra)}, missing {sorted(missing)}")
            continue
        if not (isinstance(r["member_ref"], str) and len(r["member_ref"]) == 64 and
                all(c in "0123456789abcdef" for c in r["member_ref"])):
            problems.append(f"{where}.member_ref must be 64 lowercase hex characters")
        try:
            date.fromisoformat(r["date"])
        except (TypeError, ValueError):
            problems.append(f"{where}.date must be YYYY-MM-DD")
        if not isinstance(r["meals_logged"], int) or not 1 <= r["meals_logged"] <= 20:
            problems.append(f"{where}.meals_logged must be 1 to 20")
        if set(r["meal_types"] or {}) != set(MEAL_TYPES) or sum(r["meal_types"].values()) != r["meals_logged"]:
            problems.append(f"{where}.meal_types must count every meal type and add up to meals_logged")
        for f in ("calories_kcal", *MACROS.values()):
            if r[f] is not None and not (_finite(r[f]) and r[f] <= 50000):
                problems.append(f"{where}.{f} must be null or a number from 0 to 50000")
        rng = r["calories_range_kcal"]
        if rng is not None and not (isinstance(rng, list) and len(rng) == 2 and all(_finite(x) for x in rng) and rng[0] <= rng[1]):
            problems.append(f"{where}.calories_range_kcal must be null or [low, high]")
        if r["estimated"] is not True or not isinstance(r["complete"], bool):
            problems.append(f"{where}: estimated must be true and complete a boolean")
        if r["consent_version"] != CONSENT_VERSION:
            problems.append(f"{where}.consent_version must be {CONSENT_VERSION}")
        if r["idempotency_key"] in seen:
            problems.append(f"{where}.idempotency_key repeats an earlier record")
        seen.add(r["idempotency_key"])
    return problems


def send_batch(batch, url, token, opener=urllib.request.urlopen, sleep=time.sleep, delays=RETRY_DELAYS):
    """POST a batch. 2xx and 409 (already received) succeed; 400/401/403/422 stop; 429, 5xx and network errors retry."""
    problems = validate_batch(batch)
    if problems:
        raise DeliveryError("Batch failed validation; not sent: " + "; ".join(problems[:5]))
    body = json.dumps(batch).encode()
    attempts = 0
    for delay in (0, *delays):
        if delay:
            sleep(delay)
        attempts += 1
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {token}",
            "Idempotency-Key": batch["batch_id"]})
        try:
            with opener(req, timeout=30) as resp:
                return {"status": resp.status, "attempts": attempts}
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                return {"status": 409, "attempts": attempts, "note": "already received"}
            if exc.code == 429 or exc.code >= 500:
                last = DeliveryError(f"Partner returned HTTP {exc.code}", exc.code, True, attempts)
                continue
            raise DeliveryError(f"Partner rejected the batch with HTTP {exc.code}; not retried. Check the batch "
                                "and credentials.", exc.code, False, attempts) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = DeliveryError(f"Could not reach the partner: {getattr(exc, 'reason', exc)}", None, True, attempts)
            continue
    last.attempts = attempts
    raise DeliveryError(f"{last} after {attempts} attempts. Hold the batch for manual resend (dead letter).",
                        last.status, True, attempts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("diary", type=Path, help="diary JSON in the app's browser-storage format")
    parser.add_argument("--member-id", required=True)
    parser.add_argument("--consent", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--send", metavar="URL")
    parser.add_argument("--today", type=date.fromisoformat, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    secret = os.environ.get("WELLNESS_SHARED_SECRET", "")
    try:
        records = daily_records(json.loads(args.diary.read_text(encoding="utf-8")), args.member_id, secret,
                                json.loads(args.consent.read_text(encoding="utf-8")), args.today)
    except ConsentError as exc:
        print(f"Not shared: {exc}")
        return 3
    except ValueError as exc:
        print(exc)
        return 1
    batch = build_batch(records)
    problems = validate_batch(batch)
    if problems:
        print("Batch is invalid:\n  " + "\n  ".join(problems))
        return 1
    if args.out:
        args.out.write_text(json.dumps(batch, indent=2) + "\n", encoding="utf-8")
    print(f"{len(records)} daily record(s) for member_ref {records[0]['member_ref'][:12]}..." if records
          else "No days to share.")
    if args.send and records:
        try:
            result = send_batch(batch, args.send, os.environ.get("WELLNESS_PARTNER_TOKEN", ""))
        except DeliveryError as exc:
            print(exc)
            return 2
        print(f"Delivered: HTTP {result['status']} after {result['attempts']} attempt(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
