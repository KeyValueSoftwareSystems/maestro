"""Remote sync, provenance and feature-lock safety tests against real git repos."""
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
import codebase_scan  # noqa: E402
import workspace_sync as ws  # noqa: E402


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def quiet(fn, *args, **kwargs):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = fn(*args, **kwargs)
    return code, json.loads(buf.getvalue().splitlines()[-1])


class WorkspaceSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="workspace-sync-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "codebase", "backend")
        self.remote = os.path.join(self.tmp, "backend.git")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Test")
        with open(os.path.join(self.repo, "app.txt"), "w") as fh:
            fh.write("v1\n")
        git(self.repo, "add", "app.txt")
        git(self.repo, "commit", "-q", "-m", "initial")
        subprocess.run(["git", "init", "--bare", "-q", self.remote], check=True)
        git(self.repo, "remote", "add", "origin", self.remote)
        git(self.repo, "push", "-q", "-u", "origin", "main")

        map_path = os.path.join(self.repo, "docs", "codebase-map.md")
        os.makedirs(os.path.dirname(map_path), exist_ok=True)
        with open(map_path, "w") as fh:
            fh.write("# Backend map\n")
        codebase_scan.write_marker(map_path, git(self.repo, "rev-parse", "HEAD"))
        os.makedirs(os.path.join(self.tmp, "docs"))
        with open(os.path.join(self.tmp, "docs", "architecture.md"), "w") as fh:
            fh.write("# Architecture\n")
        for surface in ("technical", "functional"):
            directory = os.path.join(self.tmp, "docs", surface)
            os.makedirs(directory)
            with open(os.path.join(directory, "auth.md"), "w") as fh:
                fh.write(f"# {surface.title()} auth\n")
        self.evidence = os.path.join(self.tmp, "evidence.md")
        with open(self.evidence, "w") as fh:
            fh.write("indexed\n")
        quiet(ws.cmd_record_knowledge, self.tmp, self.evidence)

    def remote_commit(self, content="v2\n"):
        clone = os.path.join(self.tmp, "writer")
        subprocess.run(["git", "clone", "-q", self.remote, clone], check=True)
        git(clone, "config", "user.email", "writer@example.com")
        git(clone, "config", "user.name", "Writer")
        git(clone, "switch", "-q", "main")
        with open(os.path.join(clone, "app.txt"), "w") as fh:
            fh.write(content)
        git(clone, "add", "app.txt")
        git(clone, "commit", "-q", "-m", "remote change")
        git(clone, "push", "-q", "origin", "main")
        return git(clone, "rev-parse", "HEAD")

    def plan(self, name="plan.json", lock=None):
        path = os.path.join(self.tmp, name)
        code, out = quiet(ws.cmd_plan, self.tmp, path, lock)
        self.assertEqual(code, 0)
        with open(path) as fh:
            doc = json.load(fh)
        return path, out, doc

    def test_current_workspace_has_no_gate_work(self):
        _, out, doc = self.plan()
        self.assertFalse(out["needs_attention"])
        self.assertEqual(doc["repos"][0]["status"], "current")
        self.assertFalse(doc["knowledge"]["stale"])

    def test_fetch_then_verified_fast_forward(self):
        target = self.remote_commit()
        plan_path, out, doc = self.plan()
        repo = doc["repos"][0]
        self.assertEqual(repo["status"], "behind")
        self.assertTrue(repo["pullable"])
        self.assertTrue(out["needs_attention"])
        result_path = os.path.join(self.tmp, "result.json")
        code, result = quiet(ws.cmd_apply, self.tmp, plan_path, out["plan_sha256"], result_path)
        self.assertEqual(code, 0)
        self.assertTrue(result["updated"])
        self.assertTrue(result["refresh_needed"])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), target)

    def test_dirty_repo_is_never_updated(self):
        old = git(self.repo, "rev-parse", "HEAD")
        self.remote_commit()
        with open(os.path.join(self.repo, "local.txt"), "w") as fh:
            fh.write("local\n")
        plan_path, out, doc = self.plan()
        self.assertFalse(doc["repos"][0]["pullable"])
        code, result = quiet(ws.cmd_apply, self.tmp, plan_path, out["plan_sha256"],
                             os.path.join(self.tmp, "result.json"))
        self.assertEqual(code, 0)
        self.assertFalse(result["updated"])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), old)

    def test_dirty_application_file_surfaces_even_when_remote_is_current(self):
        with open(os.path.join(self.repo, "app.txt"), "a") as fh:
            fh.write("uncommitted\n")
        _, out, doc = self.plan()
        self.assertTrue(out["needs_attention"])
        self.assertEqual(doc["repos"][0]["status"], "current")
        self.assertTrue(doc["repos"][0]["dirty"])
        self.assertFalse(doc["repos"][0]["pullable"])

    def test_tampered_plan_is_rejected(self):
        plan_path, out, _ = self.plan()
        with open(plan_path, "a") as fh:
            fh.write(" ")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(ws.cmd_apply(self.tmp, plan_path, out["plan_sha256"],
                                          os.path.join(self.tmp, "result.json")), 1)

    def test_knowledge_and_lock_detect_local_head_drift(self):
        lock_path = os.path.join(self.tmp, "workspace-lock.json")
        _, first = quiet(ws.cmd_lock, self.tmp, lock_path)
        self.assertFalse(first["head_changed"])
        with open(os.path.join(self.repo, "local-commit.txt"), "w") as fh:
            fh.write("new\n")
        git(self.repo, "add", "local-commit.txt")
        git(self.repo, "commit", "-q", "-m", "local head move")
        _, out, doc = self.plan(lock=lock_path)
        self.assertTrue(out["needs_attention"])
        self.assertTrue(doc["knowledge"]["stale"])
        self.assertEqual(doc["lock_drift_repos"], ["backend"])
        _, second = quiet(ws.cmd_lock, self.tmp, lock_path)
        self.assertTrue(second["head_changed"])


if __name__ == "__main__":
    unittest.main()
