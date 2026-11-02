"""Run modes: `human` asks every gate; `design` and `auto` let each gate's `auto:` policy answer
it, record the choice as an autopilot decision, and stop the run at any gate the policy does
not answer."""

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
import assumptions  # noqa: E402
import maestroctl  # noqa: E402
import resolver  # noqa: E402
import state as statemod  # noqa: E402
import stop_hook  # noqa: E402
import validate  # noqa: E402

FLOW = """\
version: 1
name: modes
nodes:
  - id: draft
    instruction: Draft.
    outputs: [ready]
    next: design_ok
  - id: design_ok
    type: gate
    prompt: Approve the design?
    options:
      - {id: approve, label: Approve, to: build}
      - {id: revise, label: Revise, to: draft, input: feedback}
    auto: {option: approve, modes: [auto]}
  - id: build
    instruction: Build.
    next: release
  - id: release
    type: gate
    prompt: Release?
    options:
      - {id: approve, label: Approve, to: end}
      - {id: reject, label: Reject, to: abort}
    auto: {option: approve, when: "${steps.draft.outputs.ready} == true"}
"""

LOOP = """\
version: 1
name: loop
nodes:
  - id: work
    instruction: Work.
    max_visits: 2
    next: again
  - id: again
    type: gate
    prompt: Again?
    options:
      - {id: again, label: Again, to: work}
      - {id: stop, label: Stop, to: end}
    auto: {option: again}
"""


class RunModeCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-modes-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name, text in (("modes.yaml", FLOW), ("loop.yaml", LOOP)):
            with open(os.path.join(self.tmp, name), "w") as fh:
                fh.write(text)

    def write_config(self):
        with open(os.path.join(self.tmp, "maestro.config.yaml"), "w") as fh:
            fh.write("version: 1\nrepos: {}\n")

    def ctl(self, *argv, code=0):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                got = maestroctl.main(["--root", self.tmp, *argv])
            except SystemExit as exc:  # argparse rejects bad choices
                got = exc.code
        self.assertEqual(got, code, err.getvalue())
        text = out.getvalue()
        return json.loads(text) if text.strip().startswith("{") else err.getvalue()

    def drive_to_gate_or_end(self, ready=True):
        action = self.ctl("next", "--slug", "f")
        self.assertEqual(action["step"], "draft")
        return self.ctl("complete", "--slug", "f", "--step", "draft",
                        "--outputs", json.dumps({"ready": ready}))

    def gates(self):
        return statemod.load("f", self.tmp)["gates"]

    def test_human_mode_asks_every_gate(self):
        started = self.ctl("init", "--slug", "f", "--workflow", "modes.yaml")
        self.assertEqual(started["mode"], "human")
        action = self.drive_to_gate_or_end()
        self.assertEqual(action["action"], "ask_gate")
        self.assertEqual(action["step"], "design_ok")
        self.assertNotIn("mode", action)
        self.assertNotIn("autopilot", action)

    def test_design_mode_answers_only_gates_whose_policy_lists_it(self):
        self.ctl("init", "--slug", "f", "--workflow", "modes.yaml", "--mode", "design")
        action = self.drive_to_gate_or_end()
        # design_ok autopilots only in auto mode: the run stops for a person
        self.assertEqual(action["step"], "design_ok")
        self.assertEqual(action["mode"], "design")
        action = self.ctl("gate-record", "--slug", "f", "--step", "design_ok", "--option", "approve")
        self.assertEqual(action["step"], "build")
        action = self.ctl("complete", "--slug", "f", "--step", "build", "--outputs", "{}")
        self.assertEqual(action["action"], "done")
        self.assertEqual(action["autopilot"], [
            {"kind": "gate", "step": "release", "option": "approve", "label": "Approve",
             "mode": "design"}])
        self.assertEqual([(g["step"], g.get("auto")) for g in self.gates()],
                         [("design_ok", None), ("release", "design")])

    def test_auto_mode_runs_through_and_stops_when_the_condition_fails(self):
        self.write_config()
        self.ctl("init", "--slug", "f", "--workflow", "modes.yaml", "--mode", "auto")
        action = self.drive_to_gate_or_end(ready=False)
        self.assertEqual(action["step"], "build")
        self.assertEqual(action["autopilot"][0]["step"], "design_ok")
        action = self.ctl("complete", "--slug", "f", "--step", "build", "--outputs", "{}")
        # release's condition is false: autopilot halts at the gate instead of guessing
        self.assertEqual(action["action"], "ask_gate")
        self.assertEqual(action["step"], "release")
        self.assertEqual(action["mode"], "auto")

    def test_switching_mode_on_resume_takes_over_from_the_next_gate(self):
        self.write_config()
        self.ctl("init", "--slug", "f", "--workflow", "modes.yaml", "--mode", "auto")
        resumed = self.ctl("init", "--slug", "f", "--workflow", "modes.yaml", "--mode", "human")
        self.assertEqual(resumed["mode"], "human")
        self.assertEqual(self.drive_to_gate_or_end()["step"], "design_ok")
        self.assertIn("run mode set to human",
                      [n["text"] for n in statemod.load("f", self.tmp)["notes"]])
        # resuming without --mode keeps it
        self.assertEqual(self.ctl("init", "--slug", "f", "--workflow", "modes.yaml")["mode"], "human")

    def test_autopilot_choices_stay_within_the_visit_cap(self):
        self.write_config()
        self.ctl("init", "--slug", "f", "--workflow", "loop.yaml", "--mode", "auto")
        action = self.ctl("next", "--slug", "f")
        for _ in range(2):
            self.assertEqual(action["step"], "work")
            action = self.ctl("complete", "--slug", "f", "--step", "work", "--outputs", "{}")
        # the third autopilot "again" would exceed work's cap: a person decides instead
        self.assertEqual(action["action"], "ask_gate")
        self.assertEqual(action.get("synthesized"), "exhausted")

    def test_auto_mode_needs_a_passing_preflight(self):
        err = self.ctl("init", "--slug", "f", "--workflow", "modes.yaml", "--mode", "auto",
                       code=3)
        self.assertIn("preflight", err)
        self.assertIsNone(statemod.load("f", self.tmp))
        self.write_config()
        self.assertEqual(self.ctl("init", "--slug", "f", "--workflow", "modes.yaml",
                                  "--mode", "auto")["mode"], "auto")
        self.ctl("init", "--slug", "f", "--workflow", "modes.yaml", "--mode", "fast", code=2)



    def stop_hook_exit(self):
        stdin = sys.stdin
        sys.stdin = io.StringIO(json.dumps({"cwd": self.tmp}))
        try:
            with redirect_stderr(io.StringIO()):
                return stop_hook.main()
        finally:
            sys.stdin = stdin

    def test_stop_hook_keeps_going_only_past_gates_the_mode_answers(self):
        self.ctl("init", "--slug", "f", "--workflow", "modes.yaml", "--mode", "design")
        self.drive_to_gate_or_end()
        self.ctl("gate-record", "--slug", "f", "--step", "design_ok", "--option", "approve")
        # build is served and claimed; once it completes, release is a gate design mode answers
        with statemod.locked("f", self.tmp):
            run = resolver.Run("f", self.tmp)
            resolver.complete_step(run, "build", outputs={})
            statemod.save("f", run.state, self.tmp)
        self.assertEqual(statemod.load("f", self.tmp)["run"]["cursors"], ["release"])
        self.assertEqual(self.stop_hook_exit(), 2)
        self.ctl("init", "--slug", "f", "--workflow", "modes.yaml", "--mode", "human")
        self.assertEqual(self.stop_hook_exit(), 0)


