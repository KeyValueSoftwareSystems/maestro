"""The evaluation set: every case builds a runnable workspace, and a finished run is scored
against the case's expectations, with regressions flagged against a baseline."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import eval_score  # noqa: E402
import eval_setup  # noqa: E402
import project_config  # noqa: E402
import test_sdlc_e2e as e2e  # noqa: E402

CASES = os.path.join(ROOT, "evals", "cases")


def run_quietly(fn, argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = fn(argv)
    return code, json.loads(out.getvalue())


class CaseSetupTest(unittest.TestCase):
    def test_every_case_builds_a_workspace_that_passes_preflight(self):
        for name in sorted(os.listdir(CASES)):
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp:
                dest = os.path.join(tmp, "ws")
                case, record = eval_setup.setup(os.path.join(CASES, name), dest)
                self.assertEqual(record["slug"], case["slug"])
                errors = [i for i in project_config.preflight(dest) if i.level == "error"]
                self.assertEqual(errors, [], [i.msg for i in errors])
                for repo, spec in case["repos"].items():
                    path = os.path.join(dest, "codebase", repo)
                    head = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"],
                                          capture_output=True, text=True)
                    self.assertEqual(head.returncode, 0, repo)
                    if spec.get("role") != "infra":  # the infra test passes only after the feature
                        build = subprocess.run(spec["commands"]["test"], shell=True, cwd=path,
                                               capture_output=True, text=True)
                        self.assertEqual(build.returncode, 0, f"{repo}: {build.stderr}")
                requirement = os.path.join(dest, ".maestro", "runs", case["slug"], "requirement",
                                           "brief.md")
                self.assertTrue(os.path.isfile(requirement))


class ScoreTest(unittest.TestCase):
    """Score a finished golden-workflow run (the no-LLM harness) against a case."""

    @classmethod
    def setUpClass(cls):
        cls.driver = e2e.SdlcE2E("test_happy_path")
        cls.driver.setUp()
        cls.driver.prep_tasks_json()
        action, _ = cls.driver.drive(dict(e2e.SdlcE2E.DESIGN_GATES))
        assert action["action"] == "done", action
        cls.root = cls.driver.tmp

    @classmethod
    def tearDownClass(cls):
        cls.driver.doCleanups()

    def case(self, expect):
        folder = tempfile.mkdtemp(prefix="eval-case-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        lines = ["name: harness", "slug: demo", "requirement: x", "repos: {}", "expect:"]
        lines += [f"  {k}: {json.dumps(v)}" for k, v in expect.items()]
        with open(os.path.join(folder, "case.yaml"), "w") as fh:
            fh.write("\n".join(lines) + "\n")
        return folder

    def test_metrics_and_expectations(self):
        folder = self.case({"status": "done", "design_path": "full", "infra_level": "none",
                            "interfaces_changed": True, "verification": "verified",
                            "ac_all_passed": True, "drift_blocking": False,
                            "min_acceptance_criteria": 1, "max_rounds_per_stage": 1,
                            "max_person_gates": 6})
        code, report = run_quietly(eval_score.main, ["score", "--root", self.root,
                                                     "--case", folder])
        self.assertEqual(code, 0, report)
        metrics = report["metrics"]
        self.assertEqual(metrics["verification"], {"backend": "verified", "frontend": "verified"})
        self.assertEqual(metrics["questions_by_stage"], {"hld": 1, "lld": 1, "prd": 1})
        self.assertEqual(metrics["person_gates"], 6)  # PRD, HLD mode, HLD, LLD scope, LLD, release
        self.assertTrue(metrics["prd_valid"])

    def test_failed_expectations_and_the_judge(self):
        folder = self.case({"max_questions": 0, "judge_min": 4})
        judge = os.path.join(folder, "judge.json")
        with open(judge, "w") as fh:
            json.dump({"scores": {"fit": 3, "evidence": 4}}, fh)
        code, report = run_quietly(eval_score.main, ["score", "--root", self.root,
                                                     "--case", folder, "--judge", judge])
        self.assertEqual(code, 1)
        self.assertEqual(report["summary"],
                         "0/2 expectations met; failed: max_questions, judge_min")
        self.assertEqual(next(c for c in report["checks"] if c["name"] == "judge_min")["actual"], 3.5)


class SummaryTest(unittest.TestCase):
    def test_regressions_against_the_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = os.path.join(tmp, "a.json")
            with open(report, "w") as fh:
                json.dump({"case": "a", "passed": False,
                           "metrics": {"questions_asked": 9, "fix_rounds": 3},
                           "judge": {"scores": {"x": 3}}}, fh)
            baseline = os.path.join(tmp, "baseline.json")
            with open(baseline, "w") as fh:
                json.dump({"a": {"passed": True, "questions_asked": 6, "fix_rounds": 1,
                                 "judge": 4.0}}, fh)
            code, out = run_quietly(eval_score.main, ["summary", "--reports", report,
                                                      "--baseline", baseline])
            self.assertEqual(code, 1)
            self.assertEqual(len(out["regressions"]), 4)
            self.assertEqual(out["summary"], "0/1 cases passed, 4 regression(s)")


if __name__ == "__main__":
    unittest.main()
