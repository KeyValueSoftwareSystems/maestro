"""Implementation pool verifies every designed repo and hands QA exact git identities."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import implementation_pool as pool  # noqa: E402


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = pool.main(list(argv))
    out = buf.getvalue().strip()
    return code, json.loads(out) if code == 0 and out else out


class ImplementationPoolTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="impl-pool-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.repo = os.path.join(self.root, "codebase", "mobile-app")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Test")
        with open(os.path.join(self.repo, "README.md"), "w") as fh:
            fh.write("initial\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-q", "-m", "initial")
        run_dir = os.path.join(self.root, ".maestro", "runs", "feature-x")
        os.makedirs(run_dir)
        with open(os.path.join(run_dir, "lld-repos.json"), "w") as fh:
            json.dump({"selected": ["mobile-app"], "remaining": []}, fh)

    def create_feature_worktree(self):
        worktree = os.path.join(self.root, "worktrees", "mobile-app")
        os.makedirs(os.path.dirname(worktree))
        branch = "feature/feature-x-mobile-app"
        git(self.repo, "worktree", "add", "-q", "-b", branch, worktree, "HEAD")
        with open(os.path.join(worktree, "README.md"), "a") as fh:
            fh.write("feature\n")
        git(worktree, "add", "README.md")
        git(worktree, "commit", "-q", "-m", "feature")
        return worktree, branch, git(worktree, "rev-parse", "HEAD")

    def test_verified_worktree_becomes_qa_manifest(self):
        code, out = run("init", "--root", self.root, "--slug", "feature-x")
        self.assertEqual(code, 0)
        self.assertEqual(out["selected_csv"], "mobile-app")
        _, claim = run("claim", "--root", self.root, "--slug", "feature-x")
        self.assertEqual(claim["repo"], "mobile-app")

        worktree, branch, commit = self.create_feature_worktree()

        code, inspected = run("inspect", "--root", self.root, "--repo", "mobile-app",
                              "--branch", branch,
                              "--worktree", worktree)
        self.assertEqual(code, 0)
        self.assertEqual(inspected["commit"], commit)

        code, _ = run("record", "--root", self.root, "--slug", "feature-x",
                      "--repo", "mobile-app", "--branch", "feature/feature-x-mobile-app",
                      "--worktree", worktree, "--commit", commit)
        self.assertEqual(code, 0)
        code, final = run("finalize", "--root", self.root, "--slug", "feature-x")
        self.assertEqual(code, 0)
        self.assertEqual(len(final["manifest_sha256"]), 64)
        with open(os.path.join(self.root, final["manifest_path"])) as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest["repositories"][0]["commit"], commit)
        self.assertEqual(manifest["repositories"][0]["worktree"], os.path.realpath(worktree))

    def test_finalize_rechecks_branch_did_not_move_after_record(self):
        run("init", "--root", self.root, "--slug", "feature-x")
        run("claim", "--root", self.root, "--slug", "feature-x")
        worktree, branch, commit = self.create_feature_worktree()
        code, _ = run("record", "--root", self.root, "--slug", "feature-x",
                      "--repo", "mobile-app", "--branch", branch,
                      "--worktree", worktree, "--commit", commit)
        self.assertEqual(code, 0)
        with open(os.path.join(worktree, "README.md"), "a") as fh:
            fh.write("moved after review\n")
        git(worktree, "add", "README.md")
        git(worktree, "commit", "-q", "-m", "unreviewed change")
        code, _ = run("finalize", "--root", self.root, "--slug", "feature-x")
        self.assertEqual(code, 1)

    def test_rejects_main_checkout_as_worktree(self):
        run("init", "--root", self.root, "--slug", "feature-x")
        run("claim", "--root", self.root, "--slug", "feature-x")
        branch = "feature/unsafe"
        git(self.repo, "checkout", "-q", "-b", branch)
        commit = git(self.repo, "rev-parse", "HEAD")
        code, _ = run("record", "--root", self.root, "--slug", "feature-x",
                      "--repo", "mobile-app", "--branch", branch,
                      "--worktree", self.repo, "--commit", commit)
        self.assertEqual(code, 1)

    def test_finalize_fails_when_selected_repo_was_not_recorded(self):
        run("init", "--root", self.root, "--slug", "feature-x")
        run("claim", "--root", self.root, "--slug", "feature-x")
        code, _ = run("finalize", "--root", self.root, "--slug", "feature-x")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
