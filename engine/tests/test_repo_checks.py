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
        self.assertEqual(receipt["skipped"], ["setup", "typecheck", "security"])

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

    def test_security_command_runs_after_the_tests(self):
        self.config({"build": "true", "test": "true", "security": "echo 1 high finding; exit 1"})
        _proc, result = self.run_checks()
        self.assertFalse(result["passed"])
        self.assertEqual(result["failed_checks"], "security")
        self.assertEqual([c["name"] for c in self.receipt()["checks"]], ["build", "test", "security"])

    def test_committed_secrets_fail_verification_without_recording_the_value(self):
        main, worktree = self._repo_with_branch()
        self.config({"build": "true", "test": "true"})
        key = "AKIA" + "Q3EXAMPLEKEY12345"[:0] + "ZX7R4N2KQ8W5PL6M"
        token = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
        with open(os.path.join(worktree, "settings.py"), "w") as fh:
            fh.write(f"AWS_KEY = '{key}'\nSAMPLE = 'AKIAIOSFODNN7EXAMPLE'\n\nGITHUB = '{token}'\n")
        subprocess.run(["git", "-C", worktree, "add", "settings.py"], check=True)
        subprocess.run(["git", "-C", worktree, "-c", "user.email=t@e", "-c", "user.name=T",
                        "commit", "-qm", "oops"], check=True)
        result = self.run_guarded(main)
        self.assertFalse(result["passed"])
        self.assertEqual(result["failed_checks"], "secrets")
        self.assertIn("settings.py:1 (aws-access-key)", result["summary"])
        secrets = next(c for c in self.receipt()["checks"] if c["name"] == "secrets")
        self.assertEqual([(f["path"], f["line"], f["rule"]) for f in secrets["findings"]],
                         [("settings.py", 1, "aws-access-key"), ("settings.py", 4, "github-token")])
        with open(os.path.join(self.root, self.out)) as fh:
            receipt_text = fh.read()
        self.assertNotIn(key, receipt_text)
        self.assertNotIn(token, receipt_text)
        self.assertEqual(self.receipt()["secret_scan"], "ran")

    def commit_feature(self, worktree, rel="feature.txt", text="new\n"):
        with open(os.path.join(worktree, rel), "w") as fh:
            fh.write(text)
        subprocess.run(["git", "-C", worktree, "add", rel], check=True)
        subprocess.run(["git", "-C", worktree, "-c", "user.email=t@e", "-c", "user.name=T",
                        "commit", "-qm", "feature"], check=True)

    def test_a_check_that_also_fails_on_the_base_commit_is_pre_existing(self):
        main, worktree = self._repo_with_branch()
        self.commit_feature(worktree)
        # lint fails everywhere (an old backlog); the build fails only where feature.txt exists
        self.config({"setup": "touch .setup-ran", "build": "true",
                     "lint": "echo 1392 problems; exit 1", "test": "true"})
        result = self.run_guarded(main)
        self.assertTrue(result["passed"], result)
        self.assertEqual((result["failed_checks"], result["pre_existing_csv"]), ("", "lint"))
        self.assertIn("pre-existing failures, also failing on base", result["summary"])
        lint = next(c for c in self.receipt()["checks"] if c["name"] == "lint")
        self.assertEqual(lint["status"], "pre-existing")
        base = subprocess.run(["git", "-C", main, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(lint["baseline"]["commit"], base)
        self.assertEqual(self.receipt()["pre_existing"], ["lint"])
        checkout = os.path.join(self.root, ".maestro", "baseline", "backend", base[:12])
        self.assertTrue(os.path.exists(os.path.join(checkout, ".setup-ran")))  # setup ran first
        with open(os.path.join(self.root, ".maestro", "baseline", ".gitignore")) as fh:
            self.assertIn("*", fh.read())

    def test_the_baseline_works_with_a_relative_root_as_the_workflow_passes_it(self):
        main, worktree = self._repo_with_branch()
        self.commit_feature(worktree)
        self.config({"build": "true", "test": "test -f never-there"})
        proc = subprocess.run(
            [sys.executable, os.path.abspath(SCRIPT), "--root", ".", "--repo", "backend",
             "--worktree", "feature", "--out", self.out, "--base-repo", "codebase/backend"],
            capture_output=True, text=True, cwd=self.root,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual((result["passed"], result["pre_existing_csv"]), (True, "test"))
        base = subprocess.run(["git", "-C", main, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".maestro", "baseline", "backend",
                                                   base[:12])))
        self.assertFalse(os.path.exists(os.path.join(main, ".maestro")))  # never inside the repo

    def run_keyed(self, main, key):
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--root", self.root, "--repo", "backend",
             "--worktree", self.worktree, "--out", self.out, "--base-repo", main,
             "--reuse-key", key],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_an_unchanged_commit_reuses_the_receipt_until_a_person_intervenes(self):
        main, worktree = self._repo_with_branch()
        self.commit_feature(worktree)
        counter = os.path.join(self.root, "test-runs")
        self.config({"build": "true",
                     "test": f"echo x >> {counter}; test ! -f feature.txt"})
        first = self.run_keyed(main, "impl_gate-0")
        self.assertEqual((first["passed"], first["unchanged"]), (False, False))
        again = self.run_keyed(main, "impl_gate-0")  # the fix round committed nothing
        self.assertEqual((again["passed"], again["unchanged"]), (False, True))
        self.assertIn("No new commit since the last verify", again["summary"])
        self.assertEqual(again["failed_checks"], "test")
        after_gate = self.run_keyed(main, "impl_gate-1")  # a person chose another round
        self.assertFalse(after_gate["unchanged"])
        with open(os.path.join(worktree, "feature.txt"), "w") as fh:
            fh.write("edited, not committed\n")
        self.assertFalse(self.run_keyed(main, "impl_gate-1")["unchanged"])  # dirty: re-run
        subprocess.run(["git", "-C", worktree, "checkout", "-q", "--", "feature.txt"], check=True)
        # clean now, but it was verified dirty: the fix changed files without a commit — re-run
        self.assertFalse(self.run_keyed(main, "impl_gate-1")["unchanged"])
        self.commit_feature(worktree, rel="other.txt")
        self.assertFalse(self.run_keyed(main, "impl_gate-1")["unchanged"])  # new commit
        self.config({"build": "true", "test": f"echo x >> {counter}; true"})
        self.assertFalse(self.run_keyed(main, "impl_gate-1")["unchanged"])  # command changed
        with open(counter) as fh:  # branch runs only (the base run is cached once)
            self.assertEqual(fh.read().count("x"), 7)

    def test_a_failure_the_feature_caused_still_fails(self):
        main, worktree = self._repo_with_branch()
        self.commit_feature(worktree)
        self.config({"build": "test ! -f feature.txt", "test": "true"})
        result = self.run_guarded(main)
        self.assertFalse(result["passed"])
        self.assertEqual((result["failed_checks"], result["pre_existing_csv"]),
                         ("build,test", ""))

    def test_the_baseline_runs_once_per_base_commit_and_command(self):
        main, worktree = self._repo_with_branch()
        self.commit_feature(worktree)
        counter = os.path.join(self.root, "baseline-runs")
        self.config({"build": "true", "test": f"test -f feature.txt || echo x >> {counter}; exit 1"})
        self.assertEqual(self.run_guarded(main)["pre_existing_csv"], "test")
        self.assertEqual(self.run_guarded(main)["pre_existing_csv"], "test")
        with open(counter) as fh:
            self.assertEqual(fh.read().count("x"), 1)  # the second verify used the cached result

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
