"""Full-pipeline simulation: drives the REAL shipped workflows (sdlc-main.yaml +
design/impl/qa subworkflows) through the engine with zero LLM — canned agent outputs,
scripted gate decisions, artifacts touched on disk. This is the proof that the example
pack and the engine agree."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import resolver  # noqa: E402
import state as statemod  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def canned_agent_outputs(step, action):
    """Outputs by node id — mirrors each node's declared outputs list."""
    node = step.rsplit("/", 1)[-1]
    table = {
        "brainstorm_draft": {"draft_summary": "PRD drafted; 0 open questions"},
        "rq_fold": {"refined_summary": "folded 1 answer"},
        "author_hld": {"hld_summary": "3 services, 2 new tables"},
        "refine_hld": {"refined_summary": "folded 1 answer"},
        "backend_design": {"lld_path": "lld/backend.md", "contract_notes": "rest+cursor"},
        "frontend_design": {"lld_path": "lld/frontend.md", "contract_notes": "uses GET /searches"},
        "contract": {"contract_summary": "5 endpoints"},
        "test_cases": {"test_cases_path": "test-cases.md", "case_count": 12},
        "arch_review": {"review_path": "reviews/architecture.md", "blocking": False,
                        "summary": "sound"},
        "tasks": {"task_count": 4, "slice_count": 2},
        "implement": {"branch": "feature/x", "summary": "built", "tests_passed": True},
        "review": {"review_path": "reviews/summary.md", "blocking": False, "summary": "clean"},
        "fix": {"fix_summary": "fixed", "checks_passed": True},
        "qa_run": {"passed": True, "failed_count": 0, "summary": "all green"},
        "review_pack": {"pack_path": "review-pack.md", "recommendation": "ready",
                        "summary": "ready"},
        "retrospect": {"incoming_path": ".maestro/memory/incoming/demo.json",
                       "lessons_count": 2, "summary": "distilled"},
    }
    outputs = dict(table[node])
    # sanity: canned outputs must cover everything the node declares
    missing = [f for f in action.get("outputs", []) if f not in outputs]
    assert not missing, f"{step}: canned outputs missing {missing}"
    return outputs


def canned_script(step):
    node = step.rsplit("/", 1)[-1]
    if node == "oq_serve":
        return 0, json.dumps({"state": "approve"})
    if node == "assert_requirement":
        # setUp populates the requirement folder -> the "have" path (author the HLD).
        return 0, json.dumps({"state": "have"})
    return 0, "ok"


