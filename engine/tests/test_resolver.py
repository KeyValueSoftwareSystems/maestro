"""Resolver simulation suite — the engine's correctness proof.

Drives complete runs through the resolver with zero LLM: canned agent outputs, touched
artifact files, scripted gate decisions. Asserts the exact traversal, resume behaviour,
back-edge cascade resets, visit caps, parallel joins and failure modes.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import resolver  # noqa: E402
import state as statemod  # noqa: E402


BACKEDGE_WF = """\
version: 1
name: backedge
inputs:
  slug: {type: string, required: true}
defaults: {max_visits: 10}
start: work
nodes:
  - id: work
    type: agent
    instruction: Do work.
    outputs: [note]
    artifact: ".maestro/${inputs.slug}/work.md"
    next: review
  - id: review
    type: agent
    instruction: Review it.
    outputs: [blocking]
    max_visits: 2
    on_exhausted: escalate
    routes:
      - {when: "${steps.review.outputs.blocking} == true", to: work}
      - {to: end}
  - id: escalate
    type: gate
    prompt: Too many rounds.
    options:
      - {id: giveup, label: Give up, to: abort}
      - {id: ship, label: Ship anyway, to: end}
"""

PARALLEL_WF = """\
version: 1
name: par
inputs:
  slug: {type: string, required: true}
start: fanout
nodes:
  - id: fanout
    type: parallel
    join: all
    on_branch_fail: %(mode)s
    branches:
      - id: be
        start: s
        steps:
          - id: s
            type: agent
            instruction: BE.
            outputs: [note]
            on_fail: abort
            retries: 0
            next: end
      - id: fe
        start: s
        steps:
          - id: s
            type: agent
            instruction: FE.
            outputs: [note]
            next: end
    next: after
  - id: after
    type: agent
    instruction: "Join results: ${steps.fanout.branches.be.outputs.note}"
    outputs: [ok]
    next: end
"""

SUB_PARENT = """\
version: 1
name: parent
inputs:
  slug: {type: string, required: true}
start: child
nodes:
  - id: child
    type: subworkflow
    workflow: workflows/child.yaml
    inputs: {slug: "${inputs.slug}", flavor: vanilla}
    on_fail: ask
    next: after
  - id: after
    type: agent
    instruction: "Child said ${steps.child.outputs.verdict}"
    outputs: [ok]
    next: end
outputs:
  verdict: "${steps.child.outputs.verdict}"
"""

SUB_CHILD = """\
version: 1
name: child
inputs:
  slug: {type: string, required: true}
  flavor: {type: string, default: plain}
start: qa
nodes:
  - id: qa
    type: agent
    instruction: "QA ${inputs.flavor}."
    outputs: [verdict]
    retries: 0
    on_fail: abort
    next: end
outputs:
  verdict: "${steps.qa.outputs.verdict}"
"""

SCRIPT_WF = """\
version: 1
name: scripty
inputs:
  slug: {type: string, required: true}
start: probe
nodes:
  - id: probe
    type: script
    run: [echo, hi]
    retries: 1
    on_fail: cleanup
    routes:
      - {when: "${steps.probe.outputs.state} == go", to: end}
      - {to: cleanup}
  - id: cleanup
    type: script
    run: ["true"]
    next: end