INTERVIEW = """\
version: 1
name: ask
nodes:
  - id: ask
    type: interview
    sections:
      - {id: retention, title: Retention, proposal: Keep 30 days}
      - {id: owner, title: Data owner}
    artifact: ctx/demo-context.json
    auto: {modes: [auto]}
    routes:
      - {when: "${run.mode} == auto", to: write}
      - {to: again}
  - id: again
    instruction: Ask again.
  - id: write
    instruction: Write.
"""


class InterviewAutopilotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-ask-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        with open(os.path.join(self.tmp, "ask.yaml"), "w") as fh:
            fh.write(INTERVIEW)
        with open(os.path.join(self.tmp, "maestro.config.yaml"), "w") as fh:
            fh.write("version: 1\nrepos: {}\n")

    def ctl(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            self.assertEqual(maestroctl.main(["--root", self.tmp, *argv]), 0)
        return json.loads(out.getvalue())

    def test_auto_mode_assumes_recommendations_defers_the_rest_and_routes_on_mode(self):
        self.ctl("init", "--slug", "f", "--workflow", "ask.yaml", "--mode", "auto")
        action = self.ctl("next", "--slug", "f")
        self.assertEqual(action["step"], "write")  # one round: straight to the writer
        self.assertEqual(action["autopilot"], [
            {"kind": "interview", "step": "ask", "mode": "auto", "assumed": 1, "deferred": 1}])
        with open(os.path.join(self.tmp, "ctx", "demo-context.json")) as fh:
            decisions = {d["id"]: d for d in json.load(fh)["decisions"]}
        self.assertEqual((decisions["retention"]["source"], decisions["retention"]["answer"]),
                         ("assumption", "Keep 30 days"))
        self.assertEqual(decisions["owner"]["source"], "deferred")
        self.assertEqual({d["by"] for d in decisions.values()}, {"autopilot"})
        outputs = statemod.load("f", self.tmp)["steps"]["ask"]["outputs"]
        self.assertEqual((outputs["assumption_count"], outputs["deferred_count"]), (1, 1))

    def test_modes_the_policy_does_not_list_still_ask(self):
        self.ctl("init", "--slug", "f", "--workflow", "ask.yaml", "--mode", "design")
        action = self.ctl("next", "--slug", "f")
        self.assertEqual(action["action"], "ask_interview")
        self.assertNotIn("autopilot", action)

    def test_assumption_log_lists_guesses_open_items_and_autopilot_gates(self):
        self.ctl("init", "--slug", "f", "--workflow", "ask.yaml", "--mode", "auto")
        self.ctl("next", "--slug", "f")
        state = statemod.load("f", self.tmp)
        state["gates"].append({"step": "release", "option": "approve", "auto": "auto",
                               "at": "2026-11-02T10:00:00Z"})
        state["gates"].append({"step": "prd", "option": "approve", "at": "2026-11-02T09:00:00Z"})
        statemod.save("f", state, self.tmp)
        out = io.StringIO()
        with redirect_stdout(out):
            assumptions.main(["render", "--root", self.tmp, "--slug", "f",
                              "--decisions", "ctx/demo-context.json",
                              "--decisions", "ctx/missing-context.json"])
        result = json.loads(out.getvalue())
        self.assertEqual(result["summary"], "1 assumption, 1 left open, 1 autopilot gate decision")
        with open(os.path.join(self.tmp, result["path"])) as fh:
            log = fh.read()
        self.assertIn("- **DEMO · Retention** (autopilot): Keep 30 days", log)
        self.assertIn("- **DEMO · Data owner** (autopilot): Left open on autopilot", log)
        self.assertIn("- release → approve (auto mode", log)
        self.assertNotIn("- prd →", log)  # a person's gate choice is not an assumption

    def test_empty_log_says_everything_was_confirmed(self):
        self.ctl("init", "--slug", "f", "--workflow", "ask.yaml")
        out = io.StringIO()
        with redirect_stdout(out):
            assumptions.main(["render", "--root", self.tmp, "--slug", "f"])
        result = json.loads(out.getvalue())
        self.assertEqual(result["assumption_count"], 0)
        with open(os.path.join(self.tmp, result["path"])) as fh:
            self.assertIn("confirmed by a person", fh.read())


class RunModeResolverTest(unittest.TestCase):
    def test_unknown_mode_is_refused(self):
        with self.assertRaises(resolver.RunError):
            resolver.init_run("f", "x.yaml", {}, ".", mode="fast")


class AutoPolicyValidationTest(unittest.TestCase):
    def test_interview_policy_takes_modes_and_when_only(self):
        node = {"id": "i", "type": "interview", "artifact": "x.json",
                "sections": [{"id": "a", "title": "A"}],
                "auto": {"modes": ["auto"], "option": "x"},
                "routes": [{"when": "${run.mode} == auto", "to": "end"}, {"to": "end"}]}
        errors = [i.msg for i in validate._validate_node(node, {"i": node}, set(), "w")
                  if i.level == "error"]
        self.assertEqual(errors, ["interview auto has unknown key 'option'"])

    def issues(self, auto):
        node = {"id": "g", "type": "gate", "prompt": "?", "auto": auto, "options": [
            {"id": "ok", "label": "OK", "to": "end"},
            {"id": "fix", "label": "Fix", "to": "end", "input": "feedback"},
            {"id": "no", "label": "No", "to": "abort"},
        ]}
        return [i.msg for i in validate._validate_node(node, {"g": node}, set(), "w")
                if i.level == "error"]

    def test_valid_policy(self):
        self.assertEqual(self.issues({"option": "ok", "modes": ["design"],
                                      "when": "${steps.g.outputs.choice} == ok"}), [])
        self.assertEqual(self.issues({"option": "ok", "when": [
            "${steps.g.outputs.choice} == ok", "${steps.g.outputs.done} == true"]}), [])

    def test_bad_policies(self):
        for auto, fragment in (
                ({"option": "missing"}, "is not an option"),
                ({"option": "fix"}, "must not need input"),
                ({"option": "no"}, "or abort"),
                ({"option": "ok", "modes": ["human"]}, "design/auto"),
                ({"option": "ok", "modes": []}, "design/auto"),
                ({"option": "ok", "when": "a === b"}, "auto.when"),
                ({"option": "ok", "when": ["${steps.g.outputs.choice} == ok", "a === b"]},
                 "auto.when"),
                ({"option": "ok", "when": []}, "list of conditions"),
                ({"option": "ok", "after": 1}, "unknown key"),
                ("ok", "must be a map")):
            with self.subTest(auto=auto):
                self.assertTrue(any(fragment in msg for msg in self.issues(auto)),
                                self.issues(auto))


if __name__ == "__main__":
    unittest.main()
