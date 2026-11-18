"""Regression tests for review findings in the resolver: a failed branch's question, claims,
single-pass substitution, on_exhausted cycles, rebase safety, empty-collection truthiness and
the reserved `slug` input."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import condctl  # noqa: E402
import resolver  # noqa: E402
import state as statemod  # noqa: E402
from test_resolver import PARALLEL_WF, Sim  # noqa: E402


class BranchFailAskTest(Sim):
    def test_the_question_is_asked_when_the_other_branch_finishes_first(self):
        self.start(self.write_wf("w.yaml", PARALLEL_WF % {"mode": "ask"}))
        action = self.fail_step("fanout[be]/s")
        self.assertEqual(action["synthesized"], "branch_fail")
        action = self.complete("fanout[fe]/s", {"note": "x"})
        # the join must wait for the person, not complete over the failed branch
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "fanout"))
        self.assertEqual(action["synthesized"], "branch_fail")
        self.assertNotEqual(self.state()["steps"]["fanout"]["status"], "done")
        action = self.gate("fanout", "skip")
        self.assertEqual((action["action"], action["step"]), ("run_agent", "after"))

    def test_retry_after_the_other_branch_finished(self):
        self.start(self.write_wf("w.yaml", PARALLEL_WF % {"mode": "ask"}))
        self.fail_step("fanout[be]/s")
        self.complete("fanout[fe]/s", {"note": "x"})
        action = self.gate("fanout", "retry")
        self.assertEqual((action["action"], action["step"]), ("run_agent", "fanout[be]/s"))
        action = self.complete("fanout[be]/s", {"note": "again"})
        self.assertEqual((action["action"], action["step"]), ("run_agent", "after"))

    def test_two_failed_branches_are_asked_one_after_the_other(self):
        wf = PARALLEL_WF % {"mode": "ask"}
        wf = wf.replace("            outputs: [note]\n            next: end\n    next: after",
                        "            outputs: [note]\n            on_fail: abort\n            retries: 0\n"
                        "            next: end\n    next: after")
        self.start(self.write_wf("w.yaml", wf))
        self.fail_step("fanout[be]/s")
        action = self.fail_step("fanout[fe]/s")
        self.assertEqual(action["synthesized"], "branch_fail")
        asked = [self.state()["steps"]["fanout"]["pending_ask"]["branch"]]
        action = self.gate("fanout", "skip")
        self.assertEqual(action["synthesized"], "branch_fail")  # the second one is still owed
        asked.append(self.state()["steps"]["fanout"]["pending_ask"]["branch"])
        self.assertEqual(sorted(asked), ["be", "fe"])
        action = self.gate("fanout", "skip")
        self.assertEqual((action["action"], action["step"]), ("run_agent", "after"))


class ClaimTest(Sim):
    WF = "version: 1\nname: c\nnodes:\n  - {id: work, instruction: Do., outputs: [note]}\n"

    def served(self):
        with statemod.locked("feat", self.tmp):
            run = self.run_obj()
            action = resolver.next_action(run, claim=True)
            statemod.save("feat", run.state, self.tmp)
        return action["claim"]

    def attempt(self, outputs, claim=None):
        run = self.run_obj()
        try:
            resolver.complete_step(run, "work", outputs=outputs, claim=claim)
        finally:
            statemod.save("feat", run.state, self.tmp)

    def test_a_refused_result_keeps_the_claim_so_a_stale_worker_is_still_refused(self):
        self.start(self.write_wf("c.yaml", self.WF))
        claim = self.served()
        with self.assertRaises(resolver.RunError):  # missing output field
            self.attempt({}, claim)
        self.assertEqual(self.state()["steps"]["work"]["claim_id"], claim)
        with self.assertRaises(resolver.RunError) as ctx:
            self.attempt({"note": "late"}, "0ldc1aim")
        self.assertIn("re-dispatched", str(ctx.exception))
        self.attempt({"note": "ok"}, claim)
        self.assertEqual(self.state()["steps"]["work"]["status"], "done")

    def test_a_result_without_the_claim_is_refused_while_one_is_held(self):
        self.start(self.write_wf("c.yaml", self.WF))
        claim = self.served()
        with self.assertRaises(resolver.RunError) as ctx:
            self.attempt({"note": "x"})
        self.assertIn("claim", str(ctx.exception))
        self.attempt({"note": "x"}, claim)

    def test_an_unclaimed_step_still_completes_without_one(self):
        self.start(self.write_wf("c.yaml", self.WF))  # served by peek / lead: never claimed
        self.attempt({"note": "x"})
        self.assertEqual(self.state()["steps"]["work"]["status"], "done")


class SinglePassSubstitutionTest(Sim):
    WF = """\
version: 1
name: sp
inputs:
  slug: {type: string, required: true}
  feedback: {type: string, default: ""}
  secret: {type: string, default: TOPSECRET}
  stack: {type: string, default: backend}
start: work
nodes:
  - id: work
    type: agent
    instruction: "fb=[${inputs.feedback}] stack=[${inputs.stack}] nested=[${inputs.stack}-review]"
    next: end
