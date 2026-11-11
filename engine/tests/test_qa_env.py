"""qa_env: the QA environment and project e2e suites run by the engine, against the verified
worktrees named in the manifest."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import qa_env  # noqa: E402


class QaEnvTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="qa-env-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.worktrees = {}
        for repo in ("backend", "web-app"):
            path = os.path.join(self.root, "worktrees", repo)
            os.makedirs(path)
            self.worktrees[repo] = path
        self.manifest = ".maestro/runs/demo/implementation-manifest.json"
        full = os.path.join(self.root, self.manifest)
        os.makedirs(os.path.dirname(full))
        with open(full, "w") as fh:
            json.dump({"feature_slug": "demo", "repositories": [
                {"repo": repo, "worktree": path, "commit": f"{repo}-sha"}
                for repo, path in self.worktrees.items()]}, fh)

    def config(self, text):
        with open(os.path.join(self.root, "maestro.config.yaml"), "w") as fh:
            fh.write("version: 1\n" + text)

    def run_cmd(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = qa_env.main([argv[0], "--root", self.root, "--manifest", self.manifest,
                                *argv[1:]])
        text = out.getvalue().strip()
        return code, (json.loads(text) if text else None), err.getvalue()

    def test_nothing_configured_is_reported_not_failed(self):
        self.config("repos: {}\n")
        code, out, _ = self.run_cmd("up")
        self.assertEqual((code, out["configured"]), (0, False))
        code, out, _ = self.run_cmd("e2e", "--out", "r.json")
        self.assertTrue(out["passed"])
        self.assertIn("No project e2e command configured", out["summary"])
        self.assertEqual(self.run_cmd("down")[1]["configured"], False)

    def test_plan_reports_whether_the_workspace_has_an_e2e_suite(self):
        self.config("repos:\n  backend:\n    commands: {build: b, test: t}\n"
                    "    e2e: {status: none, reason: none found}\n")
        code, out, _ = self.run_cmd("plan")
        self.assertEqual((code, out["has_e2e"], out["e2e_repos_csv"]), (0, False, ""))
        self.assertIn("add no framework", out["summary"])
        self.config("repos:\n  backend:\n    commands: {build: b, test: t}\n  web-app:\n"
                    "    commands: {build: b, test: t, e2e: npm run e2e}\n"
                    "    e2e: {status: verified, framework: playwright}\n")
        _, out, _ = self.run_cmd("plan")
        self.assertEqual((out["has_e2e"], out["e2e_repos_csv"]), (True, "web-app"))
        self.assertIn("web-app (playwright: npm run e2e)", out["summary"])

    def test_start_gets_the_code_under_test_and_ready_must_pass(self):
        self.config('repos: {}\nenvironment:\n'
                    '  start: "echo $MAESTRO_WORKTREE_WEB_APP $MAESTRO_COMMIT_BACKEND > up.txt"\n'
                    '  ready: "test -f up.txt"\n  stop: "rm up.txt"\n')
        code, out, _ = self.run_cmd("up")
        self.assertEqual((code, out["started"]), (0, True))
        with open(os.path.join(self.root, "up.txt")) as fh:
            self.assertEqual(fh.read().split(), [self.worktrees["web-app"], "backend-sha"])
        code, out, _ = self.run_cmd("down")
        self.assertTrue(out["stopped"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "up.txt")))
        self.config('repos: {}\nenvironment: {start: "true", ready: "false"}\n')
        code, _, err = self.run_cmd("up")
        self.assertEqual(code, 1)
        self.assertIn("ready failed", err)

    def test_e2e_runs_each_configured_suite_in_its_worktree(self):
        self.config('repos:\n  backend:\n    commands: {build: "true", test: "true", '
                    'e2e: "pwd > ran.txt"}\n  web-app:\n    commands: {build: "true", '
                    'test: "true", e2e: "exit 3"}\n')
        code, out, _ = self.run_cmd("e2e", "--out", ".maestro/runs/demo/qa/e2e-receipt.json")
        self.assertEqual(code, 0)
        self.assertFalse(out["passed"])
        self.assertEqual((out["failed_repos"], out["ran_csv"]), ("web-app", "backend,web-app"))
        self.assertEqual(out["summary"], "Project e2e failed: web-app")
        with open(os.path.join(self.worktrees["backend"], "ran.txt")) as fh:
            self.assertEqual(os.path.realpath(fh.read().strip()),
                             os.path.realpath(self.worktrees["backend"]))
        with open(os.path.join(self.root, out["receipt_path"])) as fh:
            receipt = json.load(fh)
        self.assertEqual([(c["repo"], c["commit"], c["exit_code"]) for c in receipt["checks"]],
                         [("backend", "backend-sha", 0), ("web-app", "web-app-sha", 3)])


if __name__ == "__main__":
    unittest.main()
