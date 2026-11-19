"""A gate option with `pause: true` ("approve later") and the node `say:` line.

Pausing leaves the gate unanswered: `next` reports the run paused and serves nothing else until a
resume (`init` on the slug) clears it, then the same question is asked again. Every served step
carries one plain `say` line: the node's `say:`, else its label."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import resolver  # noqa: E402
import state as statemod  # noqa: E402
import todo as todomod  # noqa: E402
import validate as validatemod  # noqa: E402
import wf  # noqa: E402

PAUSE_WF = """\
version: 1
name: pausing
inputs:
  slug: {type: string, required: true}
start: write
nodes:
  - id: write
    type: agent
    label: Write the plan
    say: "Writing the plan for ${inputs.slug}."
    instruction: Write it.
    outputs: [note]
    next: approval
  - id: approval
    type: gate
    label: Plan approval
    prompt: Approve the plan?
    options:
      - {id: approve, label: Approve, to: after}
      - {id: later, label: Approve later, pause: true}
      - {id: reject, label: Reject, to: abort}
  - id: after
    type: script
    run: ["true"]
    next: end
"""


class PauseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-pause-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        os.makedirs(os.path.join(self.tmp, "workflows"))
        self.rel = os.path.join("workflows", "w.yaml")
        with open(os.path.join(self.tmp, self.rel), "w") as fh:
            fh.write(PAUSE_WF)
        resolver.init_run("feat", self.rel, {}, self.tmp)

    def run_obj(self):
        return resolver.Run("feat", self.tmp)

    def nxt(self):
        return resolver.next_action(self.run_obj())

    def to_gate(self):
        run = self.run_obj()
        resolver.complete_step(run, "write", outputs={"note": "x"})
        statemod.save("feat", run.state, self.tmp)

    def gate(self, option):
        run = self.run_obj()
        resolver.record_gate(run, "approval", option)
        statemod.save("feat", run.state, self.tmp)
        return resolver.next_action(run)

    def test_say_and_label_fallback(self):
        action = self.nxt()
        self.assertEqual(action["action"], "run_agent")
        self.assertEqual(action["say"], "Writing the plan for feat.")
        self.to_gate()
        action = self.nxt()
        self.assertEqual(action["action"], "ask_gate")
        self.assertEqual(action["say"], "Plan approval")
        self.assertEqual([o.get("pause") for o in action["options"]], [None, True, None])

    def test_pause_holds_the_gate_and_resume_asks_again(self):
        self.to_gate()
        action = self.gate("later")
        self.assertEqual(action, {"action": "paused", "step": "approval",
                                  "resume": "/maestro feat", "say": "Plan approval"})
        entry = statemod.load("feat", self.tmp)["steps"]["approval"]
        self.assertEqual(entry["paused"]["option"], "later")
        self.assertNotEqual(entry.get("status"), "done")
        self.assertEqual(entry.get("outputs") or {}, {})
        # still paused on another `next`, and autopilot answers nothing
        self.assertEqual(self.nxt()["action"], "paused")
        self.assertEqual(resolver.apply_autopilot(self.run_obj()), [])
        # the todo list shows it waiting on the person
        todo = todomod.build(self.run_obj())
        self.assertIn("Plan approval (paused)", todomod.render(todo))
        runs = statemod.list_runs(self.tmp)
        self.assertTrue(runs[0]["paused"])
        self.assertEqual(runs[0]["paused_at"], ["approval"])
        # resume: init on the slug clears the pause, the same question is served again
        data, created = resolver.init_run("feat", self.rel, {}, self.tmp)
        self.assertFalse(created)
        statemod.save("feat", data, self.tmp)
        self.assertNotIn("paused", statemod.load("feat", self.tmp)["steps"]["approval"])
        action = self.nxt()
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "approval"))
        action = self.gate("approve")
        self.assertEqual((action["action"], action["step"]), ("run_script", "after"))


class ValidateTest(unittest.TestCase):
    def issues(self, text):
        return validatemod.validate_doc(wf.loads(text))

    def codes(self, text, level=None):
        return [i.code for i in self.issues(text) if level is None or i.level == level]

    def test_pause_option_needs_no_route(self):
        self.assertEqual(self.codes(PAUSE_WF, "error"), [])

    def test_pause_option_takes_no_route_or_input(self):
        text = PAUSE_WF.replace("{id: later, label: Approve later, pause: true}",
                                "{id: later, label: Approve later, pause: true, to: after}")
        self.assertIn("gate-pause-option", self.codes(text, "error"))

    def test_autopilot_never_pauses(self):
        text = PAUSE_WF.replace("      - {id: reject, label: Reject, to: abort}\n",
                                "      - {id: reject, label: Reject, to: abort}\n"
                                "    auto: {option: later}\n")
        self.assertIn("gate-pause-option", self.codes(text, "error"))

    def test_option_without_to_and_without_pause_is_still_an_error(self):
        text = PAUSE_WF.replace("{id: later, label: Approve later, pause: true}",
                                "{id: later, label: Approve later}")
        self.assertIn("missing-key", self.codes(text, "error"))

    def test_say_lint(self):
        long = PAUSE_WF.replace('say: "Writing the plan for ${inputs.slug}."',
                                "say: " + "x" * 120)
        self.assertEqual(self.codes(long, "warning"), ["say-style"])
        internal = PAUSE_WF.replace('say: "Writing the plan for ${inputs.slug}."',
                                    'say: "Plan ${steps.write.outputs.note}"')
        self.assertIn("say-style", self.codes(internal, "warning"))
        self.assertEqual(self.codes(internal, "error"), [])


if __name__ == "__main__":
    unittest.main()