"""


class Sim(unittest.TestCase):
    """Harness: tmp repo dir, helpers to drive a run without any LLM."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-sim-")
        os.makedirs(os.path.join(self.tmp, "workflows"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write_wf(self, name, text):
        path = os.path.join(self.tmp, "workflows", name)
        with open(path, "w") as fh:
            fh.write(text)
        return os.path.join("workflows", name)

    def start(self, wf_rel, slug="feat"):
        with statemod.locked(slug, self.tmp):
            resolver.init_run(slug, wf_rel, {}, self.tmp)
        return slug

    def run_obj(self, slug="feat"):
        return resolver.Run(slug, self.tmp)

    def nxt(self, slug="feat", serial=False):
        return resolver.next_action(self.run_obj(slug), serial=serial)

    def touch(self, rel):
        full = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write("content\n")

    def complete(self, step, outputs=None, exit_code=None, stdout=None, slug="feat"):
        run = self.run_obj(slug)
        resolver.complete_step(run, step, outputs=outputs, exit_code=exit_code, stdout=stdout)
        statemod.save(slug, run.state, self.tmp)
        return resolver.next_action(run)

    def gate(self, step, option, input_text=None, slug="feat"):
        run = self.run_obj(slug)
        resolver.record_gate(run, step, option, input_text=input_text)
        statemod.save(slug, run.state, self.tmp)
        return resolver.next_action(run)

    def fail_step(self, step, reason="boom", slug="feat"):
        run = self.run_obj(slug)
        resolver.fail_step(run, step, reason)
        statemod.save(slug, run.state, self.tmp)
        return resolver.next_action(run)

    def state(self, slug="feat"):
        return statemod.load(slug, self.tmp)


class BackEdgeTest(Sim):
    def drive_round(self, blocking):
        action = self.nxt()
        self.assertEqual((action["action"], action["step"]), ("run_agent", "work"))
        self.touch(".maestro/feat/work.md")
        action = self.complete("work", {"note": "did it"})
        self.assertEqual((action["action"], action["step"]), ("run_agent", "review"))
        return self.complete("review", {"blocking": blocking})

    def test_happy_path_no_loop(self):
        self.start(self.write_wf("w.yaml", BACKEDGE_WF))
        action = self.drive_round(False)
        self.assertEqual(action["action"], "done")

    def test_backedge_cascade_reset_and_visit_cap(self):
        self.start(self.write_wf("w.yaml", BACKEDGE_WF))
        # round 1 + 2: blocking -> back-edge to work (which resets work AND review)
        action = self.drive_round(True)
        self.assertEqual((action["action"], action["step"]), ("run_agent", "work"))
        st = self.state()
        # `review` sits upstream of `work` in the cycle (review -> work). Re-entering work
        # must NOT eagerly wipe it — that would destroy an input before it's regenerated.
        # It re-runs lazily when the flow reaches it again; its prior verdict survives.
        self.assertEqual(st["steps"]["review"]["outputs"], {"blocking": True})
        self.assertEqual(st["steps"]["work"]["visits"], 2)
        action = self.drive_round(True)
        # review has now been ENTERED twice (cap 2); after the next work pass, entering
        # review a third time exceeds max_visits -> on_exhausted routes to the gate
        self.touch(".maestro/feat/work.md")
        self.complete("work", {"note": "again"})
        action = self.nxt()
        self.assertEqual(action["action"], "ask_gate")
        self.assertEqual(action["step"], "escalate")
        action = self.gate("escalate", "ship")
        self.assertEqual(action["action"], "done")

    def test_gate_records_history(self):
        self.start(self.write_wf("w.yaml", BACKEDGE_WF))
        self.drive_round(True)
        self.drive_round(True)
        self.touch(".maestro/feat/work.md")
        self.complete("work", {"note": "x"})
        self.gate("escalate", "giveup")
        st = self.state()
        self.assertEqual(st["run"]["status"], "failed")
        self.assertEqual(st["gates"][-1]["option"], "giveup")


# An upstream producer feeds a loop (serve <-> ask); a later gate can revise back to the
# producer. Re-entering `serve` inside the loop must not cascade around the cycle and wipe
# the producer's outputs — the exact bug seen live (author_hld.hld_summary went null while
# the open-questions loop ran).
CASCADE_UPSTREAM_WF = """\
version: 1
name: cascade-upstream
inputs:
  slug: {type: string, required: true}
start: produce
nodes:
  - id: produce
    type: agent
    instruction: Produce the artifact.
    outputs: [summary]
    artifact: ".maestro/${inputs.slug}/out.md"
    next: serve
  - id: serve
    type: agent
    instruction: Decide what is next.
    outputs: [state]
    max_visits: 20
    routes:
      - {when: "${steps.serve.outputs.state} == ask", to: ask}
      - {to: approve}
  - id: ask
    type: gate
    prompt: A question.
    options:
      - {id: answer, label: Answer, to: serve}
  - id: approve
    type: gate
    prompt: Approve the produced artifact?
    options:
      - {id: ok, label: Approve, to: end}
      - {id: revise, label: Revise, to: produce}
"""


class CascadeUpstreamTest(Sim):
    def test_loop_reentry_preserves_upstream_outputs(self):
        self.start(self.write_wf("c2.yaml", CASCADE_UPSTREAM_WF))
        action = self.nxt()
        self.assertEqual(action["step"], "produce")
        self.touch(".maestro/feat/out.md")
        action = self.complete("produce", {"summary": "the HLD summary"})
        self.assertEqual(action["step"], "serve")
        action = self.complete("serve", {"state": "ask"})
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "ask"))
        # back-edge: ask -> serve. This re-enters serve mid-loop.
        action = self.gate("ask", "answer")
        self.assertEqual(action["step"], "serve")
        st = self.state()
        # THE REGRESSION: produce is upstream of serve; its output must be intact.
        self.assertEqual(st["steps"]["produce"]["outputs"], {"summary": "the HLD summary"})
        self.assertEqual(st["steps"]["produce"]["status"], "done")
        # serve itself did re-run (reset on re-entry)
        self.assertEqual(st["steps"]["serve"]["visits"], 2)

    def test_revise_regenerates_downstream(self):
        # The other direction: revising back to `produce` DOES reset the true downstream.
        self.start(self.write_wf("c2.yaml", CASCADE_UPSTREAM_WF))
        self.nxt()
        self.touch(".maestro/feat/out.md")
        self.complete("produce", {"summary": "v1"})
        self.complete("serve", {"state": "approve"})
        action = self.gate("approve", "revise")
        # re-enters produce; it must be pending again (regenerate)
        self.assertEqual(action["step"], "produce")
        st = self.state()
        self.assertEqual(st["steps"]["produce"]["status"], "pending")
        self.assertEqual(st["steps"]["produce"]["outputs"], {})


