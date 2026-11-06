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

    def test_a_valid_code_review_verdict_records_the_reviewed_commit(self):
        self.write(self.f, {"schema_version": 1, "findings": [finding("F1")]})
        self.run_cmd("verdict", "--findings", self.f, "--commit", "abc123")
        with open(os.path.join(self.dir, "reviewed.json")) as fh:
            record = json.load(fh)
        self.assertEqual((record["commit"], record["blocking"]), ("abc123", True))
        os.remove(os.path.join(self.dir, "reviewed.json"))
        self.write(self.f, "not json")  # a malformed review records nothing
        self.run_cmd("verdict", "--findings", self.f, "--commit", "abc123")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "reviewed.json")))

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


class RoundLimitTest(FindingsTest):
    """The engine bounds re-review loops: a round limit, and late findings go to the person."""

    def verdict_round(self, round_no, max_rounds=None, previous=True):
        argv = ["verdict", "--findings", self.f, "--round", str(round_no), "--root", self.dir]
        if previous:
            argv += ["--previous", os.path.join(self.dir, "previous.json")]
        if max_rounds:
            argv += ["--max-rounds", str(max_rounds)]
        return self.run_cmd(*argv)

    def test_new_blocking_finding_on_a_re_review_is_late_unless_the_revision_caused_it(self):
        self.write(os.path.join(self.dir, "previous.json"), {"findings": [finding("F1")]})
        caused = {**finding("F3"), "introduced_by_revision": True}
        self.write(self.f, {"findings": [finding("F1", status="resolved"), finding("F2"), caused]})
        result = self.verdict_round(2)
        self.assertEqual((result["blocking_count"], result["late"], result["late_csv"]),
                         (1, True, "F2"))
        self.assertTrue(result["revise"])  # F3 is the revision's own regression
        self.write(self.f, {"findings": [finding("F1", status="resolved"), finding("F2")]})
        result = self.verdict_round(2)
        self.assertEqual((result["blocking"], result["revise"], result["late"]), (False, False, True))
        self.assertIn("late blocking finding", result["summary"])

    def test_the_first_round_is_never_late(self):
        # a findings file left by an earlier pass is not this stage entry's earlier round
        self.write(os.path.join(self.dir, "previous.json"), {"findings": [finding("F1")]})
        self.write(self.f, {"findings": [finding("F9")]})
        result = self.verdict_round(1)
        self.assertEqual((result["late"], result["revise"]), (False, True))

    def test_round_limit_hands_remaining_findings_to_the_person(self):
        self.write(self.f, {"findings": [finding("F1")]})
        self.assertTrue(self.verdict_round(2, previous=False)["revise"])
        result = self.verdict_round(3, previous=False)
        self.assertEqual((result["blocking"], result["limit_reached"], result["revise"]),
                         (True, True, False))
        self.assertIn("round limit reached (3/3)", result["summary"])
        self.assertTrue(self.verdict_round(3, max_rounds=5, previous=False)["revise"])

    def test_round_limit_reads_the_project_config(self):
        self.write(os.path.join(self.dir, "maestro.config.yaml"),
                   "version: 1\nrepos: {}\nreviews:\n  max_rounds: 1\n")
        self.write(self.f, {"findings": [finding("F1")]})
        result = self.verdict_round(1, previous=False)
        self.assertEqual((result["max_rounds"], result["revise"]), (1, False))

    def test_introduced_by_revision_must_be_a_boolean(self):
        self.write(self.f, {"findings": [{**finding("F1"), "introduced_by_revision": "yes"}]})
        self.assertFalse(self.verdict_round(2)["valid"])


if __name__ == "__main__":
    unittest.main()
