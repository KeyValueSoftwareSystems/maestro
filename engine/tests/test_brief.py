"""The run brief: every agent step starts from the same engine-built facts about the run, at the
level its node asks for."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import maestroctl  # noqa: E402
import validate  # noqa: E402

FLOW = """\
version: 1
name: briefed
inputs:
  feature: {type: string, default: Report export}
nodes:
  - id: draft
    instruction: Draft the design.
    artifact: ".maestro/runs/${inputs.slug}/design.md"
    next: approve
  - id: approve
    type: gate
    prompt: Approve?
    options:
      - {id: approve, label: Approve, to: review}
      - {id: revise, label: Revise, to: draft, input: feedback}
  - id: review
    instruction: Review everything.
    brief: full
    next: repair
  - id: repair
    instruction: Fix one lint finding.
    brief: none
    next: summary
  - id: summary
    instruction: Summarize.
"""


class BriefTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-brief-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        with open(os.path.join(self.tmp, "briefed.yaml"), "w") as fh:
            fh.write(FLOW)

    def ctl(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            self.assertEqual(maestroctl.main(["--root", self.tmp, *argv]), 0)
        text = out.getvalue()
        return json.loads(text) if text.lstrip().startswith("{") else text

    def finish(self, step):
        return self.ctl("complete", "--slug", "f", "--step", step, "--outputs", "{}")

    def test_levels(self):
        self.ctl("init", "--slug", "f", "--workflow", "briefed.yaml")
        first = self.ctl("next", "--slug", "f")
        # minimal by default: feature, mode, where the run is — no documents yet
        self.assertIn("Run brief", first["prompt"])
        self.assertIn("- Feature: Report export (`f`)", first["prompt"])
        self.assertIn("- This step: `draft`", first["prompt"])
        with open(os.path.join(self.tmp, ".maestro/runs/f/design.md"), "w") as fh:
            fh.write("design\n")
        self.finish("draft")
        self.ctl("gate-record", "--slug", "f", "--step", "approve", "--option", "revise")
        self.ctl("gate-input-record", "--slug", "f", "--step", "approve",
                 "--input", "split the export worker out")
        with open(os.path.join(self.tmp, ".maestro/runs/f/design.md"), "w") as fh:
            fh.write("design v2\n")
        self.ctl("note", "--slug", "f", "--text", "the client wants CSV only")
        self.finish("draft")
        review = self.ctl("gate-record", "--slug", "f", "--step", "approve", "--option", "approve")
        # full: documents, stages, gate decisions with feedback, notes
        prompt = review["prompt"]
        self.assertIn("- Documents so far", prompt)
        self.assertIn(".maestro/runs/f/design.md (from `draft`)", prompt)
        self.assertIn('`approve` → revise (person) — "split the export worker out"', prompt)
        self.assertIn("`approve` → approve (person)", prompt)
        self.assertIn("the client wants CSV only", prompt)
        repair = self.finish("review")
        self.assertNotIn("Run brief", repair["prompt"])  # none
        summary = self.finish("repair")
        self.assertIn("Documents so far", summary["prompt"])  # minimal again
        self.assertNotIn("Decisions at gates", summary["prompt"])
        with open(os.path.join(self.tmp, ".maestro/runs/f/run-brief.md")) as fh:
            self.assertIn("Decisions at gates", fh.read())  # the file is always the full brief
        printed = self.ctl("brief", "--slug", "f", "--step", "repair")
        self.assertEqual(printed.strip(), "(this step runs without a brief)")
        self.assertIn("Notes recorded mid-run", self.ctl("brief", "--slug", "f"))

    def test_bad_levels_are_rejected(self):
        node = {"id": "a", "instruction": "x", "brief": "everything"}
        errors = [i.msg for i in validate._validate_node(node, {"a": node}, set(), "w")
                  if i.level == "error"]
        self.assertIn("agent brief must be 'none', 'minimal' or 'full'", errors)


if __name__ == "__main__":
    unittest.main()
