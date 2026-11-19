"""maestroctl slug-check, and init refusing to start a new run on a slug that is already used:
a slug names one feature for good (its run folder and its plan under docs/plans)."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import maestroctl  # noqa: E402

FLOW = """\
version: 1
name: tiny
nodes:
  - id: draft
    instruction: Draft.
    next: end
"""


class SlugCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-slug-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        with open(os.path.join(self.tmp, "flow.yaml"), "w") as fh:
            fh.write(FLOW)

    def touch(self, rel, text="x\n"):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def ctl(self, *argv, code=0):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            got = maestroctl.main(["--root", self.tmp, *argv])
        self.assertEqual(got, code, err.getvalue())
        text = out.getvalue()
        return json.loads(text) if text.strip().startswith("{") else err.getvalue()

    def check(self, slug):
        return self.ctl("slug-check", slug)

    def test_format(self):
        self.assertTrue(self.check("csv-export")["available"])
        for bad in ("CSV", "csv_export", "csv--export", "csv-", "csv.export", "../x"):
            out = self.check(bad)
            self.assertFalse(out["available"], bad)
            self.assertIn("kebab-case", out["reason"])

    def test_root_after_the_subcommand(self):
        self.touch("docs/plans/active/csv-export.md")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(maestroctl.main(["slug-check", "csv-export", "--root", self.tmp]), 0)
        self.assertFalse(json.loads(out.getvalue())["available"])

    def test_used_slugs(self):
        self.touch(".maestro/runs/one/state.yaml")
        self.touch("docs/plans/active/two.md")
        self.touch("docs/plans/completed/three.md")
        self.assertIn("already exists", self.check("one")["reason"])
        self.assertIn("in progress", self.check("two")["reason"])
        self.assertIn("delivered", self.check("three")["reason"])

    def test_a_prepared_requirement_folder_is_still_free(self):
        self.touch(".maestro/runs/four/requirement/request.md")
        self.assertTrue(self.check("four")["available"])
        self.touch(".maestro/runs/four/design/notes.md")
        self.assertFalse(self.check("four")["available"])

    def test_init_refuses_to_create_on_a_used_slug(self):
        self.touch("docs/plans/active/two.md")
        err = self.ctl("init", "--slug", "two", "--workflow", "flow.yaml", "--no-profile", code=3)
        self.assertIn("plan in progress", err)
        self.touch("docs/plans/completed/three.md")
        err = self.ctl("init", "--slug", "three", "--workflow", "flow.yaml", code=3)
        self.assertIn("delivered", err)
        err = self.ctl("init", "--slug", "three", "--workflow", "flow.yaml", "--force", code=3)
        self.assertIn("delivered", err)

    def test_init_creates_after_the_lead_prepares_the_requirement_and_resumes(self):
        self.touch(".maestro/runs/five/requirement/request.md")
        out = self.ctl("init", "--slug", "five", "--workflow", "flow.yaml")
        self.assertTrue(out["created"])
        # the run's own plan appearing later does not block resuming it
        self.touch("docs/plans/active/five.md")
        out = self.ctl("init", "--slug", "five", "--workflow", "flow.yaml")
        self.assertFalse(out["created"])
        # a restart of the same feature is allowed while its plan is active
        out = self.ctl("init", "--slug", "five", "--workflow", "flow.yaml", "--force")
        self.assertTrue(out["created"])


if __name__ == "__main__":
    unittest.main()