class ArtifactTest(Sim):
    def test_complete_refuses_missing_artifact(self):
        self.start(self.write_wf("w.yaml", BACKEDGE_WF))
        run = self.run_obj()
        with self.assertRaises(resolver.RunError) as ctx:
            resolver.complete_step(run, "work", outputs={"note": "x"})
        self.assertEqual(ctx.exception.code, 4)
        self.assertIn("artifact", str(ctx.exception))

    def test_complete_refuses_missing_output_field(self):
        self.start(self.write_wf("w.yaml", BACKEDGE_WF))
        self.touch(".maestro/feat/work.md")
        run = self.run_obj()
        with self.assertRaises(resolver.RunError) as ctx:
            resolver.complete_step(run, "work", outputs={"wrong": "x"})
        self.assertIn("note", str(ctx.exception))

    def test_complete_refuses_inactive_step(self):
        self.start(self.write_wf("w.yaml", BACKEDGE_WF))
        run = self.run_obj()
        with self.assertRaises(resolver.RunError):
            resolver.complete_step(run, "review", outputs={"blocking": False})


class FailureTest(Sim):
    def test_retry_then_ask_then_skip(self):
        self.start(self.write_wf("w.yaml", BACKEDGE_WF))
        # default retries=1: first fail -> re-serve
        action = self.fail_step("work")
        self.assertEqual((action["action"], action["step"]), ("run_agent", "work"))
        # second fail -> synthesized ask gate
        action = self.fail_step("work")
        self.assertEqual(action["action"], "ask_gate")
        self.assertEqual(action["synthesized"], "fail")
        option_ids = {o["id"] for o in action["options"]}
        self.assertEqual(option_ids, {"retry", "skip", "abort"})
        # skip -> default route (review)
        action = self.gate("work", "skip")
        self.assertEqual((action["action"], action["step"]), ("run_agent", "review"))
        self.assertEqual(self.state()["steps"]["work"]["status"], "skipped")

    def test_retry_resets_attempts(self):
        self.start(self.write_wf("w.yaml", BACKEDGE_WF))
        self.fail_step("work")
        self.fail_step("work")
        action = self.gate("work", "retry")
        self.assertEqual((action["action"], action["step"]), ("run_agent", "work"))
        self.assertEqual(self.state()["steps"]["work"]["attempts"], 0)

    def test_abort(self):
        self.start(self.write_wf("w.yaml", BACKEDGE_WF))
        self.fail_step("work")
        self.fail_step("work")
        action = self.gate("work", "abort")
        self.assertEqual(action["action"], "failed")


