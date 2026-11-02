"""ac_trace: PRD criteria -> test cases (design check) -> QA results (delivery trace)."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ac_trace  # noqa: E402

PRD = """# Export — PRD

## Acceptance criteria

- AC-01: Admins export the filtered report.
- AC-02: Exports over the row limit are refused with a reason.
- AC-03: The export lists the applied filters.

## Dependencies and risks

AC-09 is mentioned here but is not a criterion.
"""

CASES = """# Export test cases

| Criterion | Cases |
|---|---|
| AC-03 | TC-x-003 |

## Journey: export

### TC-x-001 — Export the filtered report

- **Traces:** AC-01
#### Steps
1. Export.

### TC-x-002 — Over the limit

- **Traces:** AC-02, AC-01

## Journey: limits

### TC-x-003 — Filters listed

Covers AC-03.

## Out of scope

Load testing (AC-03 under load) is excluded.
"""


class AcTraceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ac-trace-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.prd = self.write("prd.md", PRD)
        self.cases = self.write("test-cases.md", CASES)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def run_cmd(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(ac_trace.main(list(argv)), 0)
        return json.loads(out.getvalue())

    def design(self):
        return self.run_cmd("design", "--prd", self.prd, "--test-cases", self.cases)

    def qa(self, cases):
        results = self.write("results.json", json.dumps({"schema_version": 1, "cases": cases}))
        return self.run_cmd("qa", "--prd", self.prd, "--test-cases", self.cases,
                            "--results", results, "--out", os.path.join(self.dir, "ac-trace.md"))

    def test_parses_criteria_and_case_blocks_only(self):
        self.assertEqual(ac_trace.prd_criteria(self.prd), ["AC-01", "AC-02", "AC-03"])
        # the coverage matrix and closing sections prove nothing; journeys don't end the catalog
        self.assertEqual(ac_trace.test_cases(self.cases), {
            "TC-x-001": ["AC-01"], "TC-x-002": ["AC-02", "AC-01"], "TC-x-003": ["AC-03"]})
        result = self.design()
        self.assertTrue(result["valid"], result)
        self.assertEqual((result["ac_count"], result["case_count"]), (3, 3))

    def test_uncovered_and_unknown_criteria_fail(self):
        self.write("test-cases.md", CASES.replace("Covers AC-03.", "Covers AC-04."))
        result = self.design()
        self.assertFalse(result["valid"])
        self.assertEqual((result["uncovered_csv"], result["unknown_csv"]), ("AC-03", "AC-04"))
        self.write("test-cases.md", "| AC-01 | TC-x-001 |\n")
        self.assertIn("no cases", self.design()["issues_summary"])
        self.write("prd.md", "# PRD\n")
        self.assertIn("no AC-xx", self.design()["issues_summary"])

    def test_qa_verdicts_per_criterion(self):
        result = self.qa([{"id": "TC-x-001", "status": "passed"},
                          {"id": "TC-x-002", "status": "failed", "note": "no reason shown"},
                          {"id": "TC-x-003", "status": "skipped", "note": "needs staging"}])
        self.assertFalse(result["all_passed"])
        self.assertEqual((result["passing"], result["failing"], result["not_run"]), (0, 2, 1))
        self.assertEqual(result["summary"], "0/3 acceptance criteria passing — AC-01 failing, "
                                            "AC-02 failing, AC-03 not run")
        with open(result["path"]) as fh:
            table = fh.read()
        self.assertIn("| AC-03 | TC-x-003 (skipped) | not run |", table)
        self.assertIn("- TC-x-002: no reason shown", table)

    def test_all_passing_and_missing_results(self):
        result = self.qa([{"id": c, "status": "passed"} for c in ("TC-x-001", "TC-x-002", "TC-x-003")])
        self.assertTrue(result["all_passed"])
        self.assertEqual(result["summary"], "3/3 acceptance criteria passing")
        result = self.run_cmd("qa", "--prd", self.prd, "--test-cases", self.cases, "--results",
                              os.path.join(self.dir, "missing.json"),
                              "--out", os.path.join(self.dir, "ac-trace.md"))
        self.assertEqual((result["all_passed"], result["not_run"]), (False, 3))
        self.write("results.json", "[1, 2]")
        self.assertEqual(ac_trace.qa_results(os.path.join(self.dir, "results.json")), {})


if __name__ == "__main__":
    unittest.main()
