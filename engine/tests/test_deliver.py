"""deliver: report verified branches, or push them and open pull requests (draft on autopilot)."""
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import deliver  # noqa: E402

FAKE_GH = """#!/bin/sh
# records every call; `pr list` finds an open PR only for branches listed in $GH_EXISTING
echo "$@" >> "$GH_LOG"
case "$1 $2" in
  "pr list") case " $GH_EXISTING " in *" $4 "*) echo "https://github.test/pr/existing";; esac ;;
  "pr create") echo "https://github.test/pr/$(basename "$PWD")" ;;
esac
"""


def write(path, text):
    with open(path, "w") as fh:
        fh.write(text)


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


class DeliverTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="deliver-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.remote = os.path.join(self.root, "remote.git")
        subprocess.run(["git", "init", "-q", "--bare", self.remote], check=True)
        repo = os.path.join(self.root, "codebase", "backend")
        os.makedirs(repo)
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "t@example.com")
        git(repo, "config", "user.name", "T")
        write(os.path.join(repo, "README.md"), "x\n")
        git(repo, "add", "README.md")
        git(repo, "commit", "-qm", "initial")
        git(repo, "remote", "add", "origin", self.remote)
        self.worktree = os.path.join(self.root, "wt", "backend")
        self.branch = "feature/demo-backend"
        git(repo, "worktree", "add", "-q", "-b", self.branch, self.worktree)
        write(os.path.join(self.worktree, "f.txt"), "feature\n")
        git(self.worktree, "add", "f.txt")
        git(self.worktree, "commit", "-qm", "feature")
        self.commit = git(self.worktree, "rev-parse", "HEAD")
        run_dir = os.path.join(self.root, ".maestro", "runs", "demo")
        os.makedirs(os.path.join(run_dir, "requirement"))
        write(os.path.join(run_dir, "requirement", "prd.md"), "# Report export — PRD\n")
        os.makedirs(os.path.join(run_dir, "release"))
        os.makedirs(os.path.join(run_dir, "build"))
        write(os.path.join(run_dir, "release", "ac-trace.md"),
            "# Acceptance-criteria trace\n\n3/3 acceptance criteria passing.\n")
        write(os.path.join(run_dir, "release", "review-pack.md"), "# Pack\n\nReady.\n")
        self.manifest = os.path.join(run_dir, "build", "manifest.json")
        with open(self.manifest, "w") as fh:
            json.dump({"repositories": [{
                "repo": "backend", "branch": self.branch, "worktree": os.path.realpath(self.worktree),
                "commit": self.commit,
                "verification": {"status": "verified", "summary": "all checks passed"}}]}, fh)
        gh = os.path.join(self.root, "gh")
        with open(gh, "w") as fh:
            fh.write(FAKE_GH)
        os.chmod(gh, os.stat(gh).st_mode | stat.S_IEXEC)
        self.gh_log = os.path.join(self.root, "gh.log")
        self.env = {"MAESTRO_GH": gh, "GH_LOG": self.gh_log, "GH_EXISTING": ""}

    def config(self, delivery):
        with open(os.path.join(self.root, "maestro.config.yaml"), "w") as fh:
            fh.write("version: 1\nrepos: {}\n" + delivery)

    def run_deliver(self, *extra, env=None):
        saved = dict(os.environ)
        os.environ.update({**self.env, **(env or {})})
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = deliver.main(["--root", self.root, "--slug", "demo", "--manifest",
                                     self.manifest, "--pack", ".maestro/runs/demo/release/review-pack.md",
                                     "--trace", ".maestro/runs/demo/release/ac-trace.md", *extra])
        finally:
            os.environ.clear()
            os.environ.update(saved)
        text = out.getvalue().strip()
        return code, (json.loads(text) if text else None), err.getvalue()

    def gh_calls(self):
        if not os.path.exists(self.gh_log):
            return []
        with open(self.gh_log) as fh:
            return fh.read().splitlines()

    def test_branch_mode_pushes_nothing(self):
        code, out, _ = self.run_deliver()
        self.assertEqual((code, out["mode"], out["pr_urls_csv"]), (0, "branch", ""))
        self.assertIn(f"backend {self.branch} @ {self.commit[:12]}", out["summary"])
        self.assertEqual(self.gh_calls(), [])
        self.assertEqual(git(self.remote, "branch", "--list"), "")

    def test_pull_request_mode_pushes_and_opens_a_pr(self):
        self.config("delivery: {mode: pull-request, base: main}\n")
        code, out, err = self.run_deliver()
        self.assertEqual(code, 0, err)
        self.assertEqual(out["pr_urls_csv"], "https://github.test/pr/backend")
        self.assertFalse(out["draft"])
        self.assertEqual(git(self.remote, "rev-parse", self.branch), self.commit)
        create = [c for c in self.gh_calls() if c.startswith("pr create")][0]
        self.assertIn("--title Report export (backend)", create)
        self.assertIn("--base main", create)
        self.assertNotIn("--draft", create)
        with open(os.path.join(self.root, ".maestro/runs/demo/.engine/pr-bodies/backend.md")) as fh:
            body = fh.read()
        self.assertIn("Engine verification: verified", body)
        self.assertIn("Acceptance criteria: 3/3 acceptance criteria passing.", body)
        with open(os.path.join(self.root, out["path"])) as fh:
            self.assertEqual(json.load(fh)["repositories"][0]["pr"], "created")

    def test_autopilot_release_opens_a_draft_and_an_open_pr_is_reused(self):
        self.config("delivery: {mode: pull-request}\n")
        code, out, _ = self.run_deliver("--release-by", "autopilot")
        create = [c for c in self.gh_calls() if c.startswith("pr create")][0]
        self.assertIn("--draft", create)
        self.assertNotIn("--base", create)
        self.assertTrue(out["draft"])
        os.remove(self.gh_log)
        code, out, _ = self.run_deliver(env={"GH_EXISTING": self.branch})
        self.assertEqual(out["pr_urls_csv"], "https://github.test/pr/existing")
        self.assertFalse([c for c in self.gh_calls() if c.startswith("pr create")])

    def test_refuses_a_branch_that_moved_off_its_verified_commit(self):
        self.config("delivery: {mode: pull-request}\n")
        write(os.path.join(self.worktree, "g.txt"), "later\n")
        git(self.worktree, "add", "g.txt")
        git(self.worktree, "commit", "-qm", "unreviewed")
        code, _, err = self.run_deliver()
        self.assertEqual(code, 1)
        self.assertIn("refusing to deliver", err)
        self.assertEqual(git(self.remote, "branch", "--list"), "")

    def test_a_missing_gh_fails_clearly(self):
        self.config("delivery: {mode: pull-request}\n")
        code, _, err = self.run_deliver(env={"MAESTRO_GH": os.path.join(self.root, "no-gh")})
        self.assertEqual(code, 1)
        self.assertIn("is gh installed and logged in", err)


if __name__ == "__main__":
    unittest.main()