class SdlcE2E(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-e2e-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # the run root needs the real workflows + engine helpers + config
        shutil.copytree(os.path.join(REPO, "workflows"), os.path.join(self.tmp, ".maestro", "workflows"))
        shutil.copytree(os.path.join(REPO, "engine"), os.path.join(self.tmp, ".maestro", "engine"),
                        ignore=shutil.ignore_patterns("tests", "__pycache__"))
        req = os.path.join(self.tmp, ".maestro", "runs", "demo", "requirement")
        os.makedirs(req)
        with open(os.path.join(req, "requirement.md"), "w") as fh:
            fh.write("Build the demo feature.\n")

    # -- driver ----------------------------------------------------------

    def drive(self, gate_script, max_steps=200, agent_overrides=None):
        """Run the pipeline: gate_script maps step path -> list of (option, input) taken
        in order. Returns (final_action, trace)."""
        trace = []
        gate_ptr = {}
        overrides = agent_overrides or {}
        with statemod.locked("demo", self.tmp):
            resolver.init_run("demo", ".maestro/workflows/sdlc-main.yaml", {"feature": "Demo"}, self.tmp)
        for _ in range(max_steps):
            run = resolver.Run("demo", self.tmp)
            action = resolver.next_action(run)
            kind = action["action"]
            if kind in ("done", "failed"):
                return action, trace
            if kind == "run_agents":
                batch = action["agents"]
            else:
                batch = [action]
            for act in batch:
                step = act["step"]
                trace.append((act["action"], step))
                run = resolver.Run("demo", self.tmp)
                if act["action"] == "run_agent":
                    for rel in act.get("artifacts", []):
                        full = os.path.join(self.tmp, rel)
                        os.makedirs(os.path.dirname(full), exist_ok=True)
                        if not os.path.exists(full):  # keep prepped fixtures intact
                            with open(full, "w") as fh:
                                fh.write("artifact\n")
                    node = step.rsplit("/", 1)[-1]
                    outputs = overrides.get(node) or canned_agent_outputs(step, act)
                    resolver.complete_step(run, step, outputs=outputs)
                elif act["action"] == "run_script":
                    # actually run the real script where it's an engine helper; stub others
                    if ("oq_serve" in step or "validate_tasks" in step
                            or any("mem_consolidate" in a for a in act.get("argv", []))):
                        proc = subprocess.run(act["argv"], cwd=self.tmp, capture_output=True,
                                              text=True, timeout=30)
                        code, out = proc.returncode, proc.stdout
                    else:
                        code, out = canned_script(step)
                    resolver.complete_step(run, step, exit_code=code, stdout=out)
                elif act["action"] == "ask_gate":
                    decisions = gate_script.get(step)
                    self.assertTrue(decisions, f"unscripted gate: {step} ({act['prompt'][:80]})")
                    i = gate_ptr.get(step, 0)
                    self.assertLess(i, len(decisions), f"gate {step} asked more than scripted")
                    option, text = decisions[i]
                    gate_ptr[step] = i + 1
                    resolver.record_gate(run, step, option, input_text=text)
                statemod.save("demo", run.state, self.tmp)
        self.fail("pipeline did not terminate within max_steps")

    def prep_tasks_json(self):
        """The real validate_tasks.py runs against the artifact the tasks agent 'wrote' —
        write a minimally valid tasks.json for both stacks up front."""
        for stack in ("backend", "frontend"):
            doc = {
                "schema_version": 1, "stack": stack, "feature_slug": "demo",
                "context_manifest": {"read_once": ["hld"], "reference": []},
                "slices": [{"group_id": "g1", "task_ids": ["t1"]}],
                "tasks": [{"id": "t1", "group_id": "g1", "title": "do it",
                           "depends_on": [], "reads": [], "writes": [f"src/{stack}/x"],
                           "test": "unit", "standards": [], "needs_human_gate": False}],
            }
            path = os.path.join(self.tmp, ".maestro", "runs", "demo", stack, "tasks.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                json.dump(doc, fh)

    # -- scenarios ---------------------------------------------------------

    def test_happy_path(self):
        self.prep_tasks_json()
        gates = {
            "design/collect_references": [("none", None)],
            "design/prd_approval": [("approve", None)],
            "design/hld_approval": [("approve", None)],
            "contract_approval": [("approve", None)],
            "release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        self.assertEqual(action["outputs"]["hld"], ".maestro/runs/demo/hld.md")
        self.assertEqual(action["outputs"]["backend_branch"], "feature/x")
        steps = [s for _, s in trace]
        # both stacks implemented through the nested subworkflow-in-branch
        self.assertIn("implement[backend]/impl/implement", steps)
        self.assertIn("implement[frontend]/impl/review", steps)
        # the PRD phase always runs (even with a requirement already present) before the HLD
        self.assertIn("design/brainstorm_draft", steps)
        self.assertLess(steps.index("design/brainstorm_draft"), steps.index("design/author_hld"))
        # design ran before implementation, qa after
        self.assertLess(steps.index("design/author_hld"), steps.index("arch_review"))
        self.assertLess(steps.index("merge_for_test"), steps.index("qa/qa_run"))

    def test_revise_cascade_from_contract_gate(self):
        self.prep_tasks_json()
        gates = {
            "design/collect_references": [("none", None), ("none", None)],
            "design/prd_approval": [("approve", None), ("approve", None)],
            "design/hld_approval": [("approve", None), ("approve", None)],
            "contract_approval": [("revise", "tighten the API"), ("approve", None)],
            "release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        # design phase ran twice end-to-end
        self.assertEqual(steps.count("design/author_hld"), 2)
        self.assertEqual(steps.count("design/contract"), 2)

    def test_revise_cascade_from_prd_gate(self):
        """Revising at the PRD approval gate re-enters brainstorm_draft, whose cascade-reset
        re-runs the whole PRD/Q&A phase before it is confirmed again and the HLD is authored."""
        self.prep_tasks_json()
        gates = {
            "design/collect_references": [("none", None)],
            "design/prd_approval": [("revise", "sharpen the scope"), ("approve", None)],
            "design/hld_approval": [("approve", None)],
            "contract_approval": [("approve", None)],
            "release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        # PRD authored twice (revise looped back), HLD authored once (revise was before it)
        self.assertEqual(steps.count("design/brainstorm_draft"), 2)
        self.assertEqual(steps.count("design/author_hld"), 1)

    def test_blocking_arch_review_gate_waive(self):
        self.prep_tasks_json()
        gates = {
            "design/collect_references": [("none", None)],
            "design/prd_approval": [("approve", None)],
            "design/hld_approval": [("approve", None)],
            "arch_gate": [("waive", None)],
            "contract_approval": [("approve", None)],
            "release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates, agent_overrides={
            "arch_review": {"review_path": "r.md", "blocking": True, "summary": "risky"},
        })
        self.assertEqual(action["action"], "done", action)
        self.assertIn("arch_gate", [s for a, s in trace if a == "ask_gate"])

    def test_fix_cycle_runs_when_review_blocks(self):
        self.prep_tasks_json()
        # review blocks once per stack, then fix runs and review passes (per-stack
        # sequencing is per-branch, so use a stateful override)
        review_calls = {}

        class ReviewOverride(dict):
            def __missing__(self, key):
                raise KeyError(key)

        overrides = {}

        def review_outputs():
            n = review_calls.get("n", 0)
            review_calls["n"] = n + 1
            blocking = n < 2  # first review of each stack blocks
            return {"review_path": "reviews/summary.md", "blocking": blocking,
                    "summary": "found issues" if blocking else "clean"}

        # wrap: agent_overrides values are static dicts, so patch canned table instead
        orig = canned_agent_outputs

        def patched(step, action):
            if step.rsplit("/", 1)[-1] == "review":
                out = review_outputs()
                missing = [f for f in action.get("outputs", []) if f not in out]
                assert not missing
                return out
            return orig(step, action)

        globals()["canned_agent_outputs"] = patched
        try:
            gates = {
                "design/collect_references": [("none", None)],
                "design/prd_approval": [("approve", None)],
                "design/hld_approval": [("approve", None)],
                "contract_approval": [("approve", None)],
                "release_approval": [("approve", None)],
            }
            action, trace = self.drive(gates)
        finally:
            globals()["canned_agent_outputs"] = orig
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertIn("implement[backend]/impl/fix", steps)
        self.assertIn("implement[frontend]/impl/fix", steps)

    def test_oq_loop_with_real_scripts(self):
        """The design OQ cycle against the REAL oq_serve/oq_record scripts and a real
        open-questions.json written by the 'plan' agent."""
        self.prep_tasks_json()
        oq = {
            "schema_version": 1, "feature_slug": "demo",
            "questions": [{
                "id": "q1", "question": "Quota per user?", "why": "sizing",
                "options": ["10", "100"], "status": "open", "resolution": None,
            }],
        }
        oq_path = os.path.join(self.tmp, ".maestro", "runs", "demo", "open-questions.json")
        os.makedirs(os.path.dirname(oq_path), exist_ok=True)
        with open(oq_path, "w") as fh:
            json.dump(oq, fh)

        # drive design.yaml standalone
        with statemod.locked("demo", self.tmp):
            resolver.init_run("demo", ".maestro/workflows/design.yaml", {"feature": "Demo"}, self.tmp)
        asked = []
        for _ in range(60):
            run = resolver.Run("demo", self.tmp)
            action = resolver.next_action(run)
            if action["action"] == "done":
                break
            run = resolver.Run("demo", self.tmp)
            if action["action"] == "run_agents":
                for act in action["agents"]:
                    for rel in act.get("artifacts", []):
                        full = os.path.join(self.tmp, rel)
                        os.makedirs(os.path.dirname(full), exist_ok=True)
                        open(full, "w").write("x")
                    resolver.complete_step(run, act["step"],
                                           outputs=canned_agent_outputs(act["step"], act))
            elif action["action"] == "run_agent":
                for rel in action.get("artifacts", []):
                    full = os.path.join(self.tmp, rel)
                    os.makedirs(os.path.dirname(full), exist_ok=True)
                    open(full, "w").write("x")
                if action["step"].endswith("refine_hld"):
                    # simulate the plan skill folding resolved answers into the HLD
                    with open(oq_path) as fh:
                        doc = json.load(fh)
                    for q in doc["questions"]:
                        if q["status"] == "resolved":
                            q["status"] = "folded"
                    with open(oq_path, "w") as fh:
                        json.dump(doc, fh)
                resolver.complete_step(run, action["step"],
                                       outputs=canned_agent_outputs(action["step"], action))
            elif action["action"] == "run_script":
                proc = subprocess.run(action["argv"], cwd=self.tmp, capture_output=True,
                                      text=True, timeout=30)
                resolver.complete_step(run, action["step"], exit_code=proc.returncode,
                                       stdout=proc.stdout)
            elif action["action"] == "ask_gate":
                step = action["step"]
                if step == "collect_references":
                    resolver.record_gate(run, step, "none")
                elif step == "oq_ask":
                    asked.append(action["prompt"])
                    self.assertIn("Quota per user?", action["prompt"])
                    resolver.record_gate(run, step, "answer", input_text="2")
                elif step == "prd_approval":
                    resolver.record_gate(run, step, "approve")
                elif step == "hld_approval":
                    resolver.record_gate(run, step, "approve")
                else:
                    self.fail(f"unexpected gate {step}")
            statemod.save("demo", run.state, self.tmp)
        else:
            self.fail("design workflow did not finish")
        self.assertEqual(len(asked), 1)
        with open(oq_path) as fh:
            doc = json.load(fh)
        # answered with option index 2 -> "100", then refine folded it
        self.assertEqual(doc["questions"][0]["status"], "folded")
        self.assertEqual(doc["questions"][0]["resolution"]["answer"], "100")

    def test_brainstorm_path_when_requirement_empty(self):
        """Empty requirement folder -> intake gate -> references gate (with a link) ->
        author the PRD via the real oq_serve/oq_record scripts (on requirement-questions.json)
        -> reach author_hld. The PRD loop mirrors the design OQ loop."""
        # start from an EMPTY requirement folder (undo setUp's seed file)
        req_dir = os.path.join(self.tmp, ".maestro", "runs", "demo", "requirement")
        for name in os.listdir(req_dir):
            os.remove(os.path.join(req_dir, name))
        rq_path = os.path.join(self.tmp, ".maestro", "runs", "demo", "requirement-questions.json")

        with statemod.locked("demo", self.tmp):
            resolver.init_run("demo", ".maestro/workflows/design.yaml", {"feature": "Demo"}, self.tmp)

        seen = []
        asked = []
        gave_refs = []
        reached_hld = False
        for _ in range(80):
            run = resolver.Run("demo", self.tmp)
            action = resolver.next_action(run)
            if action["action"] == "done":
                break
            run = resolver.Run("demo", self.tmp)
            step = action.get("step")
            if action["action"] == "run_agent":
                seen.append(step.rsplit("/", 1)[-1])
                for rel in action.get("artifacts", []):
                    full = os.path.join(self.tmp, rel)
                    os.makedirs(os.path.dirname(full), exist_ok=True)
                    open(full, "w").write("x")
                node = step.rsplit("/", 1)[-1]
                if node == "brainstorm_draft":
                    # simulate the brainstorm skill emitting one open question
                    doc = {"schema_version": 1, "feature_slug": "demo", "questions": [{
                        "id": "r1", "question": "Who is the primary user?", "why": "scope",
                        "options": ["Admins", "End users"], "status": "open", "resolution": None,
                    }]}
                    with open(rq_path, "w") as fh:
                        json.dump(doc, fh)
                    outputs = {"draft_summary": "drafted; 1 open question"}
                elif node == "rq_fold":
                    with open(rq_path) as fh:
                        doc = json.load(fh)
                    for q in doc["questions"]:
                        if q["status"] == "resolved":
                            q["status"] = "folded"
                    with open(rq_path, "w") as fh:
                        json.dump(doc, fh)
                    outputs = {"refined_summary": "folded 1 answer"}
                elif node == "author_hld":
                    reached_hld = True
                    resolver.complete_step(run, step, outputs={"hld_summary": "ok"})
                    statemod.save("demo", run.state, self.tmp)
                    break
                else:
                    outputs = canned_agent_outputs(step, action)
                resolver.complete_step(run, step, outputs=outputs)
            elif action["action"] == "run_script":
                proc = subprocess.run(action["argv"], cwd=self.tmp, capture_output=True,
                                      text=True, timeout=30)
                resolver.complete_step(run, step, exit_code=proc.returncode,
                                       stdout=proc.stdout)
            elif action["action"] == "ask_gate":
                if step == "requirement_intake":
                    resolver.record_gate(run, step, "brainstorm")
                elif step == "collect_references":
                    gave_refs.append(action["prompt"])
                    resolver.record_gate(run, step, "provide",
                                         input_text="https://figma.com/file/demo")
                elif step == "rq_ask":
                    asked.append(action["prompt"])
                    resolver.record_gate(run, step, "answer", input_text="2")
                elif step == "prd_approval":
                    resolver.record_gate(run, step, "approve")
                else:
                    self.fail(f"unexpected gate {step}")
            statemod.save("demo", run.state, self.tmp)
        else:
            self.fail("brainstorm path did not reach author_hld")

        self.assertTrue(reached_hld, "never reached author_hld")
        self.assertEqual(len(gave_refs), 1)  # references gate was offered
        self.assertIn("brainstorm_draft", seen)
        self.assertIn("rq_fold", seen)
        self.assertEqual(len(asked), 1)
        self.assertIn("Who is the primary user?", asked[0])
        with open(rq_path) as fh:
            doc = json.load(fh)
        # answered option index 2 -> "End users", then rq_fold folded it
        self.assertEqual(doc["questions"][0]["status"], "folded")
        self.assertEqual(doc["questions"][0]["resolution"]["answer"], "End users")


if __name__ == "__main__":
    unittest.main()
