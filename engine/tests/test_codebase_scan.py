"""codebase_scan.py — per-repo codebase-map commit tracking, against REAL git repos.

Proves the deterministic contract the incremental refresh relies on: full when there
is no marker yet, incremental (with the changed-file list) after a commit, current
when nothing moved, per-repo umbrella detection, and record stamping HEAD."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import codebase_scan as cs  # noqa: E402


def quiet(fn, *args):
    """Run a cmd_* function capturing its stdout JSON; return the parsed dict."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(*args)
    return json.loads(buf.getvalue())


def git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   capture_output=True, text=True)


def init_repo(path):
    os.makedirs(path, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.email", "t@t.t")
    git(path, "config", "user.name", "t")
    git(path, "config", "commit.gpgsign", "false")


def commit(repo, rel, content, msg):
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        fh.write(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    rc, sha = cs._git(repo, "rev-parse", "HEAD")
    return sha


def write_map(repo, body="# Codebase map\n\ncontent\n"):
    path = os.path.join(repo, cs.DEFAULT_MAP_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)
    return path


class SingleRepo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cs-single-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, ignore_errors=True)
        init_repo(self.tmp)
        commit(self.tmp, "src/a.py", "print(1)\n", "init")

    def plan(self):
        return cs.discover_repos(self.tmp), None

    def test_full_when_no_map(self):
        repos = cs.discover_repos(self.tmp)
        self.assertEqual(len(repos), 1)
        name, path = repos[0]
        map_abs = os.path.join(path, cs.DEFAULT_MAP_REL)
        # no map file yet -> plan classifies full
        head = cs._head(path)
        prev = cs.read_marker(map_abs) if os.path.exists(map_abs) else None
        self.assertIsNone(prev)
        self.assertIsNotNone(head)
        # no map at all -> the freshness gate must treat this repo as stale
        plan = self._plan(self.tmp)
        self.assertTrue(plan["stale"])
        self.assertEqual(plan["stale_repos"], [name])

    def test_incremental_after_commit_then_current(self):
        repo = self.tmp
        # write the map + record the current HEAD (simulates a build-knowledge run)
        write_map(repo)
        quiet(cs.cmd_record, repo, cs.DEFAULT_MAP_REL)
        recorded_sha = cs.read_marker(os.path.join(repo, cs.DEFAULT_MAP_REL))
        self.assertEqual(recorded_sha, cs._head(repo))

        # nothing changed -> current, and the freshness gate reports not stale
        entry = self._plan_entry(repo)
        self.assertEqual(entry["mode"], "current")
        self.assertEqual(entry["changed_count"], 0)
        self.assertFalse(self._plan(repo)["stale"])
        self.assertEqual(self._plan(repo)["stale_repos"], [])

        # a new commit -> incremental, listing exactly the changed file
        commit(repo, "src/b.py", "print(2)\n", "add b")
        entry = self._plan_entry(repo)
        self.assertEqual(entry["mode"], "incremental")
        self.assertIn("src/b.py", entry["changed_files"])
        self.assertNotIn("src/a.py", entry["changed_files"])
        self.assertEqual(entry["prev_commit"], recorded_sha)
        self.assertEqual(entry["head_commit"], cs._head(repo))
        # a real code change since the last recorded map -> the gate must fire
        plan = self._plan(repo)
        self.assertTrue(plan["stale"])
        self.assertEqual(plan["stale_repos"], [entry["name"]])

        # record again -> marker advances to the new HEAD, back to current/not stale
        write_map(repo)
        quiet(cs.cmd_record, repo, cs.DEFAULT_MAP_REL)
        self.assertEqual(self._plan_entry(repo)["mode"], "current")
        self.assertFalse(self._plan(repo)["stale"])

    def test_full_when_recorded_commit_is_gone(self):
        write_map(repo := self.tmp)
        # stamp a bogus commit that does not exist in history
        cs.write_marker(os.path.join(repo, cs.DEFAULT_MAP_REL), "0" * 40)
        entry = self._plan_entry(repo)
        self.assertEqual(entry["mode"], "full")
        self.assertTrue(self._plan(repo)["stale"])

    def test_verified_record_requires_map_prose_to_change(self):
        repo = self.tmp
        map_path = write_map(repo)
        quiet(cs.cmd_record, repo, cs.DEFAULT_MAP_REL)
        commit(repo, "src/b.py", "print(2)\n", "change")
        snapshot = os.path.join(repo, ".maestro", "runs", "x", "map-snapshot.json")
        snap = quiet(cs.cmd_snapshot, repo, cs.DEFAULT_MAP_REL, snapshot)

        self.assertEqual(cs.cmd_record(repo, cs.DEFAULT_MAP_REL, snapshot,
                                       snap["snapshot_sha256"]), 1)
        self.assertNotEqual(cs.read_marker(map_path), cs._head(repo))

        with open(map_path, "a") as fh:
            fh.write("\nUpdated architecture notes.\n")
        result = quiet(cs.cmd_record, repo, cs.DEFAULT_MAP_REL, snapshot,
                       snap["snapshot_sha256"])
        self.assertEqual(result["recorded"][0]["commit"], cs._head(repo))
        self.assertEqual(cs.read_marker(map_path), cs._head(repo))

    def test_verified_record_rejects_head_change_during_refresh(self):
        repo = self.tmp
        map_path = write_map(repo)
        quiet(cs.cmd_record, repo, cs.DEFAULT_MAP_REL)
        commit(repo, "src/b.py", "print(2)\n", "change")
        snapshot = os.path.join(repo, ".maestro", "runs", "x", "map-snapshot.json")
        snap = quiet(cs.cmd_snapshot, repo, cs.DEFAULT_MAP_REL, snapshot)
        with open(map_path, "a") as fh:
            fh.write("\nUpdated notes.\n")
        commit(repo, "src/c.py", "print(3)\n", "concurrent change")
        self.assertEqual(cs.cmd_record(repo, cs.DEFAULT_MAP_REL, snapshot,
                                       snap["snapshot_sha256"]), 1)

    def test_verified_record_rejects_tampered_snapshot(self):
        repo = self.tmp
        write_map(repo)
        quiet(cs.cmd_record, repo, cs.DEFAULT_MAP_REL)
        commit(repo, "src/b.py", "print(2)\n", "change")
        snapshot = os.path.join(repo, ".maestro", "runs", "x", "map-snapshot.json")
        snap = quiet(cs.cmd_snapshot, repo, cs.DEFAULT_MAP_REL, snapshot)
        with open(snapshot, "a") as fh:
            fh.write(" ")
        self.assertEqual(cs.cmd_record(repo, cs.DEFAULT_MAP_REL, snapshot,
                                       snap["snapshot_sha256"]), 1)

    def _plan(self, repo):
        return quiet(cs.cmd_plan, repo, cs.DEFAULT_MAP_REL)

    def _plan_entry(self, repo):
        return self._plan(repo)["repos"][0]


class UmbrellaRepos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cs-umbrella-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, ignore_errors=True)
        # umbrella: two git repos under codebase/, plus a non-repo dir that must be ignored
        for name in ("backend", "frontend"):
            init_repo(os.path.join(self.tmp, "codebase", name))
            commit(os.path.join(self.tmp, "codebase", name), "x.txt", name, "init")
        os.makedirs(os.path.join(self.tmp, "codebase", "notes"))  # not a git repo

    def test_detects_only_git_repos_under_codebase(self):
        repos = dict(cs.discover_repos(self.tmp))
        self.assertEqual(set(repos), {"backend", "frontend"})

    def test_record_stamps_each_repo_independently(self):
        for name in ("backend", "frontend"):
            write_map(os.path.join(self.tmp, "codebase", name))
        quiet(cs.cmd_record, self.tmp, cs.DEFAULT_MAP_REL)
        for name in ("backend", "frontend"):
            repo = os.path.join(self.tmp, "codebase", name)
            self.assertEqual(
                cs.read_marker(os.path.join(repo, cs.DEFAULT_MAP_REL)),
                cs._head(repo),
            )

    def test_record_skips_repo_without_map(self):
        write_map(os.path.join(self.tmp, "codebase", "backend"))
        result = quiet(cs.cmd_record, self.tmp, cs.DEFAULT_MAP_REL)
        self.assertEqual([r["name"] for r in result["recorded"]], ["backend"])
        self.assertEqual([s["name"] for s in result["skipped"]], ["frontend"])

    def test_stale_flags_only_the_drifted_repo(self):
        # both repos mapped + recorded -> nothing stale
        for name in ("backend", "frontend"):
            write_map(os.path.join(self.tmp, "codebase", name))
        quiet(cs.cmd_record, self.tmp, cs.DEFAULT_MAP_REL)
        plan = quiet(cs.cmd_plan, self.tmp, cs.DEFAULT_MAP_REL)
        self.assertFalse(plan["stale"])
        self.assertEqual(plan["stale_repos"], [])

        # a manual commit in just one repo (simulating work done outside Maestro)
        commit(os.path.join(self.tmp, "codebase", "backend"), "y.txt", "manual change", "manual")
        plan = quiet(cs.cmd_plan, self.tmp, cs.DEFAULT_MAP_REL)
        self.assertTrue(plan["stale"])
        self.assertEqual(plan["stale_repos"], ["backend"])


if __name__ == "__main__":
    unittest.main()
