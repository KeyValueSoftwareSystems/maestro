"""Timeouts and resume safety: a stuck worker is reported and can be re-served, and a result from
an older dispatch never overwrites the newer one."""
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
import state as statemod  # noqa: E402
import validate  # noqa: E402

FLOW = """\
version: 1
name: pair
nodes:
  - id: fan
    type: parallel
    branches:
      - id: a
        start: work
        steps:
          - {id: work, instruction: Build A., timeout: 60}
      - id: b
        start: work
        steps:
          - {id: work, instruction: Build B.}
"""


class ResumeSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-resume-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        with open(os.path.join(self.tmp, "pair.yaml"), "w") as fh:
            fh.write(FLOW)

    def ctl(self, *argv, code=0):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            got = maestroctl.main(["--root", self.tmp, *argv])
        self.assertEqual(got, code, err.getvalue())
        return json.loads(out.getvalue()) if out.getvalue().strip() else err.getvalue()

    def age(self, step, seconds):
        state = statemod.load("f", self.tmp)
        import datetime
        past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds)
        state["steps"][step]["dispatched_at"] = past.strftime("%Y-%m-%dT%H:%M:%SZ")
        statemod.save("f", state, self.tmp)

    def test_results_from_an_older_dispatch_are_refused(self):
        self.ctl("init", "--slug", "f", "--workflow", "pair.yaml")
        wave = self.ctl("next", "--slug", "f")
        claims = {a["step"]: a["claim"] for a in wave["agents"]}
        self.assertEqual(sorted(claims), ["fan[a]/work", "fan[b]/work"])
        # the session restarts: init releases the claims and the work is served again
        self.ctl("init", "--slug", "f", "--workflow", "pair.yaml")
        again = {a["step"]: a["claim"] for a in self.ctl("next", "--slug", "f")["agents"]}
        self.assertNotEqual(again["fan[a]/work"], claims["fan[a]/work"])
        err = self.ctl("complete", "--slug", "f", "--step", "fan[a]/work", "--outputs", "{}",
                       "--claim", claims["fan[a]/work"], code=4)
        self.assertIn("re-dispatched", err)
        self.ctl("complete", "--slug", "f", "--step", "fan[a]/work", "--outputs", "{}",
                 "--claim", again["fan[a]/work"])
        # a completion without a claim is still accepted (older leads)
        done = self.ctl("complete", "--slug", "f", "--step", "fan[b]/work", "--outputs", "{}")
        self.assertEqual(done["action"], "done")

    def test_stuck_workers_are_reported_and_can_be_reclaimed(self):
        self.ctl("init", "--slug", "f", "--workflow", "pair.yaml")
        first = {a["step"]: a["claim"] for a in self.ctl("next", "--slug", "f")["agents"]}
        wait = self.ctl("next", "--slug", "f")
        self.assertEqual(wait["action"], "wait")
        self.assertNotIn("stale", wait)
        self.age("fan[a]/work", 120)   # past its 60 s timeout
        self.age("fan[b]/work", 120)   # well inside the 3600 s default
        wait = self.ctl("next", "--slug", "f")
        self.assertEqual([s["step"] for s in wait["stale"]], ["fan[a]/work"])
        self.assertIn("reclaim", wait["hint"])
        reserved = self.ctl("reclaim", "--slug", "f", "--step", "fan[a]/work")
        self.assertEqual(reserved["step"], "fan[a]/work")
        self.assertNotEqual(reserved["claim"], first["fan[a]/work"])
        self.ctl("reclaim", "--slug", "f", "--step", "nope", code=4)

    def test_timeout_must_be_positive_seconds(self):
        node = {"id": "a", "instruction": "x", "timeout": "1h"}
        errors = [i.msg for i in validate._validate_node(node, {"a": node}, set(), "w")
                  if i.level == "error"]
        self.assertIn("agent timeout must be a positive whole number of seconds", errors)


if __name__ == "__main__":
    unittest.main()
