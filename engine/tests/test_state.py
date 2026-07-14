"""Ledger tests: locking, atomic writes, corrupt-file fail-soft, artifact checks."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import state as statemod  # noqa: E402


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-state-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_save_load_roundtrip(self):
        data = statemod.new_state("s", "workflows/x.yaml", "abc", {"slug": "s"})
        statemod.step_entry(data, "a")["status"] = "done"
        statemod.save("s", data, self.tmp)
        back = statemod.load("s", self.tmp)
        self.assertEqual(back["steps"]["a"]["status"], "done")
        self.assertEqual(back["workflow"]["sha256"], "abc")

    def test_missing_returns_none(self):
        self.assertIsNone(statemod.load("nope", self.tmp))

    def test_corrupt_fails_soft(self):
        path = statemod.state_path("s", self.tmp)
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as fh:
            fh.write("a: &bad 1\n")
        self.assertIsNone(statemod.load("s", self.tmp))

    def test_wrong_version_fails_soft(self):
        data = statemod.new_state("s", "w.yaml", "h", {})
        data["version"] = 99
        statemod.save("s", data, self.tmp)
        self.assertIsNone(statemod.load("s", self.tmp))

    def test_artifact_ok(self):
        self.assertFalse(statemod.artifact_ok("missing.txt", self.tmp))
        empty = os.path.join(self.tmp, "empty.txt")
        open(empty, "w").close()
        self.assertFalse(statemod.artifact_ok("empty.txt", self.tmp))
        full = os.path.join(self.tmp, "full.txt")
        with open(full, "w") as fh:
            fh.write("x")
        self.assertTrue(statemod.artifact_ok("full.txt", self.tmp))

    def test_locked_is_reentrant_across_processes(self):
        # two sequential lock acquisitions must not deadlock or error
        with statemod.locked("s", self.tmp):
            pass
        with statemod.locked("s", self.tmp):
            pass

    def test_atomic_write_leaves_no_tmp(self):
        data = statemod.new_state("s", "w.yaml", "h", {})
        statemod.save("s", data, self.tmp)
        files = os.listdir(os.path.dirname(statemod.state_path("s", self.tmp)))
        self.assertNotIn("state.yaml.tmp", files)

    def test_list_runs_empty(self):
        self.assertEqual(statemod.list_runs(self.tmp), [])

    def test_list_runs_enumerates_and_summarises(self):
        first = statemod.new_state("alpha", "workflows/design.yaml", "h1", {})
        statemod.save("alpha", first, self.tmp)
        second = statemod.new_state("beta", "workflows/sdlc-main.yaml", "h2", {})
        second["run"]["cursors"] = ["author_hld"]
        statemod.save("beta", second, self.tmp)

        runs = statemod.list_runs(self.tmp)
        self.assertEqual({r["slug"] for r in runs}, {"alpha", "beta"})
        by_slug = {r["slug"]: r for r in runs}
        self.assertEqual(by_slug["alpha"]["workflow"], "workflows/design.yaml")
        self.assertEqual(by_slug["beta"]["status"], "running")
        self.assertEqual(by_slug["beta"]["active"], ["author_hld"])
        # every entry is a lightweight summary, never the full ledger
        self.assertEqual(set(runs[0]),
                         {"slug", "status", "workflow", "active", "updated_at"})

    def test_list_runs_skips_non_run_dirs(self):
        # a stray directory that isn't a run (no valid state.yaml) is ignored
        os.makedirs(os.path.join(self.tmp, statemod.MAESTRO_DIR, "memory"))
        good = statemod.new_state("real", "w.yaml", "h", {})
        statemod.save("real", good, self.tmp)
        self.assertEqual([r["slug"] for r in statemod.list_runs(self.tmp)], ["real"])


if __name__ == "__main__":
    unittest.main()
