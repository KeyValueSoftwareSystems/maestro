"""Debug-mode run profile: off by default; `init --debug` keeps every visit of every step and
splits its time into queued, work (agents, scripts) and human (gates, interviews)."""

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
import run_profile  # noqa: E402
import state as statemod  # noqa: E402

FLOW = """\
version: 1
name: prof
nodes:
  - id: draft
    instruction: Draft.
    next: check
  - id: check
    type: script
    run: [python3, -c, "print('{\\"ok\\": true}')"]
    next: review
  - id: review
    type: gate
    prompt: Approve?
    options:
      - {id: approve, label: Approve, to: end}
      - {id: revise, label: Revise, to: draft, input: feedback}
"""


class RunProfileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-profile-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        with open(os.path.join(self.tmp, "prof.yaml"), "w") as fh:
            fh.write(FLOW)

    def ctl(self, *argv, code=0):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            got = maestroctl.main(["--root", self.tmp, *argv])
        self.assertEqual(got, code, err.getvalue())
        text = out.getvalue()
        return json.loads(text) if text.strip().startswith("{") else text + err.getvalue()

    def drive(self):
        """draft -> check (script, run by the lead) -> review: revise once, then approve."""
        action = self.ctl("next", "--slug", "f")
        for option in ("revise", "approve"):
            self.assertEqual(action["step"], "draft")
            action = self.ctl("complete", "--slug", "f", "--step", "draft", "--outputs", "{}")
            self.assertEqual(action["step"], "check")
            action = self.ctl("complete", "--slug", "f", "--step", "check", "--exit-code", "0",
                              "--stdout", '{"ok": true}')
            self.assertEqual(action["step"], "review")
            extra = ["--input", "tighten it"] if option == "revise" else []
            action = self.ctl("gate-record", "--slug", "f", "--step", "review",
                              "--option", option, *extra)
        self.assertEqual(action["action"], "done")

    def feature_file(self, name):
        return os.path.join(statemod.feature_dir("f", self.tmp), name)

    def test_off_by_default(self):
        started = self.ctl("init", "--slug", "f", "--workflow", "prof.yaml")
        self.assertNotIn("debug", started)
        self.drive()
        state = statemod.load("f", self.tmp)
        self.assertNotIn("profile", state)
        self.assertNotIn("served_at_ms", state["steps"]["draft"])
        self.assertFalse(os.path.exists(self.feature_file("profile.md")))
        self.assertIn("not in debug mode", self.ctl("profile", "--slug", "f", code=3))

    def test_debug_keeps_every_visit_and_splits_work_from_human(self):
        started = self.ctl("init", "--slug", "f", "--workflow", "prof.yaml", "--debug")
        self.assertTrue(started["debug"])
        self.drive()
        state = statemod.load("f", self.tmp)
        visits = state["profile"]["visits"]
        self.assertEqual([(v["step"], v["visit"]) for v in visits],
                         [("draft", 1), ("check", 1), ("review", 1),
                          ("draft", 2), ("check", 2), ("review", 2)])
        for visit in visits:
            self.assertIn("served_ms", visit)  # each was handed out by a serving call
            self.assertLessEqual(visit["start_ms"], visit["served_ms"])
            self.assertLessEqual(visit["served_ms"], visit["end_ms"])
        report = run_profile.build(state)
        self.assertEqual(report["steps"]["draft"]["visits"], 2)
        self.assertEqual(report["steps"]["review"]["type"], "gate")
        self.assertEqual(report["steps"]["review"]["work_ms"], 0)
        self.assertEqual(report["steps"]["draft"]["human_ms"], 0)
        self.assertEqual(report["visits_recorded"], 6)
        with open(self.feature_file("profile.json")) as fh:
            self.assertEqual(json.load(fh)["visits_recorded"], 6)
        text = self.ctl("profile", "--slug", "f")
        self.assertIn("# Run profile — f", text)
        self.assertIn("| review | gate | 2 |", text)

    def test_debug_switched_on_for_a_resumed_run(self):
        self.ctl("init", "--slug", "f", "--workflow", "prof.yaml")
        self.ctl("next", "--slug", "f")
        self.ctl("complete", "--slug", "f", "--step", "draft", "--outputs", "{}")
        resumed = self.ctl("init", "--slug", "f", "--workflow", "prof.yaml", "--debug")
        self.assertTrue(resumed["debug"])
        self.ctl("next", "--slug", "f")
        self.ctl("complete", "--slug", "f", "--step", "check", "--exit-code", "0")
        steps = [v["step"] for v in statemod.load("f", self.tmp)["profile"]["visits"]]
        self.assertEqual(steps, ["check"])  # visits before debug was on are not invented


