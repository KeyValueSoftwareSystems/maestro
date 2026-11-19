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
import simulate  # noqa: E402
import state as statemod  # noqa: E402

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
    """Score a finished golden-workflow run against a case: an auto-mode major run walked by the
    no-LLM simulator over two repositories."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="eval-score-")
        shutil.copytree(os.path.join(ROOT, "workflows"),
                        os.path.join(cls.root, ".maestro", "workflows"))
        shutil.copytree(os.path.join(ROOT, "engine"), os.path.join(cls.root, ".maestro", "engine"),
                        ignore=shutil.ignore_patterns("tests", "__pycache__"))
        for repo in ("backend", "frontend"):
            path = os.path.join(cls.root, "codebase", repo)
            os.makedirs(path)
            for args in (["init", "-q"], ["config", "user.email", "t@example.com"],
                         ["config", "user.name", "T"]):
                subprocess.run(["git", *args], cwd=path, check=True)
            with open(os.path.join(path, "README.md"), "w") as fh:
                fh.write(repo + "\n")
            subprocess.run(["git", "add", "-A"], cwd=path, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)
        requirement = os.path.join(cls.root, ".maestro", "runs", "demo", "requirement")
        os.makedirs(requirement)
        with open(os.path.join(requirement, "brief.md"), "w") as fh:
            fh.write("Show the order status.\n")
        with redirect_stdout(io.StringIO()):
            code = simulate.main(["simulate.py", "--root", cls.root, "--workflow",
                                  ".maestro/workflows/sdlc-main.yaml", "--slug", "demo",
                                  "--input", "path=major", "--auto", "--mode", "auto",
                                  "--allow-script-side-effects"])
        assert code == 0, code

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def case(self, expect):
        folder = tempfile.mkdtemp(prefix="eval-case-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        lines = ["name: harness", "slug: demo", "requirement: x", "repos: {}", "expect:"]
        lines += [f"  {k}: {json.dumps(v)}" for k, v in expect.items()]
        with open(os.path.join(folder, "case.yaml"), "w") as fh:
            fh.write("\n".join(lines) + "\n")
        return folder

    def test_metrics_and_expectations(self):
        folder = self.case({"status": "done", "type": "major", "prd_valid": True,
                            "plan_valid": True, "verification": "simulated",
                            "ac_all_passed": True, "drift_blocking": False,
                            "min_acceptance_criteria": 1, "max_rounds_per_stage": 1,
                            "max_person_gates": 3})
        code, report = run_quietly(eval_score.main, ["score", "--root", self.root,
                                                     "--case", folder])
        self.assertEqual(code, 0, report)
        metrics = report["metrics"]
        self.assertEqual(metrics["verification"], {"backend": "simulated", "frontend": "simulated"})
        self.assertEqual(metrics["questions_by_stage"], {"prd": 1})
        # autopilot answers the rest; a person still confirms the brainstorm, approves the plan
        # and confirms the archive
        self.assertEqual(metrics["person_gates"], 3)
        gates = statemod.load("demo", self.root)["gates"]
        self.assertEqual(sorted(g["step"].rsplit("/", 1)[-1] for g in gates if not g.get("auto")),
                         ["brainstorm_confirm", "confirm_archive", "plan_approval"])
        self.assertTrue(metrics["prd_valid"])
        self.assertTrue(metrics["plan_valid"])

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
