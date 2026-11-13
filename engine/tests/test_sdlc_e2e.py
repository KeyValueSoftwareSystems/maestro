"""Full-pipeline simulation: drives the REAL shipped workflows (sdlc-main.yaml +
design/impl/qa subworkflows) through the engine with zero LLM — canned agent outputs,
scripted gate decisions, artifacts touched on disk. This is the proof that the example
pack and the engine agree."""
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import resolver  # noqa: E402
import state as statemod  # noqa: E402
import codebase_scan  # noqa: E402
import living_docs  # noqa: E402
import lld_set  # noqa: E402
import run_layout  # noqa: E402
import workspace_sync  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_ARTIFACT_WRITES = itertools.count(1)


def canned_agent_outputs(step, action):
    """Outputs by node id — mirrors each node's declared outputs list."""
    node = step.rsplit("/", 1)[-1]
    table = {
        "project_context": {"project_context": "A test product with backend and frontend repositories."},
        "prepare_prd": {"feature_goal": "Deliver the demo feature for test users.",
                        "summary": "Prepared the next focused product questions"},
        "write_prd": {"summary": "PRD written from confirmed context", "needs_clarification": False},
        "normalize_prd": {"summary": "Client PRD restructured; 1 fact to confirm"},
        "impact": {"impact_summary": "backend and frontend change", "repos_csv": "backend,frontend"},
        "prepare_hld_questions": {"summary": "Prepared architecture questions"},
        "brainstorm_hld": {"summary": "One service owns orders; 1 point open"},
        "write_hld": {"hld_summary": "3 services, 2 new tables", "needs_clarification": False},
        "prepare_lld_questions": {"summary": "Prepared repository design questions"},
        "author_llds": {"summary": "LLDs written", "contract_change_needed": False,
                        "contract_change": "None"},
        "revise_llds": {"summary": "LLDs revised", "contract_change_needed": False,
                        "contract_change": "None", "needs_clarification": False},
        "contract": {"contract_summary": "5 endpoints"},
        "contract_change": {"contract_summary": "added one field"},
        "test_cases": {"test_cases_path": "test-cases.md", "case_count": 12},
        "arch_review": {"review_path": "reviews/architecture.md", "blocking": False,
                        "summary": "sound"},
        "revise_from_review": {"hld_summary": "Resolved review findings",
                               "needs_clarification": False},
        "readiness_review": {"review_path": "reviews/lld-readiness.md", "blocking": False,
                             "summary": "ready"},
        "tasks": {"task_count": 4, "slice_count": 2, "escalate": False, "escalation": "None"},
        "implement": {"branch": "feature/x", "worktree": "/tmp/simulated",
                      "commit": "0" * 40, "summary": "built", "tests_passed": True,
                      "escalate": False, "escalation": "None"},
        "review": {"review_path": "reviews/summary.md", "blocking": False, "summary": "clean"},
        "fix": {"fix_summary": "fixed", "checks_passed": True, "escalate": False},
        "qa_run": {"passed": True, "failed_count": 0, "summary": "all green"},
        "qa_fix": {"fix_summary": "harness wait fixed", "checks_passed": True, "escalate": False,
                   "product_bug": False, "bug_repos": ""},
        "drift_check": {"review_path": "reviews/drift.md", "blocking": False,
                        "summary": "no drift"},
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

    qa_case_status = "passed"

    @property
    def prompts(self):
        if not hasattr(self, "_prompts"):
            self._prompts = {}
        return self._prompts

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
        # lld_set.py discovers repos under codebase/* — give it exactly backend+frontend
        # so the real script (run for real below, not stubbed) matches every other assumption
        # in this file (backend.md/frontend.md artifacts, per-stack tasks/impl/review).
        for stack in ("backend", "frontend"):
            path = os.path.join(self.tmp, "codebase", stack)
            os.makedirs(path)
            subprocess.run(["git", "init", "-q"], cwd=path, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
            with open(os.path.join(path, "README.md"), "w") as fh:
                fh.write(f"{stack}\n")
            subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=path, check=True)
            map_path = codebase_scan.map_path(self.tmp, stack)
            os.makedirs(os.path.dirname(map_path), exist_ok=True)
            with open(map_path, "w") as fh:
                fh.write(f"# {stack} map\n")
            head = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], check=True,
                                  capture_output=True, text=True).stdout.strip()
            codebase_scan.write_marker(map_path, head)
        # Project commands the engine's verify step runs in each implementation worktree.
        with open(os.path.join(self.tmp, "maestro.config.yaml"), "w") as fh:
            fh.write("version: 1\nrepos:\n" + "".join(
                f"  {stack}:\n    commands: {{build: \"true\", lint: \"true\", "
                f"test: \"test ! -f BROKEN\"}}\n" for stack in ("backend", "frontend")))
        # Simulate the normal /maestro-init result so the happy path proves the new sync
        # checkpoint is zero-agent/no-gate when code and knowledge are already current.
        os.makedirs(os.path.join(self.tmp, "docs"), exist_ok=True)
        living_docs.write_minimal_docs(self.tmp, "demo", ["backend", "frontend"])
        evidence = os.path.join(self.tmp, ".maestro", "bootstrap-evidence.md")
        with open(evidence, "w") as fh:
            fh.write("Indexed test workspace.\n")
        with __import__("contextlib").redirect_stdout(__import__("io").StringIO()):
            self.assertEqual(workspace_sync.cmd_record_knowledge(self.tmp, evidence), 0)

    def write_agent_artifact(self, rel, step):
        full = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        queue = rel.split("/.engine/queues/")[-1] if "/.engine/queues/" in rel else ""
        if queue in ("prd.json", "hld.json", "lld.json"):
            stage = queue[:-len(".json")]
            decisions = run_layout.path("demo", self.tmp, run_layout.stage_record(stage))
            questions = [] if os.path.exists(decisions) else [{
                "id": "conflict-behavior",
                "topic": stage + "-stale-request-outcome",
                "title": "Conflicting action",
                "question": "What should the user see if another action makes this request stale?",
                "why": "This defines a material failure and recovery path.",
                "proposal": "Reject the stale request, explain why, and preserve entered data.",
                "must_resolve": ["visible stale-request outcome", "recovery action"],
            }]
            if questions and stage != "prd":
                questions[0]["kind"] = "direction"
            with open(full, "w") as fh:
                json.dump({
                    "schema_version": 2,
                    "questions": questions,
                    "audit": {
                        "unresolved": [] if not questions else ["stale-request behavior"],
                        "contradictions": [],
                },
            }, fh)
            return
        if queue in ("hld-post.json", "lld-post.json"):
            with open(full, "w") as fh:
                json.dump({
                    "schema_version": 2,
                    "questions": [],
                    "audit": {"unresolved": [], "contradictions": []},
                }, fh)
            return
        if rel.endswith("/impact.json"):  # rewritten on every visit, as `fresh` requires
            with open(full, "w") as fh:
                json.dump({"schema_version": 1, "repos": [
                    {"name": "backend", "change": "owns the decision"},
                    {"name": "frontend", "change": "renders it"}],
                    "interfaces_change": True, "data_migration": False,
                    "infrastructure_change": False, "size": "major",
                    "summary": f"two repositories {next(_ARTIFACT_WRITES)}"}, fh)
            return
        if os.path.exists(full):
            with open(full) as fh:
                previous = fh.read()
            # Keep fixtures and structured docs; rewrite this harness's own generic
            # placeholder so `fresh: true` steps see new proof on every visit.
            if not previous.startswith("artifact "):
                return
        if rel.endswith("/requirement/prd.md"):
            sections = {
                "Summary": "Deliver the confirmed demo feature.",
                "Problem and context": "The product needs the demo behavior described in this run.",
                "Users and jobs": "Test users need to complete the demo workflow.",
                "Goals and success signals": "The behavior works and its acceptance checks pass.",
                "Non-goals": "Unrelated product and platform changes are excluded.",
                "Functional scope": "Implement the confirmed demo behavior across the required surfaces.",
                "Non-functional requirements": "- Saving responds within 300 ms at p95 for 50 requests per second.",
                "Constraints and assumptions": "Use the existing backend and frontend repositories.",
                "Acceptance criteria": "- AC-01: The documented behavior is available and automated tests pass.",
                "Dependencies and risks": "Delivery depends on both repositories remaining compatible.",
                "Priorities and phasing": "Build the core behavior before optional refinements.",
                "References": "The run requirement and maintained project documentation.",
            }
            with open(full, "w") as fh:
                fh.write("# Demo feature — PRD\n\n"
                         "**Feature slug:** `demo`\n"
                         "**Status:** Ready for review\n\n")
                fh.write("\n\n".join(
                    f"## {heading}\n\n{body}" for heading, body in sections.items()
                ) + "\n")
        elif rel.endswith("/design/hld.md"):
            sections = {
                "Decision summary": "\n".join(
                    f"- Confirmed architecture decision {index}." for index in range(1, 6)
                ),
                "Context and scope": "The approved demo spans the backend and frontend.",
                "Proposed design": "The backend owns decisions. The frontend renders server state.\n\n```mermaid\nflowchart LR\n  client --> backend\n```",
                "Interfaces": "- The frontend calls the backend to load and save state (synchronous).",
                "Key decisions and trade-offs": "Use one authority to prevent divergent behavior.",
                "Delivery and risks": "Land the backend contract before client integration.",
                "Open questions": "None",
            }
            with open(full, "w") as fh:
                fh.write("# Demo feature — HLD\n\n"
                         "**Feature slug:** `demo`\n"
                         "**Status:** Ready for review\n\n")
                fh.write("\n\n".join(
                    f"## {heading}\n\n{body}" for heading, body in sections.items()
                ) + "\n")
        elif rel.endswith("/design/test-cases.md"):
            with open(full, "w") as fh:
                fh.write("# Demo test cases\n\n| Criterion | Cases |\n|---|---|\n"
                         "| AC-01 | TC-demo-001 |\n\n## Journey: demo\n\n"
                         "### TC-demo-001 — The documented behavior works\n\n"
                         "- **Traces:** AC-01\n- **Expected result:** the behavior is visible.\n")
        elif rel.endswith("/qa/results.json"):
            with open(full, "w") as fh:
                json.dump({"schema_version": 1, "cases": [
                    {"id": "TC-demo-001", "status": self.qa_case_status,
                     "note": "" if self.qa_case_status == "passed" else "assertion failed"}]}, fh)
        elif rel.endswith("requirement-questions.json") or rel.endswith("open-questions.json"):
            with open(full, "w") as fh:
                json.dump({"schema_version": 1, "feature_slug": "demo", "questions": []}, fh)
        else:
            # Unique per write: `fresh: true` steps must produce new proof on every visit.
            with open(full, "w") as fh:
                fh.write(f"artifact {next(_ARTIFACT_WRITES)}\n")

    def write_review_files(self, act, node, outputs):
        """What a reviewer and its author write beside their reports: the reviewer's findings
        (one open blocking finding exactly when it reports blocking) and the author's resolutions
        (every active blocking finding fixed)."""
        findings = next((rel for rel in act.get("artifacts", [])
                         if rel.endswith(".findings.json")), None)
        if findings:
            items = ([{"id": "F1", "severity": "blocking", "area": "fit", "status": "open",
                       "finding": "A requirement has no mechanism.", "evidence": "hld.md"}]
                     if outputs.get("blocking") else [])
            Path(self.tmp, findings).write_text(json.dumps({"schema_version": 1,
                                                            "findings": items}))
        resolutions = next((rel for rel in act.get("artifacts", [])
                            if rel.endswith(".resolutions.json")), None)
        if node == "revise_llds":
            resolutions = ".maestro/runs/demo/reviews/lld-readiness.resolutions.json"
        if node == "fix":
            # the code-review fixer names its resolutions file in the prompt, not as an artifact
            match = re.search(r"\.maestro/runs/demo/reviews/code-[\w-]+\.resolutions\.json",
                              act.get("prompt", ""))
            resolutions = match.group(0) if match else None
        if resolutions:
            Path(self.tmp, resolutions).parent.mkdir(parents=True, exist_ok=True)
            Path(self.tmp, resolutions).write_text(json.dumps({"schema_version": 1, "resolutions": [
                {"id": "F1", "resolution": getattr(self, "fix_resolution", "fixed"),
                 "note": "added the mechanism"}]}))

    def write_llds(self, slug="demo"):
        """What the LLD writer produces: one LLD per selected repository (design/lld/<repo>.md)."""
        for repo in lld_set.selected(slug, self.tmp):
            full = lld_set.lld_path(slug, repo, self.tmp)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            parent_slug = slug
            sections = {
                "Change summary": "\n".join(
                    f"- Deliver repository behavior {index}." for index in range(1, 5)
                ),
                "Existing seam": (
                    "Requests enter through `src/routes.py` and follow the existing service boundary."
                ),
                "Proposed changes": (
                    "Extend the current service with the approved behavior. Keep state ownership "
                    "inside the existing data layer."
                ),
                "Data model and migrations": (
                    "No repository-owned persistence change."
                ),
                "API and client contract": (
                    "No externally consumed interface change."
                ),
                "State and flows": (
                    "The route validates input, invokes the service, and returns the result. The "
                    "service owns ordering and changes state only after validation."
                ),
                "Failure and operational behavior": (
                    "Validation failures use the existing client error. Storage failures preserve "
                    "prior state and use current logging."
                ),
                "Implementation sequence": (
                    "1. Extend the service boundary and cover its behavior.\n"
                    "2. Connect the route and add an integration test."
                ),
                "Verification": (
                    "Service tests cover validation and state changes. Route tests cover the result."
                ),
            }
            with open(full, "w") as fh:
                fh.write(
                    f"# Demo {repo} — LLD\n\n"
                    f"**Parent feature:** `{parent_slug}`\n"
                    f"**Repository:** `{repo}`\n"
                    "**Status:** Ready for review\n\n"
                )
                fh.write("\n\n".join(
                    f"## {heading}\n\n{body}" for heading, body in sections.items()
                ) + "\n")

    def implementation_outputs(self, act):
        def prompt_value(name):
            match = re.search(rf"^- {re.escape(name)}: (.+)$", act["prompt"], re.MULTILINE)
            self.assertIsNotNone(match, f"missing {name} in implementation prompt")
            return match.group(1).strip()

        repo = prompt_value("stack")
        repo_path = os.path.join(self.tmp, prompt_value("repo_path"))
        branch = prompt_value("branch")
        worktree = os.path.join(self.tmp, ".maestro", "test-worktrees", repo)
        os.makedirs(os.path.dirname(worktree), exist_ok=True)
        if not os.path.exists(worktree):
            subprocess.run(["git", "-C", repo_path, "worktree", "add", "-q", "-b",
                            branch, worktree, "HEAD"], check=True)
        commit = subprocess.run(["git", "-C", worktree, "rev-parse", "HEAD"], check=True,
                                capture_output=True, text=True).stdout.strip()
        return {"branch": branch, "worktree": worktree, "commit": commit,
                "summary": "built", "tests_passed": True, "escalate": False,
                "escalation": "None"}

    # -- driver ----------------------------------------------------------

    def drive(self, gate_script, max_steps=200, agent_overrides=None, mode=None, inputs=None,
              workflow=".maestro/workflows/sdlc-main.yaml", force=False):
        """Run the pipeline: gate_script maps step path -> list of (option, input) taken
        in order. Gates the run mode lets the engine answer appear in the trace as
        ("auto_gate", step). Returns (final_action, trace)."""
        trace = []
        gate_ptr = {}
        overrides = agent_overrides or {}
        with statemod.locked("demo", self.tmp):
            resolver.init_run("demo", workflow, {"feature": "Demo", **(inputs or {})}, self.tmp,
                              force=force, mode=mode)
        for _ in range(max_steps):
            run = resolver.Run("demo", self.tmp)
            answered = resolver.apply_autopilot(run)
            if answered:
                trace.extend((f"auto_{item['kind']}", item["step"]) for item in answered)
                statemod.save("demo", run.state, self.tmp)
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
                # an agent's engine check runs under the agent's step: trace it apart
                trace.append((act["action"], step + "#check" if act.get("check") else step))
                if "prompt" in act:
                    self.prompts.setdefault(step, []).append(act["prompt"])
                run = resolver.Run("demo", self.tmp)
                if act["action"] in ("run_agent", "run_lead"):
                    for rel in act.get("artifacts", []):
                        self.write_agent_artifact(rel, step)
                    node = step.rsplit("/", 1)[-1]
                    if node in ("author_llds", "revise_llds"):
                        self.write_llds()
                    override = overrides.get(node)
                    outputs = (
                        override() if callable(override) else override
                    ) or (
                        self.implementation_outputs(act) if node == "implement"
                        else canned_agent_outputs(step, act)
                    )
                    self.write_review_files(act, node, outputs)
                    resolver.complete_step(run, step, outputs=outputs)
                elif act["action"] == "run_script":
                    # actually run the real script where it's an engine helper; stub others
                    if ("oq_serve" in step or "validate_tasks" in step
                            or any(a.endswith("validate_tasks.py") for a in act.get("argv", []))
                            or any(a.endswith("validate_prd.py") or a.endswith("validate_prd_questions.py")
                                   or a.endswith("validate_hld.py")
                                   for a in act.get("argv", []))
                            or any("mem_consolidate" in a or "lld_set" in a
                                   or "implementation_pool" in a or "workspace_sync" in a
                                   or "repo_checks" in a
                                   or "prd_source.py" in a or "ac_trace.py" in a
                                   or "qa_env.py" in a or "deliver.py" in a
                                   or "infra_scan.py" in a or "decision_log.py" in a
                                   or "findings.py" in a or "sizing.py" in a
                                   or "greenfield.py" in a or "impact_trace.py" in a
                                   or "release_record.py" in a
                                   for a in act.get("argv", []))):
                        proc = subprocess.run(act["argv"], cwd=self.tmp, capture_output=True,
                                              text=True, timeout=30)
                        code, out = proc.returncode, proc.stdout
                    else:
                        code, out = canned_script(step)
                    resolver.complete_step(run, step, exit_code=code, stdout=out)
                elif act["action"] == "ask_gate":
                    decisions = gate_script.get(step)
                    if decisions is None and step == "design/lld/lld_approval":
                        decisions = [("approve", None)] * 20
                    if decisions is None and step == "design/hld/hld_mode":
                        decisions = [("guided", None)] * 5
                    if decisions is None and step == "archive/confirm_archive":
                        decisions = [("archive", None)]
                    self.assertTrue(decisions, f"unscripted gate: {step} ({act['prompt'][:80]})")
                    i = gate_ptr.get(step, 0)
                    self.assertLess(i, len(decisions), f"gate {step} asked more than scripted")
                    option, text = decisions[i]
                    gate_ptr[step] = i + 1
                    selected = next(o for o in act["options"] if o["id"] == option)
                    resolver.record_gate(run, step, option)
                    if selected.get("input"):
                        self.assertIsNotNone(text, f"{step}/{option} requires scripted input")
                        pending = resolver.next_action(run)
                        self.assertEqual(pending["action"], "ask_input")
                        self.assertEqual(pending["field"], selected["input"])
                        trace.append(("ask_input", step))
                        resolver.record_gate_input(run, step, text)
                elif act["action"] == "ask_interview":
                    resolver.record_interview(
                        run, step, act["section"],
                        answer=None if act.get("proposal") else f"Confirmed {act['title']}",
                        accept=bool(act.get("proposal")),
                    )
                elif act["action"] == "ask_interview_batch":
                    resolver.record_interview_batch(run, step, {
                        question["section"]: (
                            {"accept": True} if question.get("proposal")
                            else {"answer": f"Confirmed {question['title']}"}
                        )
                        for question in act["questions"]
                    })
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
            path = os.path.join(self.tmp, ".maestro", "runs", "demo", "build", stack,
                                "tasks.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                json.dump(doc, fh)

    # -- scenarios ---------------------------------------------------------

    def test_happy_path(self):
        self.prep_tasks_json()
        gates = {
            "design/prd/prd_approval": [("approve", None)],
            "design/hld/hld_approval": [("approve", None)],
            "design/lld/lld_scope": [("all", None)],
            "review/contract_approval": [("approve", None)],
            "delivery/release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        self.assertEqual(action["outputs"]["hld"], ".maestro/runs/demo/design/hld.md")
        self.assertEqual(action["outputs"]["implementation_manifest"],
                         ".maestro/runs/demo/build/manifest.json")
        steps = [s for _, s in trace]
        self.assertIn("workspace_sync_initial/plan", steps)
        self.assertIn("workspace_sync_initial/lock", steps)
        self.assertIn("delivery/workspace_sync_pre_impl/plan", steps)
        self.assertIn("delivery/workspace_sync_pre_impl/lock", steps)
        self.assertNotIn("workspace_sync_initial/refresh_knowledge", steps)
        # both selected repos implemented through runtime claims, not hard-coded stacks
        impl_steps = [s for s in steps if s.endswith("/impl/implement")]
        review_steps = [s for s in steps if s.endswith("/impl/review")]
        self.assertEqual(len(impl_steps), 2)
        self.assertEqual(len(review_steps), 2)
        # the lead confirms context, grills one material edge, and writes once before HLD
        self.assertIn("design/intake/project_context", steps)
        self.assertIn("design/prd/prd_interview", steps)
        self.assertIn("design/prd/write_prd", steps)
        self.assertLess(steps.index("design/prd/write_prd"), steps.index("design/hld/write_hld"))
        # one LLD run: one interview, one write, a readiness check and one human approval,
        # all before any implementation begins
        gate_steps = [s for a, s in trace if a == "ask_gate"]
        self.assertEqual(gate_steps, ["design/prd/prd_approval", "design/hld/hld_mode",
                                      "design/hld/hld_approval",
                                      "design/lld/lld_scope", "design/lld/lld_approval",
                                      "delivery/release_approval", "archive/confirm_archive"])
        self.assertEqual(steps.count("design/lld/author_llds"), 1)
        self.assertEqual(steps.count("design/lld/lld_interview"), 1)
        self.assertLess(steps.index("design/lld/lld_interview"), steps.index("design/lld/author_llds"))
        self.assertFalse(any(step.endswith("/lld_post_interview") for step in steps))
        self.assertFalse(any(step.endswith("/repair_llds") for step in steps))
        for repo in ("backend", "frontend"):
            self.assertTrue(os.path.isfile(lld_set.lld_path("demo", repo, self.tmp)))
        approval = json.loads(Path(lld_set.approval_path("demo", self.tmp)).read_text())
        self.assertEqual(sorted(approval["llds"]), ["backend", "frontend"])
        self.assertIsNotNone(approval["contract_sha256"])  # the HLD lists an interface
        # the architecture is reviewed before HLD approval; the contract precedes the LLDs;
        # the readiness check follows the LLDs, then the test cases; delivery checks staleness first
        order = ["design/hld/write_hld", "design/hld/arch_review", "design/contract/contract",
                 "design/lld/author_llds", "design/lld/readiness_review",
                 "design/lld/test_cases", "design/lld/record_approval",
                 "delivery/design_check", impl_steps[0]]
        self.assertEqual([steps.index(step) for step in order],
                         sorted(steps.index(step) for step in order))
        self.assertLess(steps.index("delivery/finalize_implementation"), steps.index("delivery/qa/qa_run"))
        # one decision log across the design stages, shown at each approval
        run_dir = Path(self.tmp, ".maestro/runs/demo")
        log = (run_dir / "decisions/decision-log.md").read_text()
        for stage in ("## PRD", "## HLD", "## LLD"):
            self.assertIn(stage, log)
        # the stage records are the only store: no JSON copy of the log, no separate assumption log
        self.assertEqual(sorted(p.name for p in (run_dir / "decisions").iterdir()),
                         ["decision-log.md", "hld.json", "lld.json", "prd.json"])
        self.assertIn("Decisions: 1 decision(s)", self.prompts["design/prd/prd_approval"][0])
        self.assertIn("decision-log.md", self.prompts["design/hld/hld_approval"][0])
        # after release approval: the verified branches are reported (default branch mode:
        # nothing pushed), then lessons are harvested
        self.assertLess(steps.index("archive/deliver"), steps.index("archive/harvest/retrospect"))
        record = json.loads(Path(self.tmp, ".maestro/runs/demo/release/delivery.json").read_text())
        self.assertEqual(record["mode"], "branch")
        self.assertEqual(sorted(r["repo"] for r in record["repositories"]), ["backend", "frontend"])
        self.assertFalse(any(r["pushed"] for r in record["repositories"]))
        self.assertIn("Verified branches ready to merge", action["outputs"]["delivery"])
        gates = statemod.load("demo", self.tmp)["steps"]
        self.assertEqual(gates["delivery/release_approval"]["outputs"]["by"], "person")

    def test_valid_existing_prd_uses_fast_path(self):
        self.prep_tasks_json()
        self.write_agent_artifact(
            ".maestro/runs/demo/requirement/prd.md", "existing-prd-fixture"
        )
        gates = {
            "design/prd/prd_approval": [("approve", None)],
            "design/hld/hld_approval": [("approve", None)],
            "design/lld/lld_scope": [("all", None)],
            "review/contract_approval": [("approve", None)],
            "delivery/release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        steps = [step for _, step in trace]
        self.assertIn("design/prd/check_existing_prd", steps)
        self.assertNotIn("design/prd/prepare_prd", steps)
        self.assertNotIn("design/prd/prd_interview", steps)
        self.assertNotIn("design/prd/write_prd", steps)

    def write_client_prd(self):
        path = os.path.join(self.tmp, ".maestro", "runs", "demo", "requirement", "client-spec.md")
        with open(path, "w") as fh:
            fh.write("# Report export spec\n\n" + " ".join(
                ["Admins export the filtered report as CSV within the agreed limits."] * 30))

    def test_client_prd_is_normalized_and_only_its_gaps_are_asked(self):
        self.prep_tasks_json()
        self.write_client_prd()
        action, trace = self.drive(dict(self.DESIGN_GATES))
        self.assertEqual(action["action"], "done", action)
        steps = [step for _, step in trace]
        prd = [s.rsplit("/", 1)[-1] for s in steps if s.startswith("design/prd/")]
        # a worker restructures the client's document once; the product role asks only its
        # open gap from the structured PRD, then writes it — no interview from scratch
        self.assertEqual(prd[:6], ["check_existing_prd", "prd_source", "normalize_prd",
                                   "normalize_prd#check", "prepare_prd", "prepare_prd#check"])
        self.assertEqual(steps.count("design/prd/normalize_prd"), 1)
        self.assertIn("Requirement source: normalize", self.prompts["design/prd/prepare_prd"][0])
        self.assertIn("When the requirement source is normalize (normalize)",
                      self.prompts["design/prd/write_prd"][0])
        self.assertEqual(steps.count("design/prd/write_prd"), 1)
        self.assertEqual(steps.count("design/prd/prd_interview"), 1)
        self.assertLess(steps.index("design/prd/prd_interview"), steps.index("design/prd/write_prd"))
        self.assertTrue(os.path.isfile(os.path.join(
            self.tmp, ".maestro", "runs", "demo", "requirement", "client-spec.md")))

    def test_auto_mode_turns_a_client_prd_into_an_approved_prd_unasked(self):
        self.prep_tasks_json()
        self.write_client_prd()
        action, trace = self.drive({}, mode="auto")
        self.assertEqual(action["action"], "done", action)
        steps = [step for _, step in trace]
        self.assertIn(("auto_interview", "design/prd/prd_interview"), trace)
        self.assertEqual(steps.count("design/prd/prepare_prd"), 1)  # one round, no re-ask
        self.assertIn(("auto_gate", "design/prd/prd_approval"), trace)

    def test_release_sent_back_to_design_reimplements_every_repo(self):
        """No batches: each delivery pass builds every designed repo against the current design."""
        self.prep_tasks_json()
        gates = {
            "design/prd/prd_approval": [("approve", None), ("approve", None)],
            "design/hld/hld_approval": [("approve", None), ("approve", None)],
            "design/lld/lld_scope": [("all", None), ("all", None)],
            "review/contract_approval": [("approve", None), ("approve", None)],
            "delivery/release_approval": [("revise", "handle the empty state"), ("approve", None)],
        }
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        steps = [step for _, step in trace]
        self.assertEqual(len([step for step in steps if step.endswith("/impl/implement")]), 4)
        self.assertEqual(trace.count(("ask_gate", "delivery/release_approval")), 2)
        self.assertFalse([step for step in steps if "impl_scope" in step and "init" not in step])
        queue_path = run_layout.path("demo", self.tmp, run_layout.POOL)
        with open(queue_path, encoding="utf-8") as fh:
            queue = json.load(fh)
        self.assertEqual(queue["deferred"], [])
        self.assertEqual(set(queue["implementations"]), {"backend", "frontend"})

    def test_rescope_cascade_from_prd_gate(self):
        """PRD rescope re-confirms the feature, interview, and single-write stage."""
        self.prep_tasks_json()
        gates = {
            "design/prd/prd_approval": [("rescope", "sharpen the scope"), ("approve", None)],
            "design/hld/hld_approval": [("approve", None)],
            "design/lld/lld_scope": [("all", None)],
            "review/contract_approval": [("approve", None)],
            "delivery/release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        # PRD written twice (rescope re-runs the product role's prepare job despite a valid old
        # file); the second write is a full update, not a targeted revision
        self.assertEqual(steps.count("design/prd/write_prd"), 2)
        self.assertEqual(steps.count("design/prd/prd_interview"), 1)
        self.assertEqual(steps.count("design/hld/write_hld"), 1)
        self.assertIn("PRD approval choice (empty before the first approval): rescope", self.prompts["design/prd/write_prd"][1])

    def _design_gates(self, prd, hld):
        return {
            "design/prd/prd_approval": prd,
            "design/hld/hld_approval": hld,
            "design/lld/lld_scope": [("all", None)],
            "review/contract_approval": [("approve", None)],
            "delivery/release_approval": [("approve", None)],
        }

    def test_prd_revise_is_a_targeted_edit(self):
        """Revise edits the PRD in place under the engine's check — no goal confirm, interview,
        or rewrite."""
        self.prep_tasks_json()
        action, trace = self.drive(self._design_gates(
            [("revise", "rename the role"), ("revise", "tighten AC-02"), ("approve", None)],
            [("approve", None)]))
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        # one writer: the first write, then two targeted revisions, each checked
        self.assertEqual(steps.count("design/prd/write_prd"), 3)
        self.assertEqual(steps.count("design/prd/write_prd#check"), 3)
        self.assertEqual(steps.count("design/prd/prepare_prd"), 1)  # one accepted round, no re-ask
        revisions = self.prompts["design/prd/write_prd"][1:]
        self.assertIn("PRD approval choice (empty before the first approval): revise", revisions[0])
        self.assertIn("rename the role", revisions[0])
        self.assertIn("tighten AC-02", revisions[1])

    def test_hld_revise_is_a_targeted_edit(self):
        self.prep_tasks_json()
        action, trace = self.drive(self._design_gates(
            [("approve", None)], [("revise", "name the cache owner"), ("approve", None)]))
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertEqual(steps.count("design/hld/write_hld"), 2)
        self.assertIn("HLD approval choice (empty before the first approval): revise", self.prompts["design/hld/write_hld"][1])
        self.assertEqual(steps.count("design/hld/prepare_hld_questions"), 1)  # an accepted round goes straight to writing
        self.assertEqual(steps.count("design/hld/validate_hld"), 2)

    def test_hld_brainstorm_writes_the_hld_without_the_question_rounds(self):
        self.prep_tasks_json()
        action, trace = self.drive({**self.DESIGN_GATES,
                                    "design/hld/hld_mode": [("brainstorm", None)],
                                    "design/hld/brainstorm_confirm": [("more", None), ("create", None)]})
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertEqual(steps.count("design/hld/brainstorm_hld"), 2)
        self.assertNotIn("design/hld/prepare_hld_questions", steps)
        self.assertLess(steps.index("design/hld/brainstorm_hld"), steps.index("design/hld/write_hld"))

    def test_hld_revise_needing_a_decision_falls_back_to_clarification(self):
        self.prep_tasks_json()
        writes = []

        def write_hld():
            # the revision (second write) needs a decision the confirmed ones cannot settle
            writes.append(1)
            return {"hld_summary": "needs a decision" if len(writes) == 2 else "written",
                    "needs_clarification": len(writes) == 2}
        action, trace = self.drive(
            self._design_gates([("approve", None)],
                               [("revise", "support offline mode"), ("approve", None)]),
            agent_overrides={"write_hld": write_hld})
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertEqual(steps.count("design/hld/prepare_hld_questions"), 2)
        self.assertEqual(steps.count("design/hld/write_hld"), 3)

    def test_hld_rethink_runs_the_full_clarification_pass(self):
        self.prep_tasks_json()
        action, trace = self.drive(self._design_gates(
            [("approve", None)], [("rethink", "split the service"), ("approve", None)]))
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertEqual(steps.count("design/hld/write_hld"), 2)
        self.assertIn("HLD approval choice (empty before the first approval): rethink", self.prompts["design/hld/write_hld"][1])

    def _qa_gates(self, qa_gate):
        return {
            "design/prd/prd_approval": [("approve", None)],
            "design/hld/hld_approval": [("approve", None)],
            "design/lld/lld_scope": [("all", None)],
            "review/contract_approval": [("approve", None)],
            "delivery/qa/qa_gate": qa_gate,
            "delivery/release_approval": [("approve", None)],
        }

    def test_qa_escalation_goes_to_the_gate_without_rerunning_the_suite(self):
        self.prep_tasks_json()
        action, trace = self.drive(self._qa_gates([("accept", None)]), agent_overrides={
            "qa_run": {"passed": False, "failed_count": 2, "summary": "2 failing"},
            "qa_fix": {"fix_summary": "staging database unreachable", "checks_passed": False,
                       "escalate": True, "product_bug": False, "bug_repos": ""},
        })
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertEqual(steps.count("delivery/qa/qa_run"), 1)
        self.assertEqual(steps.count("delivery/qa/qa_fix"), 1)
        self.assertIn("delivery/qa/qa_gate", steps)
        self.assertLess(steps.index("delivery/qa/qa_gate"), steps.index("delivery/qa/env_down"))

    def test_qa_product_bug_is_fixed_in_its_worktree_and_qa_reruns(self):
        self.prep_tasks_json()
        runs = iter([{"passed": False, "failed_count": 1, "summary": "booking total wrong"},
                     {"passed": True, "failed_count": 0, "summary": "all green"}])
        bugs = Path(self.tmp, ".maestro/runs/demo/qa/bugs.md")

        def qa_fix():
            bugs.parent.mkdir(parents=True, exist_ok=True)
            bugs.write_text("## backend\n\nTC-demo-001 fails: total excludes tax.\n")
            return {"fix_summary": "product bug in backend totals", "checks_passed": False,
                    "escalate": False, "product_bug": True, "bug_repos": "backend"}
        fixed = []

        def bugfix_fix():
            # commit the fix on the feature branch the bug-fix stage was given
            worktree = statemod.load("demo", self.tmp)["steps"][
                "delivery/bugfix_claim"]["outputs"]["worktree"]
            Path(worktree, "fix.txt").write_text("tax included\n")
            subprocess.run(["git", "add", "fix.txt"], cwd=worktree, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "fix totals"], cwd=worktree, check=True)
            fixed.append(subprocess.run(["git", "rev-parse", "HEAD"], cwd=worktree, check=True,
                                        capture_output=True, text=True).stdout.strip())
            return {"fix_summary": "tax added to totals", "checks_passed": True, "escalate": False}
        action, trace = self.drive(dict(self.DESIGN_GATES), agent_overrides={
            "qa_run": lambda: next(runs), "qa_fix": qa_fix, "fix": bugfix_fix})
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        bugfix = [s for s in steps if s.startswith("delivery/bugfix/")]
        self.assertEqual([s.rsplit("/", 1)[-1] for s in bugfix],
                         ["fix", "review_resolution", "handoff", "verify", "review_scope",
                          "review", "review_verdict"])
        self.assertEqual(steps.count("delivery/finalize_implementation"), 2)
        self.assertEqual(steps.count("delivery/qa/qa_run"), 2)
        self.assertEqual(steps.count("delivery/qa/env_down"), 2)
        self.assertNotIn("delivery/qa/qa_gate", steps)
        self.assertLess(steps.index("delivery/bugfix_record"),
                        len(steps) - 1 - steps[::-1].index("delivery/finalize_implementation"))
        # QA re-ran against the fixed commit, verified by the engine at that commit
        manifest = json.loads(Path(self.tmp, ".maestro/runs/demo/build/manifest.json")
                              .read_text())
        backend = next(r for r in manifest["repositories"] if r["repo"] == "backend")
        self.assertEqual(backend["commit"], fixed[0])
        self.assertEqual(backend["verification"]["status"], "verified")

    def test_qa_harness_fix_reruns_the_suite(self):
        self.prep_tasks_json()
        runs = iter([{"passed": False, "failed_count": 1, "summary": "1 flaky"},
                     {"passed": True, "failed_count": 0, "summary": "all green"}])
        action, trace = self.drive(self._qa_gates([]), agent_overrides={
            "qa_run": lambda: next(runs)})
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertEqual(steps.count("delivery/qa/qa_run"), 2)
        self.assertEqual(steps.count("delivery/qa/qa_fix"), 1)
        self.assertNotIn("delivery/qa/qa_gate", steps)

    DESIGN_GATES = {
        "design/prd/prd_approval": [("approve", None)],
        "design/hld/hld_approval": [("approve", None)],
        "design/lld/lld_scope": [("all", None)],
        "delivery/release_approval": [("approve", None)],
    }

    @staticmethod
    def blocking_once(clean):
        """A reviewer override that blocks on its first call and is clean afterwards."""
        calls = []

        def outputs():
            calls.append(1)
            return {**clean, "blocking": len(calls) == 1,
                    "summary": "1 blocker" if len(calls) == 1 else clean["summary"]}
        return outputs

    def test_blocking_architecture_review_is_resolved_before_hld_approval(self):
        self.prep_tasks_json()
        review = self.blocking_once({"review_path": "reviews/architecture.md", "summary": "sound"})
        action, trace = self.drive(dict(self.DESIGN_GATES), agent_overrides={"arch_review": review})
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        hld = [s.rsplit("/", 1)[-1] for s in steps if s.startswith("design/hld/")]
        start = hld.index("arch_review")
        self.assertEqual(hld[start:start + 12], ["arch_review", "review_verdict",
                                                 "revise_from_review", "revise_from_review#check",
                                                 "revise_from_review#check", "review_resolution", "validate_hld",
                                                 "sync_decisions", "arch_scope", "arch_review",
                                                 "review_verdict", "hld_approval"])
        self.assertEqual(trace.count(("ask_gate", "design/hld/hld_approval")), 1)

    def test_design_mode_asks_only_for_prd_and_hld_approval(self):
        self.prep_tasks_json()
        action, trace = self.drive({
            "design/prd/prd_approval": [("approve", None)],
            "design/hld/hld_approval": [("approve", None)],
        }, mode="design")
        self.assertEqual(action["action"], "done", action)
        self.assertEqual([s for a, s in trace if a == "ask_gate"],
                         ["design/prd/prd_approval", "design/hld/hld_mode",
                          "design/hld/hld_approval", "archive/confirm_archive"])
        self.assertEqual([s for a, s in trace if a == "auto_gate"],
                         ["design/lld/lld_scope", "design/lld/lld_approval",
                          "delivery/release_approval"])
        gates = statemod.load("demo", self.tmp)["gates"]
        self.assertEqual([(g["step"], g.get("auto")) for g in gates], [
            ("design/prd/prd_approval", None), ("design/hld/hld_mode", None),
            ("design/hld/hld_approval", None), ("design/lld/lld_scope", "design"), ("design/lld/lld_approval", "design"),
            ("delivery/release_approval", "design"), ("archive/confirm_archive", None)])
        # the autopilot LLD approval still records the hash-bound approval delivery checks
        self.assertTrue(os.path.isfile(lld_set.approval_path("demo", self.tmp)))

    def test_auto_mode_runs_from_requirement_to_release_without_a_person(self):
        self.prep_tasks_json()
        action, trace = self.drive({}, mode="auto")
        self.assertEqual(action["action"], "done", action)
        # the only person: the archive confirmation, which autopilot never answers
        asked = [t for t in trace if t[0] in ("ask_gate", "ask_interview", "ask_interview_batch")]
        self.assertEqual(asked, [("ask_gate", "archive/confirm_archive")])
        self.assertIn(("auto_gate", "delivery/release_approval"), trace)
        self.assertIn(("auto_gate", "design/hld/hld_mode"), trace)  # autopilot never brainstorms
        # one autopilot round per stage, straight to the writer
        steps = [s for _, s in trace]
        for stage in ("prd", "hld", "lld"):
            self.assertIn(("auto_interview", f"design/{stage}/{stage}_interview"), trace)
            prepare = "prepare_prd" if stage == "prd" else f"prepare_{stage}_questions"
            self.assertEqual(steps.count(f"design/{stage}/{prepare}"), 1)
        prd_context = json.loads(Path(self.tmp, ".maestro/runs/demo/decisions/prd.json").read_text())
        decision = prd_context["decisions"][0]
        self.assertEqual((decision["source"], decision["by"]), ("assumption", "autopilot"))
        log = Path(self.tmp, ".maestro/runs/demo/decisions/decision-log.md").read_text()
        self.assertIn("Run mode: auto. 3 assumptions, 0 left open", log)
        self.assertIn("**PRD · ", log)
        self.assertIn("design/lld/lld_approval → approve (auto mode", log)
        self.assertLess(steps.index("delivery/assumptions"), steps.index("delivery/review_pack"))
        # a release nobody approved is recorded as such; pull-request delivery opens drafts from it
        self.assertEqual(statemod.load("demo", self.tmp)["steps"][
            "delivery/release_approval"]["outputs"]["by"], "autopilot")

    def test_declining_the_archive_delivers_nothing_and_leaves_docs_untouched(self):
        self.prep_tasks_json()
        action, trace = self.drive({"archive/confirm_archive": [("skip", None)]}, mode="auto")
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertIn("archive/confirm_archive", steps)
        self.assertFalse([s for s in steps
                          if s.startswith(("archive/deliver", "archive/harvest", "archive/cleanup"))])
        self.assertIn("push the code yourself", self.prompts["archive/confirm_archive"][0])
        state = statemod.load("demo", self.tmp)
        self.assertEqual(state["steps"]["archive/confirm_archive"]["outputs"]["choice"], "skip")
        run_dir = Path(self.tmp, ".maestro/runs/demo")
        self.assertFalse((run_dir / "release/delivery.json").exists())
        self.assertFalse(Path(self.tmp, ".maestro/memory/incoming/demo.json").exists())
        for repo in ("backend", "frontend"):  # kept: the person pushes from them
            self.assertTrue(Path(self.tmp, ".maestro/test-worktrees", repo).is_dir())
        # the approval is on record, so the archive can still run later
        self.assertEqual(json.loads((run_dir / "release.json").read_text())["approved_by"],
                         "autopilot")

    def test_a_declined_archive_runs_later_on_its_own(self):
        self.prep_tasks_json()
        self.drive({"archive/confirm_archive": [("skip", None)]}, mode="auto")
        action, trace = self.drive({"confirm_archive": [("archive", None)]},
                                   workflow=".maestro/workflows/archive.yaml", force=True)
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertEqual(steps[:3], ["check_release", "confirm_archive", "deliver"])
        self.assertIn("harvest/retrospect", steps)
        self.assertEqual(steps[-1], "cleanup")
        delivery = json.loads(Path(self.tmp, ".maestro/runs/demo/release/delivery.json").read_text())
        self.assertEqual(len(delivery["repositories"]), 2)

    def test_the_archive_refuses_a_feature_whose_release_was_not_approved(self):
        action, trace = self.drive({}, workflow=".maestro/workflows/archive.yaml")
        self.assertEqual(action["action"], "failed", action)
        self.assertEqual([s for _, s in trace], ["check_release"])

    def test_auto_mode_stops_at_hld_approval_while_the_review_still_blocks(self):
        self.prep_tasks_json()
        blocked = {"review_path": "reviews/architecture.md", "blocking": True,
                   "summary": "1 blocker"}
        action, trace = self.drive({"design/hld/hld_approval": [("reject", None)]},
                                   agent_overrides={"arch_review": blocked}, mode="auto")
        self.assertEqual(action["action"], "failed", action)
        self.assertEqual([s for a, s in trace if a == "ask_gate"], ["design/hld/hld_approval"])
        self.assertEqual([s for a, s in trace if a == "auto_gate"],
                         ["design/prd/prd_approval", "design/hld/hld_mode"])

    def test_acceptance_criteria_are_traced_through_qa_to_the_release_gate(self):
        self.prep_tasks_json()
        action, trace = self.drive(dict(self.DESIGN_GATES))
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        # the catalog is written once the LLDs pass the readiness check
        self.assertLess(steps.index("design/lld/readiness_review"),
                        steps.index("design/lld/test_cases"))
        self.assertLess(steps.index("design/lld/test_cases#check"),
                        steps.index("design/lld/lld_approval"))
        self.assertLess(steps.index("delivery/ac_trace"), steps.index("delivery/review_pack"))
        trace_md = Path(self.tmp, ".maestro/runs/demo/release/ac-trace.md").read_text()
        self.assertIn("1/1 acceptance criteria passing", trace_md)
        self.assertIn("| AC-01 | TC-demo-001 (passed) | passing |", trace_md)

    def test_untraced_criterion_sends_the_test_cases_back(self):
        self.prep_tasks_json()
        catalog = Path(self.tmp, ".maestro/runs/demo/design/test-cases.md")
        calls = []

        def test_cases():
            # the first catalog traces a criterion the PRD lacks; the rewrite fixes it
            calls.append(1)
            if len(calls) == 2:  # sent back with the engine's exact finding in its prompt
                feedback = self.prompts["design/lld/test_cases"][-1]
                self.assertIn("failed the engine's check", feedback)
                self.assertIn("criteria the PRD does not have: AC-07", feedback)
                self.assertIn("no test case traces AC-01", feedback)
            catalog.write_text("### TC-demo-001 — wrong\n\n- **Traces:** AC-07\n"
                               if len(calls) == 1 else
                               "### TC-demo-001 — right\n\n- **Traces:** AC-01\n")
            return {"test_cases_path": str(catalog), "case_count": 1}
        action, trace = self.drive(dict(self.DESIGN_GATES), agent_overrides={"test_cases": test_cases})
        self.assertEqual(action["action"], "done", action)
        lld = [s.rsplit("/", 1)[-1] for _, s in trace if s.startswith("design/lld/")]
        start = lld.index("test_cases")
        self.assertEqual(lld[start:start + 5], ["test_cases", "test_cases#check", "test_cases",
                                                "test_cases#check", "lld_approval"])
        self.assertEqual(len(calls), 2)

    def test_auto_mode_stops_at_release_when_a_criterion_fails_qa(self):
        self.prep_tasks_json()
        self.qa_case_status = "failed"
        action, trace = self.drive({"delivery/release_approval": [("reject", None)]}, mode="auto")
        self.assertEqual(action["action"], "failed", action)
        self.assertEqual([s for a, s in trace if a == "ask_gate"], ["delivery/release_approval"])
        self.assertIn("0/1 acceptance criteria passing — AC-01 failing",
                      Path(self.tmp, ".maestro/runs/demo/release/ac-trace.md").read_text())

    def test_workspace_without_infrastructure_asks_no_infrastructure_questions(self):
        self.prep_tasks_json()
        action, _trace = self.drive(dict(self.DESIGN_GATES))
        self.assertEqual(action["action"], "done", action)
        prepare = self.prompts["design/hld/prepare_hld_questions"][0]
        self.assertIn("Infrastructure level none", prepare)
        self.assertIn("ask no infrastructure questions", prepare)
        steps = statemod.load("demo", self.tmp)["steps"]
        self.assertEqual(steps["design/hld/validate_hld"]["outputs"]["infra_changed"], False)

    def add_terraform_to_backend(self):
        """Infrastructure as code inside an app repository, committed and indexed like setUp."""
        repo = os.path.join(self.tmp, "codebase", "backend")
        tf = os.path.join(repo, "deploy", "main.tf")
        os.makedirs(os.path.dirname(tf))
        with open(tf, "w") as fh:
            fh.write('resource "aws_sqs_queue" "exports" {}\n')
        subprocess.run(["git", "add", "deploy/main.tf"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "infra"], cwd=repo, check=True)
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
        codebase_scan.write_marker(codebase_scan.map_path(self.tmp, os.path.basename(repo)), head)
        with __import__("contextlib").redirect_stdout(__import__("io").StringIO()):
            workspace_sync.cmd_record_knowledge(
                self.tmp, os.path.join(self.tmp, ".maestro", "bootstrap-evidence.md"))

    def test_infrastructure_as_code_asks_infrastructure_and_the_hld_must_cover_it(self):
        self.prep_tasks_json()
        self.add_terraform_to_backend()
        hld = Path(self.tmp, ".maestro/runs/demo/design/hld.md")

        def write_hld():
            # the writer adds the section the engine now requires for an iac workspace
            self.write_agent_artifact(".maestro/runs/demo/design/hld.md", "design/hld/write_hld")
            text = hld.read_text()
            if "## Infrastructure and operations" not in text:
                hld.write_text(text.replace("## Key decisions", "## Infrastructure and operations"
                                            "\n\n- `backend`: new SQS queue `exports` with a "
                                            "dead-letter queue (14-day retention).\n\n"
                                            "## Key decisions"))
            return {"hld_summary": "export worker on a queue", "needs_clarification": False}
        action, _trace = self.drive(dict(self.DESIGN_GATES), agent_overrides={"write_hld": write_hld})
        self.assertEqual(action["action"], "done", action)
        prepare = self.prompts["design/hld/prepare_hld_questions"][0]
        self.assertIn("Infrastructure level iac", prepare)
        self.assertIn("Infrastructure as code in backend (terraform)", prepare)
        self.assertIn("read the infrastructure repositories (the `iac_repos` input)", prepare)
        self.assertIn("- iac_repos: backend", prepare)
        self.assertRegex(self.prompts["design/hld/write_hld"][0], r"--infra-level\s+iac")
        self.assertIn("Infrastructure level iac", self.prompts["design/hld/arch_review"][0])
        outputs = statemod.load("demo", self.tmp)["steps"]["design/hld/validate_hld"]["outputs"]
        self.assertEqual((outputs["valid"], outputs["infra_changed"]), (True, True))
        self.assertEqual(outputs["infra_repos_csv"], "backend")
        # the repository that owns the infrastructure change cannot be dropped from LLD scope
        self.assertIn("stay in scope: backend", self.prompts["design/lld/lld_scope"][0])

    def test_escalated_architecture_finding_goes_to_the_person_at_hld_approval(self):
        self.prep_tasks_json()
        blocked = {"review_path": "reviews/architecture.md", "blocking": True, "summary": "1 blocker"}
        resolutions = Path(self.tmp, ".maestro/runs/demo/reviews/architecture.resolutions.json")

        def escalate():
            # the author escalates instead of fixing; the test harness's default would fix it
            self.write_agent_artifact(".maestro/runs/demo/design/hld.md", "design/hld/revise_from_review")
            return {"hld_summary": "unchanged", "needs_clarification": False}
        gates = {"design/hld/hld_approval": [("reject", None)],
                 "design/prd/prd_approval": [("approve", None)]}
        original = self.write_review_files

        def write_review_files(act, node, outputs):
            original(act, node, outputs)
            if node == "revise_from_review":
                resolutions.write_text(json.dumps({"schema_version": 1, "resolutions": [
                    {"id": "F1", "resolution": "escalated", "note": "choose the cost ceiling"}]}))
        self.write_review_files = write_review_files
        action, trace = self.drive(gates, agent_overrides={"arch_review": blocked,
                                                           "revise_from_review": escalate})
        self.assertEqual(action["action"], "failed", action)  # the person rejected at the gate
        steps = [s for _, s in trace]
        self.assertEqual(steps.count("design/hld/revise_from_review"), 1)
        self.assertIn("choose the cost ceiling", self.prompts["design/hld/hld_approval"][0])

    def test_blocking_design_drift_stops_an_autopilot_release(self):
        self.prep_tasks_json()
        drift = {"review_path": "reviews/drift.md", "blocking": True,
                 "summary": "backend returns 200 where the contract says 201"}
        action, trace = self.drive({"delivery/release_approval": [("reject", None)]},
                                   agent_overrides={"drift_check": drift}, mode="auto")
        self.assertEqual(action["action"], "failed", action)
        steps = [s for _, s in trace]
        self.assertLess(steps.index("delivery/ac_trace"), steps.index("delivery/drift_check"))
        self.assertLess(steps.index("delivery/drift_verdict"), steps.index("delivery/review_pack"))
        self.assertEqual([s for a, s in trace if a == "ask_gate"], ["delivery/release_approval"])
        self.assertIn("Design drift (engine): 1 blocking finding",
                      self.prompts["delivery/release_approval"][0])

    def test_light_path_designs_from_the_prd_without_an_hld(self):
        self.prep_tasks_json()
        action, trace = self.drive({"design/prd/prd_approval": [("approve", None)],
                                    "design/lld/lld_scope": [("all", None)],
                                    "delivery/release_approval": [("approve", None)]},
                                   inputs={"path": "light"})
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertFalse([s for s in steps if s.startswith("design/hld/")])
        self.assertFalse([s for s in steps if s.startswith("design/contract/")])
        self.assertIn("design/lld/readiness_review", steps)
        self.assertIn("Design path: light", self.prompts["design/lld/author_llds"][0])
        approval = json.loads(Path(lld_set.approval_path("demo", self.tmp)).read_text())
        self.assertTrue(approval["light"])
        self.assertIsNone(approval["hld_sha256"])
        self.assertIsNotNone(approval["prd_sha256"])
        # the run reports no HLD or contract it never wrote
        self.assertEqual((action["outputs"]["hld"], action["outputs"]["contract"]), (None, None))
        # the approved design is still checked for staleness before delivery
        self.assertIn("delivery/design_check", steps)

    def test_each_repository_gets_its_stack_skills(self):
        self.prep_tasks_json()
        config = Path(self.tmp, "maestro.config.yaml")
        config.write_text(config.read_text().replace("  backend:\n", "  backend:\n    stack: go\n"))
        for name, tags in (("golang-patterns", "[stack:go, patterns]"),
                           ("go-review", "[stack:go, review]")):
            skill = Path(self.tmp, f".claude/skills/{name}/SKILL.md")
            skill.parent.mkdir(parents=True)
            skill.write_text(f"---\nname: {name}\ndescription: Go.\ntags: {tags}\n---\n")
        action, _trace = self.drive(dict(self.DESIGN_GATES))
        self.assertEqual(action["action"], "done", action)
        by_repo = {}
        for step, prompts in self.prompts.items():
            if step.endswith("/impl/implement"):
                repo = "backend" if "- stack: backend\n" in prompts[0] else "frontend"
                by_repo[repo] = prompts[0]
        self.assertIn("stack skills (golang-patterns)", by_repo["backend"])
        self.assertIn("stack skills ()", by_repo["frontend"])
        review = next(p[0] for s, p in self.prompts.items()
                      if s.endswith("/impl/review") and "repo_path: codebase/backend" in p[0])
        # the reviewer is handed the stack's checklist, not its pattern guide
        self.assertIn("review skills (go-review)", review)
        self.assertNotIn("golang-patterns", review)

    def test_greenfield_creates_and_scaffolds_the_repositories_the_hld_lists(self):
        self.prep_tasks_json()
        # a new product: no repositories, no recorded knowledge of them
        shutil.rmtree(os.path.join(self.tmp, "codebase"))
        shutil.rmtree(os.path.join(self.tmp, ".maestro", "index"), ignore_errors=True)
        provenance = os.path.join(self.tmp, "docs", "provenance.yaml")
        if os.path.isfile(provenance):
            os.remove(provenance)
        Path(self.tmp, "maestro.config.yaml").write_text("version: 1\nrepos: {}\n")
        hld = Path(self.tmp, ".maestro/runs/demo/design/hld.md")

        def write_hld():
            self.write_agent_artifact(".maestro/runs/demo/design/hld.md", "design/hld/write_hld")
            text = hld.read_text()
            if "## Repositories" not in text:
                hld.write_text(text.replace("## Proposed design", "## Repositories\n\n"
                                            "- `backend` (python): owns the demo state.\n"
                                            "- `frontend` (python): shows it.\n\n"
                                            "## Proposed design"))
            return {"hld_summary": "two new repositories", "needs_clarification": False}

        def scaffold():
            report = {"repos": {}}
            for repo in ("backend", "frontend"):
                path = Path(self.tmp, "codebase", repo)
                (path / "README.md").write_text(f"# {repo}\n")
                map_path = Path(codebase_scan.map_path(self.tmp, repo))
                map_path.parent.mkdir(parents=True, exist_ok=True)
                map_path.write_text(f"# {repo} map\n")
                subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
                subprocess.run(["git", "-C", str(path), "-c", "user.email=t@e", "-c", "user.name=T",
                                "commit", "-qm", "scaffold"], check=True)
                report["repos"][repo] = {"stack": "python", "commands": {
                    "build": "test -f README.md", "test": "test ! -f BROKEN"}}
            Path(self.tmp, ".maestro/runs/demo/build/scaffold.json").write_text(json.dumps(report))
            return {"summary": "backend and frontend scaffolded"}
        action, trace = self.drive(dict(self.DESIGN_GATES), agent_overrides={
            "write_hld": write_hld, "scaffold": scaffold})
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertIn("Greenfield: true", self.prompts["design/hld/prepare_hld_questions"][0])
        order = ["design/hld/hld_approval", "design/scaffold/create", "design/scaffold/scaffold",
                 "design/scaffold/scaffold#check", "design/scaffold/pin",
                 "design/lld/lld_scope_init"]
        self.assertEqual([steps.index(s) for s in order], sorted(steps.index(s) for s in order))
        config = Path(self.tmp, "maestro.config.yaml").read_text()
        self.assertIn("backend", config)
        manifest = json.loads(Path(self.tmp, ".maestro/runs/demo/build/manifest.json")
                              .read_text())
        self.assertEqual({r["repo"]: r["verification"]["status"] for r in manifest["repositories"]},
                         {"backend": "verified", "frontend": "verified"})

    def test_blocking_readiness_findings_revise_llds_before_approval(self):
        self.prep_tasks_json()
        readiness = self.blocking_once({"review_path": "reviews/lld-readiness.md",
                                        "summary": "ready"})
        action, trace = self.drive(dict(self.DESIGN_GATES),
                                   agent_overrides={"readiness_review": readiness})
        self.assertEqual(action["action"], "done", action)
        lld = [s.rsplit("/", 1)[-1] for _, s in trace if s.startswith("design/lld/")]
        start = lld.index("readiness_review")
        # the revision round re-checks the LLDs; the test cases are written once, after it
        self.assertEqual(lld[start:start + 13], ["readiness_review", "readiness_verdict",
                                                 "revise_llds", "readiness_resolution",
                                                 "validate_llds", "lld_impact_trace", "sync_decisions",
                                                 "readiness_scope", "readiness_review",
                                                 "readiness_verdict",
                                                 "test_cases", "test_cases#check", "lld_approval"])
        self.assertEqual(lld.count("test_cases"), 1)

    def test_readiness_rounds_stop_at_the_limit_and_the_person_decides(self):
        self.prep_tasks_json()

        def never_ready():
            return {"review_path": "reviews/lld-readiness.md", "blocking": True,
                    "summary": "still blocked"}
        action, trace = self.drive(dict(self.DESIGN_GATES),
                                   agent_overrides={"readiness_review": never_ready})
        self.assertEqual(action["action"], "done", action)
        lld = [s.rsplit("/", 1)[-1] for _, s in trace if s.startswith("design/lld/")]
        # three reviews (reviews.max_rounds default), two revisions, then the person decides
        self.assertEqual(lld.count("readiness_review"), 3)
        self.assertEqual(lld.count("revise_llds"), 2)
        self.assertEqual(lld[lld.index("test_cases"):][:3],
                         ["test_cases", "test_cases#check", "lld_approval"])
        verdict = statemod.load("demo", self.tmp)["steps"]["design/lld/readiness_verdict"]["outputs"]
        self.assertEqual((verdict["limit_reached"], verdict["blocking"]), (True, True))
        self.assertIn(("ask_gate", "design/lld/lld_approval"), trace)

    def test_lld_change_request_needs_feedback_and_is_a_targeted_revision(self):
        self.prep_tasks_json()
        gates = dict(self.DESIGN_GATES)
        gates["design/lld/lld_approval"] = [("revise", "name the retry limit"), ("approve", None)]
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        self.assertIn(("ask_input", "design/lld/lld_approval"), trace)
        steps = [s for _, s in trace]
        self.assertEqual(steps.count("design/lld/author_llds"), 1)
        self.assertEqual(steps.count("design/lld/revise_llds"), 1)
        self.assertNotIn("design/hld/hld_approval", steps[steps.index("design/lld/revise_llds"):])

    def test_contract_change_from_an_lld_updates_the_contract_before_the_llds(self):
        """A frontend need the contract lacks: the contract changes first, then the LLDs follow."""
        self.prep_tasks_json()
        contract = Path(self.tmp, ".maestro", "runs", "demo", "design", "openapi.yaml")
        writes = []

        def author_llds():
            writes.append(1)
            return {"summary": "LLDs written", "contract_change_needed": len(writes) == 1,
                    "contract_change": "frontend needs `updated_at` on GET /items"}

        def contract_change():
            contract.write_text(contract.read_text() + "# updated_at added\n")
            return {"contract_summary": "added updated_at (additive)"}

        action, trace = self.drive(dict(self.DESIGN_GATES), agent_overrides={
            "author_llds": author_llds, "contract_change": contract_change})
        self.assertEqual(action["action"], "done", action)
        lld = [s.rsplit("/", 1)[-1] for _, s in trace if s.startswith("design/lld/")]
        start = lld.index("author_llds")
        # the post-check is validated first, so a gap it records is never skipped
        self.assertEqual(lld[start:start + 6], ["author_llds", "author_llds#check",
                                                "contract_change", "revise_llds",
                                                "readiness_resolution", "validate_llds"])
        approval = json.loads(Path(lld_set.approval_path("demo", self.tmp)).read_text())
        self.assertEqual(approval["contract_sha256"], statemod.sha256_file(str(contract)))

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
                    "design/prd/prd_approval": [("approve", None)],
                "design/hld/hld_approval": [("approve", None)],
                "design/lld/lld_scope": [("all", None)],
                "review/contract_approval": [("approve", None)],
                "delivery/release_approval": [("approve", None)],
            }
            action, trace = self.drive(gates)
        finally:
            globals()["canned_agent_outputs"] = orig
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertEqual(len([s for s in steps if s.endswith("/impl/fix")]), 2)

    def _commit_outside_maestro(self):
        """A manual commit after the maps were recorded: maps and docs are now stale."""
        repo = os.path.join(self.tmp, "codebase", "backend")
        Path(repo, "manual.txt").write_text("manual change\n")
        subprocess.run(["git", "-C", repo, "add", "manual.txt"], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "manual"], check=True)

    def _sync_gates(self, choice):
        return {
            "workspace_sync_initial/sync_gate": [(choice, None)],
            "delivery/workspace_sync_pre_impl/sync_gate": [(choice, None)] * 3,
            "design/prd/prd_approval": [("approve", None)],
            "design/hld/hld_approval": [("approve", None)],
            "design/lld/lld_scope": [("all", None)],
            "review/contract_approval": [("approve", None)],
            "delivery/release_approval": [("approve", None)],
        }

    def test_keep_current_commits_still_refreshes_stale_docs(self):
        """Replaces the old design-map check: no repo update, but stale maps are refreshed."""
        self.prep_tasks_json()
        self._commit_outside_maestro()

        def refresh_knowledge():
            for stack in ("backend", "frontend"):
                with open(codebase_scan.map_path(self.tmp, stack), "a") as fh:
                    fh.write("\nRefreshed after the manual commit.\n")
            return {"domains_written": 1, "architecture_path": "docs/architecture.md",
                    "summary": "refreshed"}

        action, trace = self.drive(self._sync_gates("current"),
                                   agent_overrides={"refresh_knowledge": refresh_knowledge})
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertIn("workspace_sync_initial/keep_current", steps)
        self.assertIn("workspace_sync_initial/refresh_knowledge", steps)
        self.assertIn("workspace_sync_initial/record_knowledge", steps)
        self.assertNotIn("workspace_sync_initial/apply", steps)
        self.assertNotIn("design/map", " ".join(steps))

    def test_keep_as_is_skips_the_docs_refresh(self):
        self.prep_tasks_json()
        self._commit_outside_maestro()
        action, trace = self.drive(self._sync_gates("as_is"))
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertNotIn("workspace_sync_initial/refresh_knowledge", steps)
        self.assertIn("workspace_sync_initial/lock", steps)

    def test_failed_engine_checks_route_to_fix_before_review(self):
        """The agent says tests pass; the engine's own run says no — the engine wins."""
        self.prep_tasks_json()
        broken = os.path.join(self.tmp, ".maestro", "test-worktrees", "backend", "BROKEN")
        real_implementation_outputs = self.implementation_outputs

        def implementation_outputs(act):
            outputs = real_implementation_outputs(act)  # claims tests_passed: True
            if outputs["worktree"].endswith("backend"):
                Path(broken).write_text("failing\n")
            return outputs

        def fix_outputs():
            os.remove(broken)
            return {"fix_summary": "fixed the failing test", "checks_passed": True,
                    "escalate": False}

        self.implementation_outputs = implementation_outputs
        gates = {
            "design/prd/prd_approval": [("approve", None)],
            "design/hld/hld_approval": [("approve", None)],
            "design/lld/lld_scope": [("all", None)],
            "review/contract_approval": [("approve", None)],
            "delivery/release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates, agent_overrides={"fix": fix_outputs})
        self.assertEqual(action["action"], "done", action)
        def slot_steps(slot):
            return [s.rsplit("/", 1)[-1] for _, s in trace
                    if s.startswith(f"delivery/implement[{slot}]/impl/")]

        # slot_1 claims backend (repos are claimed in name order); slot_2 claims frontend
        # domain_rules (optional, never blocks) runs after every passing verify
        self.assertEqual(slot_steps("slot_1")[-9:], ["verify", "fix", "review_resolution", "handoff",
                                                      "verify", "domain_rules", "review_scope",
                                                      "review", "review_verdict"])
        self.assertEqual(slot_steps("slot_2")[-5:], ["verify", "domain_rules", "review_scope",
                                                      "review", "review_verdict"])
        receipt = json.loads(Path(self.tmp, ".maestro", "runs", "demo", "build", "backend",
                                  "verify.json").read_text())
        self.assertTrue(receipt["passed"])
        self.assertEqual([c["name"] for c in receipt["checks"]], ["build", "lint", "test"])
        manifest = json.loads(Path(self.tmp, ".maestro", "runs", "demo", "build",
                                   "manifest.json").read_text())
        statuses = {r["repo"]: r["verification"]["status"] for r in manifest["repositories"]}
        self.assertEqual(statuses, {"backend": "verified", "frontend": "verified"})

    IMPL_GATES = {
        "design/prd/prd_approval": [("approve", None)],
        "design/hld/hld_approval": [("approve", None)],
        "design/lld/lld_scope": [("all", None)],
        "review/contract_approval": [("approve", None)],
        "delivery/release_approval": [("approve", None)],
    }

    @staticmethod
    def impl_steps(trace, node):
        """The impl steps of the first repository slot that ran `node` (slots interleave)."""
        slot = next(s.split("]")[0] for _, s in trace if s.endswith(f"/impl/{node}"))
        return [s.rsplit("/", 1)[-1] for _, s in trace if s.startswith(slot + "]/impl/")]

    def test_blocking_code_review_is_decided_from_the_findings_file(self):
        """The reviewer's own flag says clean, its findings file says blocking: the file wins,
        the fixer answers the finding, and the re-review clears it."""
        self.prep_tasks_json()
        calls = []

        def review():
            calls.append(1)
            # first review: a blocking finding in the file (write_review_files keys off this)
            return {"review_path": "reviews/summary.md", "blocking": len(calls) == 1,
                    "summary": "clean"}
        action, trace = self.drive(dict(self.IMPL_GATES), agent_overrides={"review": review})
        self.assertEqual(action["action"], "done", action)
        steps = self.impl_steps(trace, "fix")
        start = steps.index("review_verdict")
        self.assertEqual(steps[start:start + 9], ["review_verdict", "fix", "review_resolution",
                                                  "handoff", "verify", "domain_rules",
                                                  "review_scope", "review", "review_verdict"])

    def test_escalated_review_finding_goes_to_a_person(self):
        self.prep_tasks_json()
        self.fix_resolution = "escalated"
        calls = []

        def review():
            calls.append(1)
            return {"review_path": "reviews/summary.md", "blocking": len(calls) == 1,
                    "summary": "1 blocking" if len(calls) == 1 else "clean"}
        gates = dict(self.IMPL_GATES)
        for slot in ("slot_1", "slot_2"):
            gates[f"delivery/implement[{slot}]/impl/impl_gate"] = [("accept", None)]
        action, trace = self.drive(gates, agent_overrides={"review": review})
        self.assertEqual(action["action"], "done", action)
        steps = self.impl_steps(trace, "fix")
        start = steps.index("fix")
        self.assertEqual(steps[start:start + 3], ["fix", "review_resolution", "impl_gate"])
        gate = next(p[0] for st, p in self.prompts.items() if st.endswith("/impl/impl_gate"))
        self.assertIn("F1", gate)

    def test_fix_hard_stop_goes_to_a_person(self):
        """fix-loop's escalate (an unapproved migration, a contract change) is never ignored."""
        self.prep_tasks_json()
        calls = []

        def review():
            calls.append(1)
            return {"review_path": "reviews/summary.md", "blocking": len(calls) == 1,
                    "summary": "1 blocking" if len(calls) == 1 else "clean"}
        gates = dict(self.IMPL_GATES)
        for slot in ("slot_1", "slot_2"):
            gates[f"delivery/implement[{slot}]/impl/impl_gate"] = [("accept", None)]
        action, trace = self.drive(gates, agent_overrides={
            "review": review,
            "fix": {"fix_summary": "needs a migration the LLD does not plan",
                    "checks_passed": False, "escalate": True}})
        self.assertEqual(action["action"], "done", action)
        steps = self.impl_steps(trace, "fix")
        start = steps.index("fix")
        self.assertEqual(steps[start:start + 2], ["fix", "impl_gate"])

    def test_implementer_stop_goes_to_a_person_then_continues(self):
        """Work the approved design does not describe stops the implementer; the person's
        guidance reaches the planner and the implementer on the next pass."""
        self.prep_tasks_json()
        real_implementation_outputs = self.implementation_outputs
        calls = []

        def implementation_outputs(act):
            calls.append(1)
            outputs = real_implementation_outputs(act)
            if len(calls) == 1:
                outputs.update(escalate=True, escalation="needs an unplanned orders.tax column")
            return outputs
        self.implementation_outputs = implementation_outputs
        gates = dict(self.IMPL_GATES)
        for slot in ("slot_1", "slot_2"):
            gates[f"delivery/implement[{slot}]/impl/stop_gate"] = [
                ("continue", "Compute tax at read time; no new column.")]
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        steps = self.impl_steps(trace, "stop_gate")
        start = steps.index("stop_gate")
        # the gate, then its guidance input, then a fresh plan
        self.assertEqual(steps[start:start + 4], ["stop_gate", "stop_gate", "tasks",
                                                  "tasks#check"])
        gate = next(p[0] for st, p in self.prompts.items() if st.endswith("/impl/stop_gate"))
        self.assertIn("unplanned orders.tax column", gate)
        replanned = [p for st, ps in self.prompts.items() if st.endswith("/impl/tasks") for p in ps]
        self.assertTrue(any("Compute tax at read time" in p for p in replanned))

    def test_hld_clarifies_before_single_write(self):
        """The HLD resolves one grouped architecture round before writing once."""
        self.prep_tasks_json()
        gates = {
            "design/prd/prd_approval": [("approve", None)],
            "design/hld/hld_approval": [("approve", None)],
            "design/lld/lld_scope": [("all", None)],
            "review/contract_approval": [("approve", None)],
            "delivery/release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        steps = [step for _, step in trace]
        self.assertEqual(steps.count("design/hld/hld_interview"), 1)
        self.assertEqual(steps.count("design/hld/write_hld"), 1)
        # the author's three checks (post-check, the HLD, the impact trace), then the facts are recorded
        self.assertEqual(steps.count("design/hld/write_hld#check"), 3)
        self.assertIn("design/hld/validate_hld", steps)
        self.assertNotIn("design/hld/hld_post_interview", steps)

    def test_prd_interview_path_when_requirement_empty(self):
        """An empty requirement uses lead-only clarification and a durable interview."""
        req_dir = os.path.join(self.tmp, ".maestro", "runs", "demo", "requirement")
        for name in os.listdir(req_dir):
            os.remove(os.path.join(req_dir, name))
        with statemod.locked("demo", self.tmp):
            resolver.init_run("demo", ".maestro/workflows/design.yaml", {"feature": "Demo"}, self.tmp)

        seen = []
        interview_sections = []
        reached_hld = False
        for _ in range(80):
            run = resolver.Run("demo", self.tmp)
            action = resolver.next_action(run)
            run = resolver.Run("demo", self.tmp)
            step = action.get("step")
            if action["action"] in ("run_agent", "run_lead"):
                seen.append(step.rsplit("/", 1)[-1])
                for rel in action.get("artifacts", []):
                    self.write_agent_artifact(rel, step)
                node = step.rsplit("/", 1)[-1]
                if node == "write_hld":
                    reached_hld = True
                    outputs = {"hld_summary": "ok", "needs_clarification": False}
                else:
                    outputs = canned_agent_outputs(step, action)
                resolver.complete_step(run, step, outputs=outputs)
            elif action["action"] == "run_script":
                proc = subprocess.run(action["argv"], cwd=self.tmp, capture_output=True,
                                      text=True, timeout=30)
                resolver.complete_step(run, step, exit_code=proc.returncode,
                                       stdout=proc.stdout)
            elif action["action"] == "ask_gate":
                gate = step.rsplit("/", 1)[-1]  # phase children nest paths: prd/<gate>
                if gate == "requirement_intake":
                    resolver.record_gate(run, step, "clarify")
                elif gate == "prd_approval":
                    resolver.record_gate(run, step, "approve")
                elif gate == "hld_mode":
                    resolver.record_gate(run, step, "guided")
                else:
                    self.fail(f"unexpected gate {step}")
            elif action["action"] == "ask_interview":
                if step.endswith("prd_interview"):
                    interview_sections.append(action["section"])
                resolver.record_interview(run, step, action["section"], accept=True)
            elif action["action"] == "ask_interview_batch":
                if step.endswith("prd_interview"):
                    interview_sections.extend(q["section"] for q in action["questions"])
                resolver.record_interview_batch(run, step, {
                    question["section"]: {"accept": True}
                    for question in action["questions"]
                })
            statemod.save("demo", run.state, self.tmp)
            if reached_hld:
                break
        else:
            self.fail("PRD interview path did not reach write_hld")

        self.assertTrue(reached_hld, "never reached write_hld")
        self.assertIn("project_context", seen)
        self.assertIn("write_prd", seen)
        self.assertEqual(len(interview_sections), 1)
        context_path = os.path.join(self.tmp, ".maestro", "runs", "demo", "decisions",
                                    "prd.json")
        with open(context_path) as fh:
            context = json.load(fh)
        self.assertEqual(len(context["decisions"]), 1)


if __name__ == "__main__":
    unittest.main()