class BuildTest(unittest.TestCase):
    def state(self, visits):
        return {"slug": "f", "run": {"status": "done", "debug": True}, "profile": {"visits": visits}}

    def test_categories_queued_and_idle(self):
        minute = 60_000
        report = run_profile.build(self.state([
            # a worker queued 1 min, ran 10 min
            {"step": "a", "type": "agent", "execution": "worker", "visit": 1,
             "start_ms": 0, "served_ms": minute, "end_ms": 11 * minute},
            # a person took 30 min at a gate, after 20 min with nothing running
            {"step": "g", "type": "gate", "visit": 1, "start_ms": 31 * minute,
             "served_ms": 31 * minute, "end_ms": 61 * minute},
            # an autopilot answer is work, not human time
            {"step": "auto", "type": "gate", "visit": 1, "by": "autopilot",
             "start_ms": 61 * minute, "end_ms": 61 * minute},
            # the enclosing stage is reported for its wall time only
            {"step": "stage", "type": "subworkflow", "visit": 1, "start_ms": 0,
             "end_ms": 61 * minute},
        ]))
        self.assertEqual(report["wall_ms"], 61 * minute)
        self.assertEqual(report["work_ms"], 10 * minute)
        self.assertEqual(report["human_ms"], 30 * minute)
        self.assertEqual(report["queued_ms"], minute)
        self.assertEqual(report["idle_ms"], 21 * minute)  # the first queued minute + the gap
        self.assertEqual(report["stages"]["stage"]["wall_ms"], 61 * minute)
        self.assertEqual([g["ms"] for g in report["gaps"]], [20 * minute])
        self.assertEqual(report["top"][0]["step"], "g")
        self.assertNotIn("stage", report["steps"])

    def test_a_work_visit_of_an_hour_or_more_is_flagged_as_suspect(self):
        minute = 60_000
        report = run_profile.build(self.state([
            # a lead step whose session was paused overnight still counts as work
            {"step": "write", "type": "agent", "execution": "lead", "visit": 1,
             "start_ms": 0, "end_ms": 940 * minute},
            {"step": "quick", "type": "agent", "execution": "worker", "visit": 1,
             "start_ms": 940 * minute, "end_ms": 945 * minute},
            # a person taking an hour at a gate is human time, not a suspect work visit
            {"step": "gate", "type": "gate", "visit": 1,
             "start_ms": 945 * minute, "end_ms": 1010 * minute},
        ]))
        self.assertEqual(report["long_visits"],
                         [{"step": "write", "visit": 1, "active_ms": 940 * minute}])
        text = run_profile.render_md(report)
        self.assertIn("Suspect long visits", text)
        self.assertIn("15h40m", text)

    def test_no_long_visit_section_when_nothing_is_long(self):
        report = run_profile.build(self.state([
            {"step": "a", "type": "agent", "visit": 1, "start_ms": 0, "end_ms": 10 * 60_000}]))
        self.assertEqual(report["long_visits"], [])
        self.assertNotIn("Suspect long visits", run_profile.render_md(report))


if __name__ == "__main__":
    unittest.main()
