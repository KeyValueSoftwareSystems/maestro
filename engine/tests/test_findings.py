"""Review findings: the engine decides blocking from the findings file, and the author fixes,
contests (once) or escalates each blocking finding."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import findings  # noqa: E402


def finding(fid, severity="blocking", status="open"):
    return {"id": fid, "severity": severity, "status": status, "area": "scale",
            "finding": f"{fid} problem", "evidence": "hld.md#Proposed design"}


class FindingsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="findings-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.f = os.path.join(self.dir, "findings.json")
        self.r = os.path.join(self.dir, "resolutions.json")

    def write(self, path, doc):
        with open(path, "w") as fh:
            fh.write(doc if isinstance(doc, str) else json.dumps(doc))

    def run_cmd(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(findings.main(list(argv)), 0)
        return json.loads(out.getvalue())

    def verdict(self):
        return self.run_cmd("verdict", "--findings", self.f)

    def resolve(self, resolutions=None):
        if resolutions is not None:
            self.write(self.r, {"schema_version": 1, "resolutions": resolutions})
        return self.run_cmd("resolve", "--findings", self.f, "--resolutions", self.r)

    def test_verdict_counts_only_active_blocking_findings(self):
        self.write(self.f, {"findings": [finding("F1", status="resolved"),
                                         finding("F2", severity="major"),
                                         finding("F3", status="withdrawn")]})
        self.assertEqual((self.verdict()["blocking"], self.verdict()["valid"]), (False, True))
        self.write(self.f, {"findings": [finding("F1"), finding("F2", status="upheld")]})
        result = self.verdict()
        self.assertEqual((result["blocking"], result["blocking_count"]), (True, 2))
        self.assertIn("F1 (scale)", result["summary"])

    def test_malformed_findings_are_not_valid(self):
        self.write(self.f, "not json")
        self.assertEqual(self.verdict()["valid"], False)
        self.write(self.f, {"findings": [{"id": "F1", "severity": "fatal"}]})
        result = self.verdict()
        self.assertFalse(result["valid"])
        self.assertIn("severity must be one of", result["summary"])
        os.remove(self.f)
        self.assertFalse(self.verdict()["valid"])

    def test_fix_and_contest_go_to_re_review(self):
        self.write(self.f, {"findings": [finding("F1"), finding("F2"), finding("F3", "minor")]})
        result = self.resolve([{"id": "F1", "resolution": "fixed", "note": "added a queue"},
                               {"id": "F2", "resolution": "contested", "note": "PRD says 10 rps"}])
        self.assertEqual((result["state"], result["fixed_csv"], result["contested_csv"]),
                         ("proceed", "F1", "F2"))

    def test_missing_resolution_sends_it_back(self):
        self.write(self.f, {"findings": [finding("F1"), finding("F2")]})
        result = self.resolve([{"id": "F1", "resolution": "fixed", "note": "done"}])
        self.assertEqual((result["state"], result["missing_csv"]), ("incomplete", "F2"))
        os.remove(self.r)
        self.assertEqual(self.resolve()["state"], "incomplete")

    def test_escalation_and_a_second_contest_go_to_a_person(self):
        self.write(self.f, {"findings": [finding("F1"), finding("F2", status="upheld")]})
        result = self.resolve([{"id": "F1", "resolution": "escalated", "note": "needs a budget call"},
                               {"id": "F2", "resolution": "fixed", "note": "done"}])
        self.assertEqual((result["state"], result["escalated_csv"]), ("escalate", "F1"))
        self.assertIn("needs a budget call", result["summary"])
        result = self.resolve([{"id": "F1", "resolution": "fixed", "note": "done"},
                               {"id": "F2", "resolution": "contested", "note": "still wrong"}])
        self.assertEqual((result["state"], result["escalated_csv"]), ("escalate", "F2"))
        self.assertIn("contest already rejected", result["summary"])

    def test_answers_from_an_earlier_round_do_not_count(self):
        # round 1 answered F1; the re-review keeps it open and is written after those answers
        self.write(self.f, {"findings": [finding("F1")]})
        self.resolve([{"id": "F1", "resolution": "fixed", "note": "done"}])
        self.write(self.f, {"findings": [finding("F1")]})
        old = os.stat(self.f).st_mtime_ns - 1_000_000_000
        os.utime(self.r, ns=(old, old))
        result = self.run_cmd("resolve", "--findings", self.f, "--resolutions", self.r)
        self.assertEqual((result["state"], result["missing_csv"]), ("incomplete", "F1"))

    def test_nothing_blocking_proceeds(self):
        self.write(self.f, {"findings": [finding("F1", status="resolved")]})
        self.assertEqual(self.resolve()["state"], "proceed")


if __name__ == "__main__":
    unittest.main()
