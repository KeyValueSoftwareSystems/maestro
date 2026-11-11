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

    def write_package(self, repo, deps):
        with open(os.path.join(self.worktrees[repo], "package.json"), "w") as fh:
            json.dump({"name": repo, "dependencies": deps}, fh)

    def test_harness_not_needed_without_a_web_repo(self):
        self.config("repos: {backend: {stack: go}}\n")
        code, out, _ = self.run_cmd("harness", "--out", ".maestro/runs/demo/qa/harness.json")
        self.assertEqual((code, out["ready"], out["mode"]), (0, True, "not-needed"))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".maestro/runs/demo/qa/package.json")))

    def test_harness_uses_an_existing_framework(self):
        self.config("repos: {}\n")
        self.write_package("web-app", {"react": "18.3.1"})
        open(os.path.join(self.worktrees["web-app"], "playwright.config.ts"), "w").close()
        code, out, _ = self.run_cmd("harness", "--out", ".maestro/runs/demo/qa/harness.json")
        self.assertEqual((out["ready"], out["mode"]), (True, "existing"))
        self.assertIn("web-app (playwright.config.ts)", out["summary"])
        # a configured e2e command counts too; a web stack is enough to mark the repo as web
        os.remove(os.path.join(self.worktrees["web-app"], "package.json"))
        os.remove(os.path.join(self.worktrees["web-app"], "playwright.config.ts"))
        self.config('repos:\n  web-app:\n    stack: react\n    commands: {e2e: "npm run e2e"}\n')
        out = self.run_cmd("harness", "--out", ".maestro/runs/demo/qa/harness.json")[1]
        self.assertEqual(out["mode"], "existing")

    def fake_tools(self, failing=None):
        """node/npm/npx stubs on PATH that log their calls; `failing` makes that subcommand fail."""
        bin_dir = os.path.join(self.root, "fake-bin")
        os.makedirs(bin_dir, exist_ok=True)
        calls = os.path.join(self.root, "calls.txt")
        for tool in ("node", "npm", "npx"):
            path = os.path.join(bin_dir, tool)
            with open(path, "w") as fh:
                fh.write(f'#!/bin/sh\necho "{tool} $*" >> "{calls}"\n'
                         + (f'case "$*" in *"{failing}"*) echo boom; exit 7;; esac\n'
                            if failing else "") + "exit 0\n")
            os.chmod(path, 0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = bin_dir + os.pathsep + old
        self.addCleanup(os.environ.__setitem__, "PATH", old)
        return calls

    def test_harness_sets_up_playwright_for_a_web_repo_without_one(self):
        self.config("repos: {}\n")
        self.write_package("web-app", {"react": "18.3.1"})
        calls = self.fake_tools()
        code, out, _ = self.run_cmd("harness", "--out", ".maestro/runs/demo/qa/harness.json")
        self.assertEqual((code, out["ready"], out["mode"]), (0, True, "playwright"))
        qa_dir = os.path.join(self.root, ".maestro/runs/demo/qa")
        with open(os.path.join(qa_dir, "package.json")) as fh:
            self.assertIn("@playwright/test", json.load(fh)["devDependencies"])
        self.assertTrue(os.path.exists(os.path.join(qa_dir, "playwright.config.mjs")))
        self.assertTrue(os.path.isdir(os.path.join(qa_dir, "tests")))
        with open(calls) as fh:
            ran = fh.read()
        self.assertIn("npm install", ran)
        self.assertIn("playwright install --only-shell chromium", ran)
        self.assertIn("chromium.launch", ran)
        with open(os.path.join(qa_dir, "harness.json")) as fh:
            self.assertEqual([s["step"] for s in json.load(fh)["steps"]],
                             ["install", "browsers", "browser-smoke"])

    def test_harness_setup_failure_is_not_ready(self):
        self.config("repos: {web-app: {stack: vue}}\n")
        self.fake_tools(failing="playwright install")
        code, out, _ = self.run_cmd("harness", "--out", ".maestro/runs/demo/qa/harness.json")
        self.assertEqual((code, out["ready"]), (0, False))
        self.assertIn("failed at `browsers` (exit 7)", out["summary"])
        with open(os.path.join(self.root, ".maestro/runs/demo/qa/harness.json")) as fh:
            receipt = json.load(fh)
        self.assertEqual([s["step"] for s in receipt["steps"]], ["install", "browsers"])

    def harness(self):
        return self.run_cmd("harness", "--out", ".maestro/runs/demo/qa/harness.json")[1]

    def test_config_stack_decides_which_repos_are_web(self):
        # a configured non-web stack wins over a react dependency in package.json
        self.config("repos: {web-app: {stack: node}}\n")
        self.write_package("web-app", {"react": "18.3.1"})
        out = self.harness()
        self.assertEqual(out["mode"], "not-needed")
        self.assertIn("web-app: maestro.config.yaml stack", out["summary"])
        self.assertIn("set its `stack` in maestro.config.yaml", out["summary"])

    def test_monorepo_web_app_found_one_folder_down_without_a_stack(self):
        self.config("repos: {}\n")
        app = os.path.join(self.worktrees["web-app"], "apps")
        os.makedirs(os.path.join(self.worktrees["web-app"], "node_modules", "react"))
        os.makedirs(app)
        with open(os.path.join(app, "package.json"), "w") as fh:
            json.dump({"dependencies": {"vue": "3.5.0"}}, fh)
        open(os.path.join(app, "cypress.config.ts"), "w").close()
        out = self.harness()
        self.assertEqual(out["mode"], "existing")
        self.assertIn("web-app (apps/cypress.config.ts)", out["summary"])

    def test_web_repo_without_a_framework_gets_playwright_beside_an_existing_one(self):
        self.config('repos:\n  backend: {stack: react}\n  web-app:\n    stack: angular\n'
                    '    commands: {e2e: "npm run e2e"}\n')
        self.fake_tools()
        out = self.harness()
        self.assertEqual((out["ready"], out["mode"]), (True, "playwright"))
        self.assertIn("for: backend", out["summary"])
        self.assertIn("Use the existing E2E framework for: web-app (e2e command)", out["summary"])

    def test_setup_stops_when_the_time_budget_is_used_up(self):
        self.config("repos: {web-app: {stack: react}}\n")
        self.fake_tools()
        old = qa_env.HARNESS_BUDGET_S
        qa_env.HARNESS_BUDGET_S = 0
        self.addCleanup(setattr, qa_env, "HARNESS_BUDGET_S", old)
        out = self.harness()
        self.assertFalse(out["ready"])
        self.assertIn("failed at `install` (exit 124)", out["summary"])
        self.assertIn("budget of 0s used up", out["summary"])

    def workspace_folder(self, testdir="process.env.MAESTRO_QA_TESTS ?? './tests'"):
        folder = os.path.join(self.root, "e2e")
        os.makedirs(folder)
        with open(os.path.join(folder, "package.json"), "w") as fh:
            json.dump({"devDependencies": {"@playwright/test": "1.55.0"}}, fh)
        with open(os.path.join(folder, "playwright.config.ts"), "w") as fh:
            fh.write(f"export default {{ testDir: {testdir} }};\n")
        return folder

    def test_workspace_e2e_folder_wins_over_repo_frameworks(self):
        self.config('repos:\n  web-app:\n    stack: react\n    commands: {e2e: "npm run e2e"}\n')
        folder = self.workspace_folder()
        calls = self.fake_tools()
        out = self.harness()
        self.assertEqual((out["ready"], out["mode"], out["workspace_dir"]), (True, "workspace", "e2e"))
        self.assertIn("MAESTRO_QA_TESTS=", out["summary"])
        with open(calls) as fh:
            ran = fh.read()
        self.assertIn("npm install", ran)  # no package-lock.json -> install, not ci
        self.assertIn("playwright install --only-shell chromium", ran)
        qa_dir = os.path.join(self.root, ".maestro/runs/demo/qa")
        self.assertTrue(os.path.isdir(os.path.join(qa_dir, "tests")))
        self.assertFalse(os.path.exists(os.path.join(qa_dir, "package.json")))
        # installed now (node_modules present): the re-check installs nothing, link points there
        os.makedirs(os.path.join(folder, "node_modules"))
        os.remove(calls)
        out = self.harness()
        self.assertTrue(out["ready"])
        with open(calls) as fh:
            self.assertNotIn("npm install", fh.read())
        self.assertEqual(os.path.realpath(os.path.join(qa_dir, "node_modules")),
                         os.path.realpath(os.path.join(folder, "node_modules")))

    def test_workspace_config_must_take_specs_from_the_run(self):
        self.config("repos: {}\n")
        self.workspace_folder(testdir="'./tests'")
        self.fake_tools()
        out = self.harness()
        self.assertEqual((out["ready"], out["mode"]), (False, "workspace"))
        self.assertIn("process.env.MAESTRO_QA_TESTS", out["summary"])

    def test_configured_workspace_path_must_exist(self):
        self.config("repos: {}\ne2e: {path: qa-suite}\n")
        out = self.harness()
        self.assertEqual((out["ready"], out["mode"]), (False, "workspace"))
        self.assertIn("e2e.path `qa-suite` is not a folder", out["summary"])

    def test_unrelated_e2e_folder_is_ignored(self):
        self.config("repos: {backend: {stack: go}}\n")
        os.makedirs(os.path.join(self.root, "e2e"))
        self.assertEqual(self.harness()["mode"], "not-needed")

    def test_harness_reads_the_worktree_record_before_implementation(self):
        self.config("repos: {web-app: {stack: react}, backend: {stack: go}}\n")
        record = os.path.join(self.root, ".maestro/runs/demo/worktrees.json")
        with open(record, "w") as fh:
            json.dump({"repos": {repo: {"path": path} for repo, path in self.worktrees.items()}}, fh)
        open(os.path.join(self.worktrees["web-app"], "playwright.config.ts"), "w").close()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = qa_env.main(["harness", "--root", self.root, "--slug", "demo",
                                "--out", ".maestro/runs/demo/qa/harness.json"])
        result = json.loads(out.getvalue())
        self.assertEqual((code, result["mode"]), (0, "existing"))
        self.assertIn("web-app (playwright.config.ts)", result["summary"])


if __name__ == "__main__":
    unittest.main()
