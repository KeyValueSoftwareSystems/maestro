"""repo_checks: the engine runs configured commands in a worktree and writes a receipt."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
SCRIPT = os.path.join(HERE, "..", "repo_checks.py")


class RepoChecksTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="maestro-checks-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.worktree = os.path.join(self.root, "wt")
        os.makedirs(self.worktree)
        subprocess.run(["git", "init", "-q", self.worktree], check=True)
        subprocess.run(["git", "-C", self.worktree, "-c", "user.email=t@e", "-c", "user.name=T",
                        "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        self.out = ".maestro/runs/demo/backend/verify.json"

    def config(self, commands, extra=""):
        lines = "".join(f"      {k}: {json.dumps(v)}\n" for k, v in commands.items())
        with open(os.path.join(self.root, "maestro.config.yaml"), "w") as fh:
            fh.write(f"version: 1\nrepos:\n  backend:\n    commands:\n{lines}{extra}")

    def run_checks(self, env=None):
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--root", self.root, "--repo", "backend",
             "--worktree", self.worktree, "--out", self.out],
            capture_output=True, text=True, env={**os.environ, **(env or {})},
        )
        result = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.returncode == 0 else None
        return proc, result

    def receipt(self):
        with open(os.path.join(self.root, self.out)) as fh:
            return json.load(fh)

    def test_all_checks_pass_and_receipt_names_the_commit(self):
        self.config({"build": "true", "lint": "echo linted", "test": "true"})
        proc, result = self.run_checks()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(result["passed"])
        receipt = self.receipt()
        head = subprocess.run(["git", "-C", self.worktree, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(receipt["commit"], head)
        self.assertEqual([c["name"] for c in receipt["checks"]], ["build", "lint", "test"])
        lint_log = os.path.join(self.root, receipt["checks"][1]["log"])
        with open(lint_log) as fh:
            self.assertIn("linted", fh.read())
        self.assertEqual(receipt["skipped"], ["setup", "typecheck"])

    def test_failing_test_is_reported_not_raised(self):
        self.config({"build": "true", "test": "echo 2 failed; exit 1"})
        proc, result = self.run_checks()
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(result["passed"])
        self.assertEqual(result["failed_checks"], "test")
        self.assertIn("2 failed", self.receipt()["checks"][-1]["tail"])

    def test_build_failure_stops_later_checks(self):
        self.config({"build": "exit 3", "lint": "true", "test": "true"})
        _proc, result = self.run_checks()
        statuses = {c["name"]: c["status"] for c in self.receipt()["checks"]}
        self.assertEqual(statuses, {"build": "failed", "lint": "not-run", "test": "not-run"})
        self.assertEqual(result["failed_checks"], "build,lint,test")

    def test_commands_run_inside_the_worktree_with_ci_set(self):
        self.config({"build": "test -d .git", "test": "test \"$CI\" = true"})
        _proc, result = self.run_checks()
        self.assertTrue(result["passed"], self.receipt())

    def test_timeout_is_a_failure(self):
        self.config({"build": "true", "test": "sleep 5"}, extra="    timeout_s: 1\n")
        _proc, result = self.run_checks()
        self.assertFalse(result["passed"])
        self.assertEqual(self.receipt()["checks"][-1]["status"], "timed-out")

    def test_missing_config_fails_closed(self):
        proc, _ = self.run_checks()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not found", proc.stderr)

    def test_missing_test_command_fails_closed(self):
        self.config({"build": "true", "lint": "true"})
        proc, _ = self.run_checks()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no test command", proc.stderr)

    def _repo_with_branch(self):
        """A main checkout with existing tests, and a feature worktree branched from it."""
        main = os.path.join(self.root, "codebase", "backend")
        os.makedirs(os.path.join(main, "tests"))
        subprocess.run(["git", "init", "-q", main], check=True)
        for rel in ("tests/test_orders.py", "tests/test_users.py", "src_test.go", "app.py"):
            with open(os.path.join(main, rel), "w") as fh:
                fh.write("assert True\n")
        subprocess.run(["git", "-C", main, "add", "."], check=True)
        subprocess.run(["git", "-C", main, "-c", "user.email=t@e", "-c", "user.name=T",
                        "commit", "-q", "-m", "base"], check=True)
        worktree = os.path.join(self.root, "feature")
        subprocess.run(["git", "-C", main, "worktree", "add", "-q", "-b", "feature", worktree],
                       check=True)
        self.worktree = worktree
        return main, worktree

    def run_guarded(self, main):
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--root", self.root, "--repo", "backend",
             "--worktree", self.worktree, "--out", self.out, "--base-repo", main],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_guard_flags_changed_and_deleted_existing_tests(self):
        main, worktree = self._repo_with_branch()
        self.config({"build": "true", "test": "true"})
        with open(os.path.join(worktree, "tests", "test_orders.py"), "w") as fh:
            fh.write("pass  # assertion removed\n")
        os.remove(os.path.join(worktree, "src_test.go"))
        with open(os.path.join(worktree, "tests", "test_new.py"), "w") as fh:
            fh.write("assert True\n")
        with open(os.path.join(worktree, "app.py"), "w") as fh:
            fh.write("changed = True\n")
        result = self.run_guarded(main)
        self.assertTrue(result["passed"])  # flagged for the reviewer, not failed
        changes = {c["path"]: c["status"] for c in self.receipt()["test_changes"]}
        self.assertEqual(changes, {"tests/test_orders.py": "modified", "src_test.go": "deleted"})
        self.assertIn("tests/test_orders.py (modified)", result["tests_changed"])
        self.assertEqual(self.receipt()["test_guard"], "ran")

    def test_guard_sees_committed_changes_and_custom_patterns(self):
        main, worktree = self._repo_with_branch()
        self.config({"build": "true", "test": "true"}, extra="    test_patterns: [\"app.py\"]\n")
        with open(os.path.join(worktree, "app.py"), "w") as fh:
            fh.write("changed = True\n")
        subprocess.run(["git", "-C", worktree, "-c", "user.email=t@e", "-c", "user.name=T",
                        "commit", "-qam", "edit"], check=True)
        result = self.run_guarded(main)
        self.assertEqual(result["tests_changed"], "app.py (modified)")

    def test_guard_without_base_repo_says_why(self):
        self.config({"build": "true", "test": "true"})
        self.run_checks()
        self.assertEqual(self.receipt()["test_guard"], "no base repository given")

    def test_simulation_mode_runs_nothing(self):
        proc, result = self.run_checks(env={"MAESTRO_SIMULATION": "1"})
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(result["passed"])
        self.assertFalse(os.path.exists(os.path.join(self.root, self.out)))


if __name__ == "__main__":
    unittest.main()