class ScriptTest(Sim):
    def test_script_outputs_route(self):
        self.start(self.write_wf("w.yaml", SCRIPT_WF))
        action = self.nxt()
        self.assertEqual(action["action"], "run_script")
        self.assertEqual(action["argv"], ["echo", "hi"])
        action = self.complete("probe", exit_code=0, stdout='{"state": "go"}')
        self.assertEqual(action["action"], "done")

    def test_script_default_route(self):
        self.start(self.write_wf("w.yaml", SCRIPT_WF))
        action = self.complete("probe", exit_code=0, stdout="not json")
        self.assertEqual((action["action"], action["step"]), ("run_script", "cleanup"))

    def test_script_failure_retries_then_on_fail(self):
        self.start(self.write_wf("w.yaml", SCRIPT_WF))
        action = self.complete("probe", exit_code=2, stdout="err")
        self.assertEqual((action["action"], action["step"]), ("run_script", "probe"))  # retry 1
        action = self.complete("probe", exit_code=2, stdout="err")
        self.assertEqual((action["action"], action["step"]), ("run_script", "cleanup"))  # on_fail


class ParallelTest(Sim):
    def test_join_all_and_batch(self):
        self.start(self.write_wf("w.yaml", PARALLEL_WF % {"mode": "fail_all"}))
        action = self.nxt()
        self.assertEqual(action["action"], "run_agents")
        steps = {a["step"] for a in action["agents"]}
        self.assertEqual(steps, {"fanout[be]/s", "fanout[fe]/s"})
        # serial mode serves one at a time
        action = self.nxt(serial=True)
        self.assertEqual(action["action"], "run_agent")
        # complete both; branch outputs surface on the parallel node
        self.complete("fanout[be]/s", {"note": "be-note"})
        action = self.complete("fanout[fe]/s", {"note": "fe-note"})
        self.assertEqual((action["action"], action["step"]), ("run_agent", "after"))
        self.assertIn("be-note", action["prompt"])
        action = self.complete("after", {"ok": "y"})
        self.assertEqual(action["action"], "done")

    def test_branch_fail_fail_all(self):
        self.start(self.write_wf("w.yaml", PARALLEL_WF % {"mode": "fail_all"}))
        action = self.fail_step("fanout[be]/s")  # retries=0, on_fail=abort -> branch aborts
        # parallel on_fail defaults to ask -> synthesized gate on the parallel node
        self.assertEqual(action["action"], "ask_gate")
        self.assertEqual(action["step"], "fanout")
        self.assertEqual(action["synthesized"], "fail")
        st = self.state()
        self.assertEqual(st["steps"]["fanout"]["branches"]["be"]["status"], "failed")

    def test_branch_fail_continue(self):
        self.start(self.write_wf("w.yaml", PARALLEL_WF % {"mode": "continue"}))
        self.fail_step("fanout[be]/s")
        action = self.complete("fanout[fe]/s", {"note": "fe"})
        # be failed but mode=continue: join completes when all terminal
        self.assertEqual((action["action"], action["step"]), ("run_agent", "after"))

    def test_branch_fail_ask_retry(self):
        self.start(self.write_wf("w.yaml", PARALLEL_WF % {"mode": "ask"}))
        action = self.fail_step("fanout[be]/s")
        self.assertEqual(action["action"], "ask_gate")
        self.assertEqual(action["synthesized"], "branch_fail")
        action = self.gate("fanout", "retry")
        # be branch reset and re-served (fe still pending too -> batch)
        st = self.state()
        self.assertEqual(st["steps"]["fanout"]["branches"]["be"]["status"], "running")
        steps = {a["step"] for a in action["agents"]} if action["action"] == "run_agents" else {action["step"]}
        self.assertIn("fanout[be]/s", steps)


