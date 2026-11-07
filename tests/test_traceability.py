"""Pilot UAT traceability: every requirement is tested, and every named test exists."""
import importlib
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))      # works under run_offline.py and python -m unittest alike
DOCS = ROOT / "docs"
PLAN = (DOCS / "pilot-uat-plan.md").read_text(encoding="utf-8")


def requirement_ids():
    ids = set(re.findall(r"^\| (PR-\d\d) \|", (DOCS / "privacy-and-consent.md").read_text(encoding="utf-8"), re.M))
    ids |= set(re.findall(r"^\| (IN-\d\d) \|", (DOCS / "integration-spec.md").read_text(encoding="utf-8"), re.M))
    ids |= set(re.findall(r"^\| (AC-\d\d) \|", PLAN, re.M))
    return ids


def cases():
    rows = re.findall(r"^\| (UAT-\d\d) \| ([^|]+) \| [^|]+ \| [^|]+ \| ([^|]+) \| ([^|]+) \|$", PLAN, re.M)
    return [{"id": c, "reqs": re.findall(r"(?:PR|IN|AC)-\d\d", r), "test": t.strip().strip("`"), "result": res.strip()}
            for c, r, t, res in rows]


class TraceabilityTests(unittest.TestCase):
    def test_documents_parse(self):
        self.assertEqual(len(requirement_ids()), 12 + 7 + 5)
        self.assertEqual(len(cases()), 31)

    def test_every_requirement_has_a_case(self):
        self.assertEqual(requirement_ids() - {r for c in cases() for r in c["reqs"]}, set())

    def test_cases_only_name_real_requirements(self):
        self.assertEqual({r for c in cases() for r in c["reqs"]} - requirement_ids(), set())

    def test_every_named_test_exists(self):
        for c in cases():
            ref = c["test"]
            with self.subTest(case=c["id"]):
                if ref.startswith("Manual"):
                    continue
                if ref.startswith("node --test "):
                    self.assertTrue((ROOT / ref.split()[-1]).exists())
                    continue
                module, cls, method = ref.split(".")
                test_class = getattr(importlib.import_module(module), cls)
                self.assertTrue(callable(getattr(test_class, method, None)), f"{ref} not found")

    def test_every_automated_case_is_passing_and_only_manual_ones_are_open(self):
        for c in cases():
            with self.subTest(case=c["id"]):
                if c["test"].startswith("Manual"):
                    self.assertIn(c["result"], ("Pass", "Not yet run"))
                else:
                    self.assertEqual(c["result"], "Pass")


if __name__ == "__main__":
    unittest.main()
