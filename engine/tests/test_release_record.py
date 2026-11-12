"""release_record: the archive delivers only a manifest the release gate approved."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import release_record  # noqa: E402

MANIFEST = ".maestro/runs/demo/implementation-manifest.json"


class ReleaseRecordTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="release-record-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        os.makedirs(os.path.join(self.root, ".maestro", "runs", "demo"))
        self.write_manifest("abc")

    def write_manifest(self, commit):
        with open(os.path.join(self.root, MANIFEST), "w") as fh:
            json.dump({"repositories": [{"repo": "backend", "commit": commit}]}, fh)

    def run_cmd(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = release_record.main([argv[0], "--root", self.root, "--slug", "demo",
                                        "--manifest", MANIFEST, *argv[1:]])
        return code, (json.loads(out.getvalue()) if code == 0 else err.getvalue())

    def test_check_returns_who_approved_the_recorded_manifest(self):
        code, recorded = self.run_cmd("record", "--by", "autopilot")
        self.assertEqual((code, recorded["path"]), (0, ".maestro/runs/demo/release.json"))
        code, checked = self.run_cmd("check")
        self.assertEqual((code, checked["release_by"]), (0, "autopilot"))

    def test_anything_but_autopilot_is_recorded_as_a_person(self):
        self.run_cmd("record", "--by", "")
        self.assertEqual(self.run_cmd("check")[1]["release_by"], "person")

    def test_check_refuses_without_an_approval(self):
        code, err = self.run_cmd("check")
        self.assertEqual(code, 1)
        self.assertIn("no release approval is recorded", err)

    def test_check_refuses_a_manifest_changed_after_the_approval(self):
        self.run_cmd("record")
        self.write_manifest("def")
        code, err = self.run_cmd("check")
        self.assertEqual(code, 1)
        self.assertIn("changed after the release was approved", err)

    def test_a_missing_manifest_is_refused_by_both(self):
        os.remove(os.path.join(self.root, MANIFEST))
        for command in ("record", "check"):
            code, err = self.run_cmd(command)
            self.assertEqual(code, 1, command)
        self.assertIn("manifest not found", self.run_cmd("record")[1])


if __name__ == "__main__":
    unittest.main()