class SubworkflowTest(Sim):
    def setUp(self):
        super().setUp()
        self.write_wf("child.yaml", SUB_CHILD)
        self.parent = self.write_wf("parent.yaml", SUB_PARENT)

    def test_child_outputs_surface(self):
        self.start(self.parent)
        action = self.nxt()
        self.assertEqual((action["action"], action["step"]), ("run_agent", "child/qa"))
        self.assertIn("QA vanilla.", action["prompt"])  # child default overridden by parent input
        action = self.complete("child/qa", {"verdict": "pass"})
        self.assertEqual((action["action"], action["step"]), ("run_agent", "after"))
        self.assertIn("Child said pass", action["prompt"])
        action = self.complete("after", {"ok": "y"})
        self.assertEqual(action["action"], "done")
        self.assertEqual(action["outputs"]["verdict"], "pass")

    def test_child_abort_hits_parent_on_fail(self):
        self.start(self.parent)
        action = self.fail_step("child/qa")  # retries=0, on_fail=abort -> child aborts
        self.assertEqual(action["action"], "ask_gate")
        self.assertEqual(action["step"], "child")
        action = self.gate("child", "retry")
        self.assertEqual((action["action"], action["step"]), ("run_agent", "child/qa"))


class ResumeTest(Sim):
    def test_next_is_idempotent(self):
        self.start(self.write_wf("w.yaml", BACKEDGE_WF))
        a1, a2 = self.nxt(), self.nxt()
        self.assertEqual(a1, a2)

    def test_reinit_is_noop(self):
        rel = self.write_wf("w.yaml", BACKEDGE_WF)
        self.start(rel)
        self.touch(".maestro/feat/work.md")
        self.complete("work", {"note": "x"})
        data, created = resolver.init_run("feat", rel, {}, self.tmp)
        self.assertFalse(created)
        self.assertEqual(self.nxt()["step"], "review")

    def test_workflow_edit_halts_until_rebase(self):
        rel = self.write_wf("w.yaml", BACKEDGE_WF)
        self.start(rel)
        with open(os.path.join(self.tmp, rel), "a") as fh:
            fh.write("# edited\n")
        with self.assertRaises(resolver.RunError) as ctx:
            self.nxt()
        self.assertEqual(ctx.exception.code, 3)
        self.assertIn("changed", str(ctx.exception))
        run = resolver.Run("feat", self.tmp)
        # rebase must not verify the stale hash while re-hashing
        run.state["workflow"]["sha256"] = None
        resolver.rebase(run)
        statemod.save("feat", run.state, self.tmp)
        self.assertEqual(self.nxt()["step"], "work")

    def test_reset_cascade(self):
        self.start(self.write_wf("w.yaml", BACKEDGE_WF))
        self.touch(".maestro/feat/work.md")
        self.complete("work", {"note": "x"})
        run = self.run_obj()
        resolver.reset_steps(run, ["work"], cascade=True)
        statemod.save("feat", run.state, self.tmp)
        st = self.state()
        self.assertEqual(st["steps"]["work"]["status"], "pending")
        self.assertEqual(self.nxt()["step"], "work")

    def test_reset_all(self):
        self.start(self.write_wf("w.yaml", BACKEDGE_WF))
        self.touch(".maestro/feat/work.md")
        self.complete("work", {"note": "x"})
        run = self.run_obj()
        resolver.reset_all(run)
        statemod.save("feat", run.state, self.tmp)
        st = self.state()
        self.assertEqual(st["run"]["cursors"], ["work"])
        self.assertEqual(st["steps"]["work"]["visits"], 1)


