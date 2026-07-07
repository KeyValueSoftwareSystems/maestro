import json
import tempfile
import unittest
from pathlib import Path

import state


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


if __name__ == "__main__":
    unittest.main()
