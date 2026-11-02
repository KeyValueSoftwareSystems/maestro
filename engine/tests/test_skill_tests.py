"""Skill behaviour tests: shipped cases are well-formed and name real skills, and the checker
passes or fails recorded outputs by their expected and forbidden patterns."""
import glob
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, ".."))
import skill_tests  # noqa: E402

CASES = os.path.join(ROOT, "evals", "skills")


def skill_names():
    names = set()
    for path in glob.glob(os.path.join(ROOT, "skills", "**", "SKILL.md"), recursive=True):
        with open(path, encoding="utf-8") as fh:
            match = re.search(r"^name:\s*(\S+)", fh.read(), re.M)
        if match:
            names.add(match.group(1))
    return names


class ShippedCasesTest(unittest.TestCase):
    def test_every_case_is_well_formed_and_names_a_real_skill(self):
        cases = skill_tests.load_cases(CASES)
        self.assertGreaterEqual(len(cases), 8)
        known = skill_names()
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(skill_tests.problems(case), [])
                self.assertIn(case["skill"], known)


class CheckerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="skill-tests-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.cases = os.path.join(self.dir, "cases", "fix-loop")
        os.makedirs(self.cases)
        with open(os.path.join(self.cases, "x.yaml"), "w") as fh:
            fh.write("skill: fix-loop\nname: no-skip\nprompt: |\n  Fix it.\n"
                     "must_include:\n  - 'tax_rate'\nmust_not_include:\n  - 'unittest\\.skip'\n")
        self.outputs = os.path.join(self.dir, "out")
        os.makedirs(self.outputs)

    def run_check(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = skill_tests.main(["check", "--dir", os.path.join(self.dir, "cases"),
                                     "--outputs", self.outputs])
        return code, json.loads(out.getvalue())

    def record(self, text):
        with open(os.path.join(self.outputs, "fix-loop--no-skip.txt"), "w") as fh:
            fh.write(text)

    def test_missing_output_fails(self):
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("no output recorded", report["results"][0]["failures"][0])

    def test_expected_and_forbidden_patterns(self):
        self.record("Apply order.TAX_RATE in calculate_total.")
        code, report = self.run_check()
        self.assertEqual((code, report["summary"]), (0, "1/1 skill behaviour tests passed"))
        self.record("Mark it with @unittest.skip until later.")
        code, report = self.run_check()
        self.assertEqual(code, 1)
        failures = report["results"][0]["failures"]
        self.assertIn("missing expected: tax_rate", failures)
        self.assertTrue(any(f.startswith("forbidden output: unittest\\.skip") for f in failures))

    def test_list_gives_the_prompts_to_run(self):
        out = io.StringIO()
        with redirect_stdout(out):
            skill_tests.main(["list", "--dir", os.path.join(self.dir, "cases")])
        self.assertEqual(json.loads(out.getvalue()),
                         [{"id": "fix-loop--no-skip", "skill": "fix-loop", "prompt": "Fix it.\n"}])


if __name__ == "__main__":
    unittest.main()