class GateInputTest(Sim):
    def test_option_input_required_and_exposed(self):
        wf_text = """\
version: 1
name: g
inputs:
  slug: {type: string, required: true}
start: ask
nodes:
  - id: ask
    type: gate
    prompt: Feedback?
    options:
      - {id: give, label: Give feedback, to: use, input: feedback}
  - id: use
    type: agent
    instruction: "Apply: ${steps.ask.outputs.feedback}"
    outputs: [ok]
    next: end
"""
        self.start(self.write_wf("w.yaml", wf_text))
        run = self.run_obj()
        with self.assertRaises(resolver.RunError):
            resolver.record_gate(run, "ask", "give")  # missing input text
        action = self.gate("ask", "give", input_text="tighten scope")
        self.assertIn("Apply: tighten scope", action["prompt"])


SELF_EXHAUST_WF = """\
version: 1
name: self-exhaust
inputs:
  slug: {type: string, required: true}
start: loop
nodes:
  - id: loop
    type: agent
    instruction: Spin.
    outputs: [again]
    max_visits: 1
    on_exhausted: loop
    routes:
      - {to: loop}
"""

CONTAINER_WF = """\
version: 1
name: container
inputs:
  slug: {type: string, required: true}
start: fan
nodes:
  - id: fan
    type: parallel
    join: all
    branches:
      - id: a
        start: a1
        steps:
          - id: a1
            type: agent
            instruction: Do A.
            outputs: [ok]
            next: end
      - id: b
        start: b1
        steps:
          - id: b1
            type: agent
            instruction: Do B.
            outputs: [ok]
            next: end
    next: done_step
  - id: done_step
    type: agent
    instruction: Wrap up.
    outputs: [ok]
    next: end
"""


class EngineGuardsTest(Sim):
    def test_slug_traversal_rejected(self):
        rel = self.write_wf("w.yaml", BACKEDGE_WF)
        for bad in ("../evil", "a/b", "..", "UPPER", "-lead"):
            with self.assertRaises(resolver.RunError) as ctx:
                resolver.init_run(bad, rel, {}, self.tmp)
            self.assertEqual(ctx.exception.code, 3)
            self.assertIn("slug", str(ctx.exception).lower())

    def test_non_scalar_output_rejected(self):
        self.start(self.write_wf("w.yaml", BACKEDGE_WF))
        self.touch(".maestro/feat/work.md")
        run = self.run_obj()
        with self.assertRaises(resolver.RunError) as ctx:
            resolver.complete_step(run, "work", outputs={"note": ["a", "b"]})
        self.assertEqual(ctx.exception.code, 4)
        self.assertIn("scalar", str(ctx.exception))

    def test_on_exhausted_self_loop_does_not_recurse(self):
        self.start(self.write_wf("w.yaml", SELF_EXHAUST_WF))
        # entering `loop` the 2nd time exceeds max_visits 1; on_exhausted -> loop (self)
        # must synthesize the loop-limit gate, not recurse forever.
        action = self.complete("loop", {"again": True})
        self.assertEqual(action["action"], "ask_gate")
        self.assertEqual(action.get("synthesized"), "exhausted")

    def test_reset_container_node_does_not_brick_next(self):
        self.start(self.write_wf("w.yaml", CONTAINER_WF))
        # finish the parallel wave
        self.touch(".maestro/feat/x")
        resolver_run = self.run_obj()
        wave = resolver.next_action(resolver_run)
        self.assertEqual(wave["action"], "run_agents")
        self.complete("fan[a]/a1", {"ok": True})
        self.complete("fan[b]/b1", {"ok": True})
        # now reset the parallel container itself
        run = self.run_obj()
        resolver.reset_steps(run, ["fan"])
        statemod.save("feat", run.state, self.tmp)
        # next_action must re-serve the branches, not raise "unexpected parallel node"
        action = resolver.next_action(self.run_obj())
        self.assertEqual(action["action"], "run_agents")

    def test_resolved_skill_name_in_prompt(self):
        wf_text = """\
version: 1
name: skillpin
inputs:
  slug: {type: string, required: true}
  stack: {type: string, default: backend}
start: build
nodes:
  - id: build
    type: agent
    instruction: Build it.
    skill: "${inputs.stack}-implement"
    outputs: [ok]
    next: end
"""
        self.start(self.write_wf("w.yaml", wf_text))
        action = self.nxt()
        self.assertEqual(action["skill"], "backend-implement")
        # the rendered prompt must name the RESOLVED skill and not leak the placeholder
        # or a pack-only skills/<name>/SKILL.md path
        self.assertIn("backend-implement", action["prompt"])
        self.assertNotIn("${inputs.stack}", action["prompt"])
        self.assertNotIn("skills/backend-implement/SKILL.md", action["prompt"])


