import json
import sys
import tempfile
import unittest
from pathlib import Path

# state.py lives in workflows/; this test was moved to testdata/, so add the
# workflows dir to the import path before importing it.
WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "workflows"
sys.path.insert(0, str(WORKFLOWS_DIR))

import state  # noqa: E402


class LedgerCoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_step_key_without_key(self):
        self.assertEqual(state.step_key("hld"), "hld")

    def test_step_key_with_key(self):
        self.assertEqual(state.step_key("impl", "backend"), "impl:backend")

    def test_ledger_path_shape(self):
        self.assertEqual(
            state.ledger_path("saved-search", self.root),
            self.root / "saved-search" / "state.json",
        )

    def test_load_missing_returns_empty_skeleton(self):
        data = state.load_ledger("saved-search", self.root)
        self.assertEqual(data, {"version": 1, "slug": "saved-search", "steps": {}})

    def test_save_then_load_round_trips(self):
        data = {"version": 1, "slug": "s", "steps": {"hld": {"done": True}}}
        state.save_ledger("s", data, self.root)
        self.assertEqual(state.load_ledger("s", self.root), data)

    def test_save_creates_parent_dirs(self):
        state.save_ledger("newslug", state.load_ledger("newslug", self.root), self.root)
        self.assertTrue(state.ledger_path("newslug", self.root).is_file())

    def test_save_is_atomic_no_tmp_left_behind(self):
        state.save_ledger("s", {"version": 1, "slug": "s", "steps": {}}, self.root)
        leftovers = list((self.root / "s").glob("*.tmp"))
        self.assertEqual(leftovers, [])


class StateOpsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.artifact = self.root / "hld.md"
        self.artifact.write_text("# HLD\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_is_done_false_when_never_marked(self):
        self.assertFalse(state.is_done("s", "hld", root=self.root))

    def test_mark_then_is_done_true(self):
        ok = state.mark_done("s", "hld", str(self.artifact), root=self.root)
        self.assertTrue(ok)
        self.assertTrue(state.is_done("s", "hld", root=self.root))

    def test_mark_refuses_missing_artifact(self):
        ok = state.mark_done("s", "hld", str(self.root / "nope.md"), root=self.root)
        self.assertFalse(ok)
        self.assertFalse(state.is_done("s", "hld", root=self.root))

    def test_mark_refuses_empty_artifact(self):
        empty = self.root / "empty.md"
        empty.write_text("")
        self.assertFalse(state.mark_done("s", "hld", str(empty), root=self.root))

    def test_is_done_false_when_artifact_deleted_after_mark(self):
        state.mark_done("s", "hld", str(self.artifact), root=self.root)
        self.artifact.unlink()
        self.assertFalse(state.is_done("s", "hld", root=self.root))

    def test_key_namespaces_flags(self):
        state.mark_done("s", "impl", str(self.artifact), key="backend", root=self.root)
        self.assertTrue(state.is_done("s", "impl", key="backend", root=self.root))
        self.assertFalse(state.is_done("s", "impl", key="frontend", root=self.root))

    def test_reset_clears_listed_steps(self):
        state.mark_done("s", "hld", str(self.artifact), root=self.root)
        state.reset("s", steps=["hld"], root=self.root)
        self.assertFalse(state.is_done("s", "hld", root=self.root))

    def test_reset_all_clears_everything(self):
        state.mark_done("s", "hld", str(self.artifact), root=self.root)
        state.mark_done("s", "contract", str(self.artifact), root=self.root)
        state.reset("s", all_=True, root=self.root)
        self.assertEqual(state.load_ledger("s", self.root)["steps"], {})

    def test_concurrent_marks_do_not_lose_updates(self):
        import threading
        steps = [f"step{i}" for i in range(20)]

        def worker(name):
            state.mark_done("s", name, str(self.artifact), root=self.root)

        threads = [threading.Thread(target=worker, args=(s,)) for s in steps]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        recorded = state.load_ledger("s", self.root)["steps"]
        self.assertEqual(sorted(recorded), sorted(steps))


class CorruptLedgerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.artifact = self.root / "hld.md"
        self.artifact.write_text("# HLD\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _write_corrupt(self, slug):
        p = state.ledger_path(slug, self.root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{ this is not json")

    def test_load_corrupt_ledger_returns_empty_skeleton(self):
        self._write_corrupt("s")
        data = state.load_ledger("s", self.root)
        self.assertEqual(data, {"version": 1, "slug": "s", "steps": {}})

    def test_mark_done_self_heals_corrupt_ledger(self):
        self._write_corrupt("s")
        ok = state.mark_done("s", "hld", str(self.artifact), root=self.root)
        self.assertTrue(ok)
        self.assertTrue(state.is_done("s", "hld", root=self.root))

    def test_reset_does_not_raise_on_corrupt_ledger(self):
        self._write_corrupt("s")
        state.reset("s", steps=["hld"], root=self.root)


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self._tmp.name)
        (self.cwd / "art.md").write_text("content\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args):
        import subprocess
        import sys as _sys
        script = str(WORKFLOWS_DIR / "state.py")
        return subprocess.run(
            [_sys.executable, script, *args],
            cwd=self.cwd, capture_output=True, text=True,
        )

    def test_check_missing_exits_1(self):
        self.assertEqual(self._run("check", "--slug", "s", "--step", "hld").returncode, 1)

    def test_mark_then_check_exits_0(self):
        m = self._run("mark", "--slug", "s", "--step", "hld", "--artifact", "art.md")
        self.assertEqual(m.returncode, 0)
        c = self._run("check", "--slug", "s", "--step", "hld")
        self.assertEqual(c.returncode, 0)

    def test_mark_missing_artifact_exits_1(self):
        m = self._run("mark", "--slug", "s", "--step", "hld", "--artifact", "nope.md")
        self.assertEqual(m.returncode, 1)

    def test_reset_step_makes_check_fail_again(self):
        self._run("mark", "--slug", "s", "--step", "hld", "--artifact", "art.md")
        self._run("reset", "--slug", "s", "--step", "hld")
        self.assertEqual(self._run("check", "--slug", "s", "--step", "hld").returncode, 1)

    def test_reset_without_step_or_all_exits_2(self):
        self.assertEqual(self._run("reset", "--slug", "s").returncode, 2)

    def test_reset_multiple_steps(self):
        self._run("mark", "--slug", "s", "--step", "hld", "--artifact", "art.md")
        self._run("mark", "--slug", "s", "--step", "api", "--artifact", "art.md")
        self._run("reset", "--slug", "s", "--step", "hld", "--step", "api")
        self.assertEqual(self._run("check", "--slug", "s", "--step", "api").returncode, 1)


if __name__ == "__main__":
    unittest.main()