"""

    def test_a_substituted_value_is_not_expanded_again(self):
        wf = self.write_wf("s.yaml", self.WF)
        with statemod.locked("feat", self.tmp):
            resolver.init_run("feat", wf, {"feedback": "use ${inputs.secret} and ${steps.x.outputs.y}"},
                              self.tmp)
        prompt = self.nxt()["prompt"]
        self.assertIn("fb=[use ${inputs.secret} and ${steps.x.outputs.y}]", prompt)
        self.assertNotIn("TOPSECRET", prompt)
        self.assertIn("nested=[backend-review]", prompt)

    def test_nested_references_still_resolve(self):
        self.start(self.write_wf("s.yaml", self.WF))
        run = self.run_obj()
        self.assertEqual(run.resolve_text("${config.${inputs.stack}}", run.main_frame(),
                                          missing_ok=True), "")
        self.assertEqual(run.resolve_text("${inputs.${inputs.stack}}", run.main_frame(),
                                          missing_ok=True), "")


class ExhaustedCycleTest(Sim):
    WF = """\
version: 1
name: cyc
inputs:
  slug: {type: string, required: true}
start: a
nodes:
  - id: a
    instruction: A
    max_visits: 1
    on_exhausted: b
    routes:
      - {to: a}
  - id: b
    instruction: B
    max_visits: 1
    on_exhausted: a
    routes:
      - {to: a}
"""

    def test_two_nodes_pointing_at_each_other_end_in_the_ask_gate(self):
        self.start(self.write_wf("cyc.yaml", self.WF))
        action = self.complete("a")        # a again: over its cap, on_exhausted -> b (first visit)
        self.assertEqual((action["action"], action["step"]), ("run_agent", "b"))
        action = self.complete("b")        # a exhausted -> b exhausted -> back to a: stop and ask
        self.assertEqual((action["action"], action["synthesized"]), ("ask_gate", "exhausted"))


class RebaseTest(Sim):
    WF = ("version: 1\nname: r\nnodes:\n  - {id: a, instruction: A, next: b}\n"
          "  - {id: b, instruction: B}\n")

    def rebase(self):
        run = self.run_obj()
        resolver.rebase(run)
        statemod.save("feat", run.state, self.tmp)

    def test_removing_the_active_node_is_refused(self):
        rel = self.write_wf("r.yaml", self.WF)
        self.start(rel)
        self.complete("a")  # b is active
        self.write_wf("r.yaml", "version: 1\nname: r\nnodes:\n  - {id: a, instruction: A, next: end}\n")
        with self.assertRaises(resolver.RunError) as ctx:
            self.rebase()
        self.assertIn("'b'", str(ctx.exception))
        self.assertIn("cannot rebase", str(ctx.exception))

    def test_a_harmless_edit_still_rebases(self):
        rel = self.write_wf("r.yaml", self.WF)
        self.start(rel)
        self.complete("a")
        self.write_wf("r.yaml", self.WF.replace("B}", "B again}"))
        self.rebase()
        self.assertIn("B again", self.nxt()["prompt"])

    def test_removing_an_active_branch_step_is_refused(self):
        self.start(self.write_wf("w.yaml", PARALLEL_WF % {"mode": "ask"}))
        wf = PARALLEL_WF % {"mode": "ask"}
        fe = wf.index("      - id: fe\n")
        edited = wf[:fe] + wf[fe:].replace("start: s", "start: t").replace("- id: s", "- id: t", 1)
        self.assertNotEqual(edited, wf)
        self.write_wf("w.yaml", edited)
        with self.assertRaises(resolver.RunError) as ctx:
            self.rebase()
        self.assertIn("fanout[fe]/s", str(ctx.exception))


class TruthyTest(unittest.TestCase):
    def test_empty_collections_and_false_like_values_are_falsy(self):
        for value in ([], {}, (), None, "", "[]", "{}", "[ ]", "false", "False", "0", 0, False, "null"):
            self.assertFalse(condctl.truthy(value), repr(value))
        for value in ([0], {"a": 1}, "[1]", "x", 1, True, "yes"):
            self.assertTrue(condctl.truthy(value), repr(value))

    def test_a_placeholder_rendering_an_empty_list_is_false_in_a_route(self):
        subst = lambda text: json.dumps([])  # what resolve_text renders for an empty list output
        self.assertFalse(condctl.evaluate("${steps.x.outputs.items}", subst))
        self.assertTrue(condctl.evaluate("${steps.x.outputs.items}", lambda t: json.dumps([1])))


class ReservedSlugTest(Sim):
    WF = "version: 1\nname: s\ninputs:\n  slug: {type: string}\nnodes:\n  - {id: a, instruction: A}\n"

    def test_an_input_named_slug_cannot_override_the_run_slug(self):
        rel = self.write_wf("s.yaml", self.WF)
        with statemod.locked("feat", self.tmp):
            with self.assertRaises(resolver.RunError) as ctx:
                resolver.init_run("feat", rel, {"slug": "other-run"}, self.tmp)
        self.assertIn("slug", str(ctx.exception))
        with statemod.locked("feat", self.tmp):  # the same value is harmless
            state, _ = resolver.init_run("feat", rel, {"slug": "feat"}, self.tmp)
        self.assertEqual(state["inputs"]["slug"], "feat")


if __name__ == "__main__":
    unittest.main()