class NestedPlaceholderTest(Sim):
    NESTED_WF = """\
version: 1
name: nested
inputs:
  slug: {type: string, required: true}
  stack: {type: string, default: backend}
start: work
nodes:
  - id: work
    type: agent
    instruction: "flat=${inputs.stack} nested=[${inputs.stack}-review]"
    outputs: [note]
    artifact: ".maestro/${inputs.slug}/work.md"
    next: end
"""

    def test_flat_placeholder_unchanged(self):
        self.start(self.write_wf("n.yaml", self.NESTED_WF))
        prompt = self.nxt()["prompt"]
        self.assertIn("flat=backend", prompt)
        self.assertIn("nested=[backend-review]", prompt)

    def test_bounded_loop_terminates(self):
        self.start(self.write_wf("n.yaml", self.NESTED_WF))
        run = self.run_obj()
        frame = run.main_frame()
        self.assertEqual(run.resolve_text("${inputs.stack}", frame), "backend")


class MemoryInjectionTest(Sim):
    MEM_WF = """\
version: 1
name: mem
inputs:
  slug: {type: string, required: true}
  stack: {type: string, default: backend}
start: work
nodes:
  - id: work
    type: agent
    instruction: Do the ${inputs.stack} work.
    inputs:
      general: "${memory.knowledge.codebase}"
      scoped: "${memory.knowledge.${inputs.stack}-review}"
      absent: "${memory.knowledge.nope}"
    outputs: [note]
    artifact: ".maestro/${inputs.slug}/work.md"
    next: end
"""

    def seed(self, domain, text):
        d = os.path.join(self.tmp, ".maestro", "memory", "knowledge")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, domain + ".md"), "w") as fh:
            fh.write(text)

    def test_injected_shared_nested_and_absent(self):
        self.seed("codebase", "SHARED-LESSON")
        self.seed("backend-review", "BE-REVIEW-LESSON")
        self.start(self.write_wf("m.yaml", self.MEM_WF))
        action = self.nxt()
        self.assertEqual(action["action"], "run_agent")
        prompt = action["prompt"]
        self.assertIn("SHARED-LESSON", prompt)          # ${memory.knowledge.codebase}
        self.assertIn("BE-REVIEW-LESSON", prompt)       # nested per-stack key
        self.assertNotIn("${memory", prompt)            # no leftover placeholder
        self.assertIn("absent:", prompt)                # absent domain -> blank value

    def test_frozen_at_init(self):
        self.seed("codebase", "ORIGINAL")
        self.start(self.write_wf("m.yaml", self.MEM_WF))
        self.seed("codebase", "CHANGED-AFTER-INIT")     # mutate the live store post-init
        prompt = self.nxt()["prompt"]
        self.assertIn("ORIGINAL", prompt)
        self.assertNotIn("CHANGED-AFTER-INIT", prompt)

    def test_snapshot_recorded_in_state(self):
        self.seed("codebase", "X")
        self.start(self.write_wf("m.yaml", self.MEM_WF))
        st = self.state()
        self.assertEqual(st["memory"]["snapshot"], "memory-snapshot.json")
        self.assertTrue(st["memory"]["sha256"])


if __name__ == "__main__":
    unittest.main()
