"""Full-pipeline simulation: drives the REAL shipped workflows (sdlc-main.yaml +
design/plan/impl/qa/archive subworkflows) through the engine with zero LLM — canned agent
outputs, scripted gate decisions, artifacts touched on disk. This is the proof that the example
pack and the engine agree.

The design phase is the plan flow: PRD -> (plan || test cases) -> bind. A person leads the
brainstorm and approves the plan (docs/plans/active/<slug>.md), which archive reconciles with what
was built and files under docs/plans/completed/."""
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
import ac_trace  # noqa: E402
import living_docs  # noqa: E402
import plan_doc  # noqa: E402
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
        "brainstorm": {"summary": "Keep the backend as the single owner; 1 point open"},
        "write_plan": {"summary": "Plan covers backend and frontend"},
        "test_cases": {"test_cases_path": "test-cases.md", "case_count": 12},
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
        "plan_reconcile": {"changed": False, "summary": "The delivered code matches the plan."},
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


PLAN = "design/plan_and_tests[plan]/plan/"
TESTS = "design/plan_and_tests[tests]/tests/"
ACTIVE = "docs/plans/active/demo.md"
COMPLETED = "docs/plans/completed/demo.md"


def stage_path(step):
    """Design runs the plan stage (`design-plan.yaml`) and the test cases as two branches of one
    parallel node. Scenarios name a step by its stage path (`design/plan/…`, `design/tests/…`), so
    gate scripts and trace checks read as the stages do, not as the branch nesting."""
    return step.replace(PLAN, "design/plan/").replace(TESTS, "design/tests/")


class SdlcE2E(unittest.TestCase):
    maxDiff = None

    qa_case_status = "passed"
    plan_type = "major"  # the `path` input of the run: major (full PRD and plan) or minor
    empty_prd_queue = False  # the product questions: none to ask (a clear requirement)
    new_repos = ()  # repositories the written plan marks new (a greenfield run)
    real_worktrees = False  # run worktrees.py for real (the engine creates feature worktrees)

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
        req =os.path.join(self.tmp, ".maestro", "runs", "demo", "requirement")
        os.makedirs(req)
        with open(os.path.join(req, "requirement.md"), "w") as fh:
            fh.write("Build the demo feature.\n")
        # the workspace root is a git repository: the engine commits the plan there (and files it)
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.tmp, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.tmp, check=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=self.tmp, check=True)
        # exactly backend+frontend under codebase/*, matching every other assumption in this file
        # (the plan's repositories, per-stack tasks/impl/review).
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

    MAJOR_PRD_SECTIONS = {
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
    MINOR_PRD_SECTIONS = {
        "Problem": "Users cannot reach the demo behavior.",
        "Acceptance criteria": "- AC-01: The documented behavior is available and automated tests pass.",
        "Out of scope": "Unrelated product and platform changes.",
    }

    def prd_text(self):
        sections = self.MINOR_PRD_SECTIONS if self.plan_type == "minor" else self.MAJOR_PRD_SECTIONS
        return ("# Demo feature — PRD\n\n**Feature slug:** `demo`\n**Status:** Ready for review\n\n"
                + "\n\n".join(f"## {heading}\n\n{body}" for heading, body in sections.items())
                + "\n")

    def plan_text(self, status="active"):
        """A plan that passes `plan_doc.py validate` for the run's type: every configured
        repository (marked new when `new_repos` says so) and every PRD acceptance criterion."""
        repos = ("backend", "frontend")
        if self.plan_type == "minor":
            names = ", ".join(r + (" (new)" if r in self.new_repos else "") for r in repos)
            return ("# Demo feature — plan\n"
                    f"Type: minor · Run: demo · Repositories: {names}\n"
                    "- Change: backend owns the decision; frontend renders it.\n"
                    "- Where: backend/src/routes.py and frontend/src/view.ts\n"
                    "- Interface: GET /items returns the saved state.\n"
                    "- Data: None\n"
                    "- Tests: one test per acceptance criterion.\n"
                    "- Risk: None\n")
        prd = run_layout.path("demo", self.tmp, run_layout.PRD)
        criteria = ac_trace.prd_criteria(prd) if os.path.isfile(prd) else []
        table = "\n".join(f"| {r} | {'owns the decision' if r == 'backend' else 'renders it'} | "
                          f"{'yes' if r in self.new_repos else 'no'} |" for r in repos)
        coverage = "\n".join(f"- {ac} -> backend / the route, frontend / the view" for ac in criteria)
        return ("# Demo feature — plan\n"
                f"Type: major · Run: demo · PRD: {run_layout.PRD} · Status: {status}\n\n"
                "## Summary\nDeliver the confirmed demo behavior.\n\n"
                "## Decisions\n- One authority — prevents divergent state — rejected: client-owned state.\n\n"
                f"## Repositories\n| repo | role in this change | new? |\n|---|---|---|\n{table}\n\n"
                "## Design\nThe backend owns decisions; the frontend renders server state.\n\n"
                "## Interfaces\nGET /items -> 200 {items}; 404 when the list is missing.\n\n"
                "## Infrastructure\nNone\n\n## Risks and open points\nNone\n\n"
                f"## Acceptance coverage\n{coverage}\n\n## Out of scope\nNone\n")

    def write_agent_artifact(self, rel, step):
        full = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        queue = rel.split("/.engine/queues/")[-1] if "/.engine/queues/" in rel else ""
        if queue == "prd.json":
            decisions = run_layout.path("demo", self.tmp, run_layout.stage_record("prd"))
            questions = [] if os.path.exists(decisions) or self.empty_prd_queue else [{
                "id": "conflict-behavior",
                "topic": "prd-stale-request-outcome",
                "title": "Conflicting action",
                "question": "What should the user see if another action makes this request stale?",
                "why": "This defines a material failure and recovery path.",
                "proposal": "Reject the stale request, explain why, and preserve entered data.",
                "must_resolve": ["visible stale-request outcome", "recovery action"],
            }]
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
        if rel == ".maestro/runs/demo/.engine/plan-final.md":
            # the reconciled plan: the active plan as built, plus a unique marker so the `fresh`
            # check sees new proof on every visit (accepting it files this text)
            active = os.path.join(self.tmp, ACTIVE)
            base = Path(active).read_text() if os.path.isfile(active) else self.plan_text()
            Path(full).write_text(plan_doc.stamp_completed(base)
                                  + f"\n<!-- reconciled {next(_ARTIFACT_WRITES)} -->\n")
            return
        if os.path.exists(full):
            with open(full) as fh:
                previous = fh.read()
            # Keep fixtures and structured docs; rewrite this harness's own generic
            # placeholder so `fresh: true` steps see new proof on every visit.
            if not previous.startswith("artifact "):
                return
        if rel.endswith("/requirement/prd.md"):
            with open(full, "w") as fh:
                fh.write(self.prd_text())
        elif rel == ACTIVE:
            with open(full, "w") as fh:
                fh.write(self.plan_text())
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
                       "finding": "A requirement has no mechanism.", "evidence": "the plan"}]
                     if outputs.get("blocking") else [])
            Path(self.tmp, findings).write_text(json.dumps({"schema_version": 1,
                                                            "findings": items}))
        resolutions = next((rel for rel in act.get("artifacts", [])
                            if rel.endswith(".resolutions.json")), None)
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

    def implementation_outputs(self, act):
        def prompt_value(name):
            match = re.search(rf"^- {re.escape(name)}: (.+)$", act["prompt"], re.MULTILINE)
            self.assertIsNotNone(match, f"missing {name} in implementation prompt")
            return match.group(1).strip()

        repo = prompt_value("stack")
        repo_path = os.path.join(self.tmp, prompt_value("repo_path"))
        branch = prompt_value("branch")
        given = re.search(r"^- worktree: (.+)$", act["prompt"], re.MULTILINE)
        # the engine's own feature worktree when worktrees.py ran for real, else the agent's
        worktree = (given.group(1).strip() if given and os.path.isdir(given.group(1).strip())
                    else os.path.join(self.tmp, ".maestro", "test-worktrees", repo))
        os.makedirs(os.path.dirname(worktree), exist_ok=True)
        if not os.path.exists(worktree):
            subprocess.run(["git", "-C", repo_path, "worktree", "add", "-q", "-b",
                            branch, worktree, "HEAD"], check=True)
        commit = subprocess.run(["git", "-C", worktree, "rev-parse", "HEAD"], check=True,
                                capture_output=True, text=True).stdout.strip()
        return {"branch": branch, "worktree": worktree, "commit": commit,
                "summary": "built", "tests_passed": True, "escalate": False,
                "escalation": "None"}

    def slice_outputs(self, act):
        """One slice agent: commits a file of its own in the slice worktree it was given."""
        def prompt_value(name):
            return re.search(rf"^- {re.escape(name)}: (.+)$", act["prompt"],
                             re.MULTILINE).group(1).strip()
        worktree, branch, group = (prompt_value("worktree"), prompt_value("branch"),
                                   prompt_value("group_id"))
        self.assertEqual(subprocess.run(["git", "-C", worktree, "branch", "--show-current"],
                                        check=True, capture_output=True,
                                        text=True).stdout.strip(), branch)
        Path(worktree, f"slice-{group}.txt").write_text(f"{group}\n")
        subprocess.run(["git", "-C", worktree, "add", "-A"], check=True)
        subprocess.run(["git", "-C", worktree, "commit", "-q", "-m", f"slice {group}"], check=True)
        commit = subprocess.run(["git", "-C", worktree, "rev-parse", "HEAD"], check=True,
                                capture_output=True, text=True).stdout.strip()
        return {"branch": branch, "commit": commit, "summary": f"built {group}",
                "tests_passed": True, "escalate": False, "escalation": "None"}

    # -- driver ----------------------------------------------------------

    def drive(self, gate_script, max_steps=200, agent_overrides=None, mode=None, inputs=None,
              workflow=".maestro/workflows/sdlc-main.yaml", force=False, after=None):
        """Run the pipeline: gate_script maps step path -> list of (option, input) taken
        in order. Gates the run mode lets the engine answer appear in the trace as
        ("auto_gate", step). Returns (final_action, trace)."""
        trace = []
        gate_ptr = {}
        overrides = agent_overrides or {}
        with statemod.locked("demo", self.tmp):
            data, _created = resolver.init_run(
                "demo", workflow, {"feature": "Demo", "path": self.plan_type, **(inputs or {})},
                self.tmp, force=force, mode=mode)
            statemod.save("demo", data, self.tmp)  # a resume clears the pause: keep it
        for _ in range(max_steps):
            run = resolver.Run("demo", self.tmp)
            answered = resolver.apply_autopilot(run)
            if answered:
                trace.extend((f"auto_{item['kind']}", stage_path(item["step"])) for item in answered)
                statemod.save("demo", run.state, self.tmp)
            action = resolver.next_action(run)
            kind = action["action"]
            if kind in ("done", "failed", "paused"):
                return action, trace
            if kind == "run_agents":
                batch = action["agents"]
            else:
                batch = [action]
            for act in batch:
                real = act["step"]
                step = stage_path(real)
                # an agent's engine check runs under the agent's step: trace it apart
                trace.append((act["action"], step + "#check" if act.get("check") else step))
                if "prompt" in act:
                    self.prompts.setdefault(step, []).append(act["prompt"])
                run = resolver.Run("demo", self.tmp)
                if act["action"] in ("run_agent", "run_lead"):
                    for rel in act.get("artifacts", []):
                        self.write_agent_artifact(rel, real)
                    node = step.rsplit("/", 1)[-1]
                    override = overrides.get(node)
                    outputs = (
                        override() if callable(override) else override
                    ) or (
                        self.implementation_outputs(act) if node == "implement"
                        else self.slice_outputs(act) if node == "implement_slice"
                        else canned_agent_outputs(real, act)
                    )
                    self.write_review_files(act, node, outputs)
                    resolver.complete_step(run, real, outputs=outputs)
                elif act["action"] == "run_script":
                    # actually run the real script where it's an engine helper; stub others
                    if ("oq_serve" in step or "validate_tasks" in step
                            or any(a.endswith("validate_tasks.py") for a in act.get("argv", []))
                            or any(a.endswith("validate_prd.py") or a.endswith("validate_prd_questions.py")
                                   for a in act.get("argv", []))
                            or any("mem_consolidate" in a or "plan_doc" in a or "entry_serve" in a
                                   or "implementation_pool" in a or "workspace_sync" in a
                                   or "repo_checks" in a
                                   or "prd_source.py" in a or "ac_trace.py" in a
                                   or "qa_env.py" in a or "deliver.py" in a
                                   or "decision_log.py" in a
                                   or "findings.py" in a
                                   or "greenfield.py" in a
                                   or "release_record.py" in a or "slice_pool.py" in a
                                   or ("worktrees.py" in a and self.real_worktrees)
                                   for a in act.get("argv", []))):
                        proc = subprocess.run(act["argv"], cwd=self.tmp, capture_output=True,
                                              text=True, timeout=30)
                        code, out = proc.returncode, proc.stdout
                    else:
                        code, out = canned_script(real)
                    resolver.complete_step(run, real, exit_code=code, stdout=out)
                    if (after or {}).get(step):  # a person or process touching the workspace
                        after[step]()
                elif act["action"] == "ask_gate":
                    decisions = gate_script.get(step)
                    if decisions is None and step == "archive/confirm_archive":
                        decisions = [("archive", None)]
                    self.assertTrue(decisions, f"unscripted gate: {step} ({act['prompt'][:80]})")
                    i = gate_ptr.get(step, 0)
                    self.assertLess(i, len(decisions), f"gate {step} asked more than scripted")
                    option, text = decisions[i]
                    gate_ptr[step] = i + 1
                    selected = next(o for o in act["options"] if o["id"] == option)
                    resolver.record_gate(run, real, option)
                    if selected.get("input"):
                        self.assertIsNotNone(text, f"{step}/{option} requires scripted input")
                        pending = resolver.next_action(run)
                        self.assertEqual(pending["action"], "ask_input")
                        self.assertEqual(pending["field"], selected["input"])
                        trace.append(("ask_input", step))
                        resolver.record_gate_input(run, real, text)
                elif act["action"] == "ask_interview":
                    resolver.record_interview(
                        run, real, act["section"],
                        answer=None if act.get("proposal") else f"Confirmed {act['title']}",
                        accept=bool(act.get("proposal")),
                    )
                elif act["action"] == "ask_interview_batch":
                    resolver.record_interview_batch(run, real, {
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

    DESIGN_GATES = {
        "design/prd/prd_approval": [("approve", None)],
        "design/plan/brainstorm_confirm": [("write", None)],
        "design/plan/plan_approval": [("approve", None)],
        "delivery/release_approval": [("approve", None)],
    }

    def gates(self, **replace):
        """The default person's answers, with some replaced (by the gate's short name, e.g.
        plan_approval=[...]; the stage prefix is added)."""
        prefixes = {"prd_approval": "design/prd/", "brainstorm_confirm": "design/plan/",
                    "plan_approval": "design/plan/", "release_approval": "delivery/"}
        gates = {k: list(v) for k, v in self.DESIGN_GATES.items()}
        for name, decisions in replace.items():
            gates[prefixes.get(name, "") + name] = decisions
        return gates

    def vcs(self, *args, root=None):
        return subprocess.run(["git", "-C", root or self.tmp, *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_happy_path(self):
        self.prep_tasks_json()
        action, trace = self.drive(dict(self.DESIGN_GATES))
        self.assertEqual(action["action"], "done", action)
        self.assertEqual(action["outputs"]["plan"], COMPLETED)  # filed at archive
        self.assertEqual(action["outputs"]["approved_plan"], ACTIVE)
        self.assertEqual(action["outputs"]["implementation_manifest"],
                         ".maestro/runs/demo/build/manifest.json")
        steps = [s for _, s in trace]
        self.assertIn("workspace_sync_initial/plan", steps)
        self.assertIn("workspace_sync_initial/lock", steps)
        self.assertIn("delivery/workspace_sync_pre_impl/plan", steps)
        self.assertIn("delivery/workspace_sync_pre_impl/lock", steps)
        self.assertNotIn("workspace_sync_initial/refresh_knowledge", steps)
        # both planned repos implemented through runtime claims, not hard-coded stacks
        impl_steps = [s for s in steps if s.endswith("/impl/implement")]
        review_steps = [s for s in steps if s.endswith("/impl/review")]
        self.assertEqual(len(impl_steps), 2)
        self.assertEqual(len(review_steps), 2)
        # the lead confirms context, grills one material edge, and writes the PRD once
        self.assertIn("design/intake/project_context", steps)
        self.assertIn("design/prd/prd_interview", steps)
        self.assertIn("design/prd/write_prd", steps)
        # the people in the loop: the PRD, the brainstorm confirmation, the plan, the release,
        # the archive; the test cases have no gate of their own
        gate_steps = [s for a, s in trace if a == "ask_gate"]
        self.assertEqual(gate_steps, ["design/prd/prd_approval", "design/plan/brainstorm_confirm",
                                      "design/plan/plan_approval", "delivery/release_approval",
                                      "archive/confirm_archive"])
        # the brainstorm precedes the one plan write, its check, commit and approval
        order = ["design/prd/prd_approval", "design/plan/brainstorm", "design/plan/brainstorm_confirm",
                 "design/plan/write_plan", "design/plan/commit_plan",
                 "design/plan/plan_approval", "design/plan/record_approval",
                 "design/bind_test_cases", "delivery/design_check", impl_steps[0]]
        self.assertEqual([steps.index(step) for step in order],
                         sorted(steps.index(step) for step in order))
        self.assertEqual(steps.count("design/plan/write_plan"), 1)
        self.assertEqual(steps.count("design/plan/brainstorm"), 1)
        for gone in ("design/hld", "design/lld", "design/contract", "design/sizing"):
            self.assertFalse([s for s in steps if s.startswith(gone)], gone)
        # the test cases come from the approved PRD alone, beside the plan: they are written once
        # and the approval is bound to them before delivery
        self.assertLess(steps.index("design/prd/prd_approval"), steps.index("design/tests/test_cases"))
        self.assertLess(steps.index("design/tests/test_cases#check"), steps.index("design/bind_test_cases"))
        self.assertEqual(steps.count("design/tests/test_cases"), 1)
        tests_prompt = self.prompts["design/tests/test_cases"][0]
        self.assertIn("from the approved PRD at", tests_prompt)
        self.assertNotIn("- plan_path:", tests_prompt)
        write_prompt = self.prompts["design/plan/write_plan"][0]
        self.assertIn("Plan type: major", write_prompt)
        self.assertIn("docs/plans/active/demo.md", write_prompt)
        self.assertLess(steps.index("delivery/finalize_implementation"), steps.index("delivery/qa/qa_run"))
        # the plan is bound to the PRD and the test cases, and names the repositories in scope
        run_dir = Path(self.tmp, ".maestro/runs/demo")
        approval = json.loads((run_dir / ".engine/plan-approval.json").read_text())
        self.assertTrue(approval["plan"])
        self.assertEqual(sorted(approval["repos"]), ["backend", "frontend"])
        self.assertTrue(approval["test_cases_sha256"])
        self.assertEqual(json.loads((run_dir / ".engine/plan-scope.json").read_text())["selected"],
                         ["backend", "frontend"])
        # one decision log across the design stages, shown at the PRD approval
        log = (run_dir / "decisions/decision-log.md").read_text()
        self.assertIn("## PRD", log)
        self.assertEqual(sorted(p.name for p in (run_dir / "decisions").iterdir()),
                         ["brainstorm.md", "decision-log.md", "prd.json"])
        self.assertIn("Decisions: 1 decision(s)", self.prompts["design/prd/prd_approval"][0])
        # the drift check is handed the plan
        self.assertIn("docs/plans/active/demo.md", self.prompts["delivery/drift_check"][0])
        # after release approval: the verified branches are reported (default branch mode:
        # nothing pushed), the plan is filed as completed, then lessons are harvested
        self.assertLess(steps.index("archive/deliver"), steps.index("archive/plan_reconcile"))
        self.assertLess(steps.index("archive/plan_commit"), steps.index("archive/harvest/retrospect"))
        self.assertNotIn("archive/plan_changes", steps)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ACTIVE)))
        completed = Path(self.tmp, COMPLETED).read_text()
        self.assertIn("Status: completed", completed)
        self.assertIn("## Acceptance coverage", completed)
        self.assertEqual(self.vcs("log", "-1", "--format=%s"), "plan(demo): completed")
        self.assertEqual(self.vcs("status", "--porcelain", "--", "docs/plans"), "")
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
            "design/plan/brainstorm_confirm": [("write", None)],
            "design/plan/plan_approval": [("approve", None)],
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

    # the gates a person answers in every run mode (autopilot never answers them)
    PLAN_PERSON = {
        "design/plan/brainstorm_confirm": [("write", None)],
        "design/plan/plan_approval": [("approve", None)],
    }

    PLAN_ASKED = ["design/plan/brainstorm_confirm", "design/plan/plan_approval"]

    def test_auto_mode_turns_a_client_prd_into_an_approved_prd_unasked(self):
        self.prep_tasks_json()
        self.write_client_prd()
        action, trace = self.drive(self.PLAN_PERSON, mode="auto")
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
            "design/plan/brainstorm_confirm": [("write", None)],
            "design/plan/plan_approval": [("approve", None), ("approve", None)],
            "delivery/release_approval": [("revise", "handle the empty state"), ("approve", None)],
        }
        # two full passes through every stage: more than the default step budget
        action, trace = self.drive(gates, max_steps=260)
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
            "design/plan/brainstorm_confirm": [("write", None)],
            "design/plan/plan_approval": [("approve", None)],
            "delivery/release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        # PRD written twice (rescope re-runs the product role's prepare job despite a valid old
        # file); the second write is a full update, not a targeted revision
        self.assertEqual(steps.count("design/prd/write_prd"), 2)
        self.assertEqual(steps.count("design/prd/prd_interview"), 1)
        self.assertEqual(steps.count("design/plan/write_plan"), 1)
        self.assertIn("PRD approval choice (empty before the first approval): rescope", self.prompts["design/prd/write_prd"][1])

    def test_prd_revise_is_a_targeted_edit(self):
        """Revise edits the PRD in place under the engine's check — no goal confirm, interview,
        or rewrite."""
        self.prep_tasks_json()
        action, trace = self.drive(self.gates(prd_approval=[
            ("revise", "rename the role"), ("revise", "tighten AC-02"), ("approve", None)]))
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

    def _qa_gates(self, qa_gate):
        return {
            "design/prd/prd_approval": [("approve", None)],
            "design/plan/brainstorm_confirm": [("write", None)],
            "design/plan/plan_approval": [("approve", None)],
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
                          "review_head", "review", "review_verdict"])
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

    @staticmethod
    def blocking_once(clean):
        """A reviewer override that blocks on its first call and is clean afterwards."""
        calls = []

        def outputs():
            calls.append(1)
            return {**clean, "blocking": len(calls) == 1,
                    "summary": "1 blocker" if len(calls) == 1 else clean["summary"]}
        return outputs

    def test_design_mode_asks_for_the_prd_the_plan_and_the_archive(self):
        self.prep_tasks_json()
        action, trace = self.drive({
            "design/prd/prd_approval": [("approve", None)],
            "design/plan/brainstorm_confirm": [("write", None)],
            "design/plan/plan_approval": [("approve", None)],
        }, mode="design")
        self.assertEqual(action["action"], "done", action)
        self.assertEqual([s for a, s in trace if a == "ask_gate"],
                         ["design/prd/prd_approval", "design/plan/brainstorm_confirm",
                          "design/plan/plan_approval", "archive/confirm_archive"])
        self.assertEqual([s for a, s in trace if a == "auto_gate"], ["delivery/release_approval"])
        gates = statemod.load("demo", self.tmp)["gates"]
        self.assertEqual([(stage_path(g["step"]), g.get("auto")) for g in gates], [
            ("design/prd/prd_approval", None), ("design/plan/brainstorm_confirm", None),
            ("design/plan/plan_approval", None),
            ("delivery/release_approval", "design"), ("archive/confirm_archive", None)])
        # the person's plan approval is the hash-bound approval delivery checks
        self.assertTrue(os.path.isfile(plan_doc.approval_path("demo", self.tmp)))

    def test_auto_mode_runs_from_requirement_to_release_with_a_person_only_for_the_plan(self):
        self.prep_tasks_json()
        action, trace = self.drive({
            **self.PLAN_PERSON, "archive/confirm_archive": [("archive", None)]}, mode="auto")
        self.assertEqual(action["action"], "done", action)
        # the people: the brainstorm confirmation, the plan approval and the archive confirmation,
        # which autopilot never answers
        asked = [t for t in trace if t[0] in ("ask_gate", "ask_interview", "ask_interview_batch")]
        self.assertEqual(asked, [("ask_gate", "design/plan/brainstorm_confirm"),
                                 ("ask_gate", "design/plan/plan_approval"),
                                 ("ask_gate", "archive/confirm_archive")])
        self.assertIn(("auto_gate", "design/prd/prd_approval"), trace)
        self.assertIn(("auto_gate", "delivery/release_approval"), trace)
        self.assertEqual(self.autopilot_gates(), {"design/prd/prd_approval",
                                                  "delivery/release_approval"})
        # one autopilot round for the PRD, straight to the writer
        steps = [s for _, s in trace]
        self.assertIn(("auto_interview", "design/prd/prd_interview"), trace)
        self.assertEqual(steps.count("design/prd/prepare_prd"), 1)
        prd_context = json.loads(Path(self.tmp, ".maestro/runs/demo/decisions/prd.json").read_text())
        decision = prd_context["decisions"][0]
        self.assertEqual((decision["source"], decision["by"]), ("assumption", "autopilot"))
        log = Path(self.tmp, ".maestro/runs/demo/decisions/decision-log.md").read_text()
        self.assertIn("Run mode: auto. 1 assumption, 0 left open", log)
        self.assertIn("**PRD · ", log)
        self.assertIn("design/prd/prd_approval → approve (auto mode", log)
        self.assertLess(steps.index("delivery/assumptions"), steps.index("delivery/review_pack"))
        # a release nobody approved is recorded as such; pull-request delivery opens drafts from it
        self.assertEqual(statemod.load("demo", self.tmp)["steps"][
            "delivery/release_approval"]["outputs"]["by"], "autopilot")
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, COMPLETED)))

    def autopilot_gates(self):
        """The gates the engine answered itself in the run so far."""
        return {stage_path(g["step"]) for g in statemod.load("demo", self.tmp)["gates"]
                if g.get("auto")}

    def test_declining_the_archive_delivers_nothing_and_leaves_docs_untouched(self):
        self.prep_tasks_json()
        action, trace = self.drive({**self.PLAN_PERSON, "archive/confirm_archive": [("skip", None)]},
                                   mode="auto")
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertIn("archive/confirm_archive", steps)
        self.assertFalse([s for s in steps
                          if s.startswith(("archive/deliver", "archive/plan", "archive/harvest",
                                           "archive/cleanup"))])
        prompt = self.prompts["archive/confirm_archive"][0]
        self.assertIn("deliver the code yourself", prompt)
        # the default delivery mode is `branch`: the question must not promise a push
        self.assertIn("nothing is pushed", prompt)
        # the plan stays where it was approved until the archive runs
        self.assertIn("plan stays in docs/plans/active/", prompt)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, ACTIVE)))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, COMPLETED)))
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
        self.drive({**self.PLAN_PERSON, "archive/confirm_archive": [("skip", None)]}, mode="auto")
        action, trace = self.drive({"confirm_archive": [("archive", None)]},
                                   workflow=".maestro/workflows/archive.yaml", force=True)
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertEqual(steps[:3], ["check_release", "confirm_archive", "deliver"])
        self.assertIn("harvest/retrospect", steps)
        self.assertEqual(steps[-1], "cleanup")
        # the plan is filed on the later pass too
        self.assertLess(steps.index("plan_reconcile"), steps.index("plan_commit"))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, COMPLETED)))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ACTIVE)))
        delivery = json.loads(Path(self.tmp, ".maestro/runs/demo/release/delivery.json").read_text())
        self.assertEqual(len(delivery["repositories"]), 2)

    def test_the_archive_refuses_a_feature_whose_release_was_not_approved(self):
        action, trace = self.drive({}, workflow=".maestro/workflows/archive.yaml")
        self.assertEqual(action["action"], "failed", action)
        self.assertEqual([s for _, s in trace], ["check_release"])

    def test_acceptance_criteria_are_traced_through_qa_to_the_release_gate(self):
        self.prep_tasks_json()
        action, trace = self.drive(dict(self.DESIGN_GATES))
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        # the catalog is written from the PRD and checked by the engine, with no gate
        self.assertLess(steps.index("design/prd/prd_approval"),
                        steps.index("design/tests/test_cases"))
        self.assertLess(steps.index("design/tests/test_cases#check"),
                        steps.index("delivery/design_check"))
        self.assertNotIn("ask_gate", [a for a, s in trace if s.startswith("design/tests/")])
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
                feedback = self.prompts["design/tests/test_cases"][-1]
                self.assertIn("failed the engine's check", feedback)
                self.assertIn("criteria the PRD does not have: AC-07", feedback)
                self.assertIn("no test case traces AC-01", feedback)
            catalog.write_text("### TC-demo-001 — wrong\n\n- **Traces:** AC-07\n"
                               if len(calls) == 1 else
                               "### TC-demo-001 — right\n\n- **Traces:** AC-01\n")
            return {"test_cases_path": str(catalog), "case_count": 1}
        action, trace = self.drive(dict(self.DESIGN_GATES), agent_overrides={"test_cases": test_cases})
        self.assertEqual(action["action"], "done", action)
        tests = [s.rsplit("/", 1)[-1] for _, s in trace if s.startswith("design/tests/")]
        self.assertEqual(tests, ["test_cases", "test_cases#check", "test_cases",
                                 "test_cases#check"])
        self.assertEqual(len(calls), 2)

    def test_auto_mode_stops_at_release_when_a_criterion_fails_qa(self):
        self.prep_tasks_json()
        self.qa_case_status = "failed"
        action, trace = self.drive({**self.PLAN_PERSON, "delivery/release_approval": [("reject", None)]}, mode="auto")
        self.assertEqual(action["action"], "failed", action)
        self.assertEqual([s for a, s in trace if a == "ask_gate"],
                         self.PLAN_ASKED + ["delivery/release_approval"])
        self.assertIn("0/1 acceptance criteria passing — AC-01 failing",
                      Path(self.tmp, ".maestro/runs/demo/release/ac-trace.md").read_text())

    def test_blocking_design_drift_stops_an_autopilot_release(self):
        self.prep_tasks_json()
        drift = {"review_path": "reviews/drift.md", "blocking": True,
                 "summary": "backend returns 200 where the plan says 201"}
        action, trace = self.drive({**self.PLAN_PERSON, "delivery/release_approval": [("reject", None)]},
                                   agent_overrides={"drift_check": drift}, mode="auto")
        self.assertEqual(action["action"], "failed", action)
        steps = [s for _, s in trace]
        self.assertLess(steps.index("delivery/ac_trace"), steps.index("delivery/drift_check"))
        self.assertLess(steps.index("delivery/drift_verdict"), steps.index("delivery/review_pack"))
        self.assertEqual([s for a, s in trace if a == "ask_gate"],
                         self.PLAN_ASKED + ["delivery/release_approval"])
        self.assertIn("Design drift (engine): 1 blocking finding",
                      self.prompts["delivery/release_approval"][0])

    def test_an_open_major_review_finding_stops_an_autopilot_release(self):
        self.prep_tasks_json()
        original = self.write_review_files

        def write_review_files(act, node, outputs):
            original(act, node, outputs)
            if node == "review":  # the code review: a major finding nobody fixed or withdrew
                rel = next(r for r in act["artifacts"] if r.endswith(".findings.json"))
                Path(self.tmp, rel).write_text(json.dumps({"schema_version": 1, "findings": [
                    {"id": "M1", "severity": "major", "area": "correctness", "status": "open",
                     "finding": "Month-end due dates drift.", "evidence": "billing.go:210"}]}))
        self.write_review_files = write_review_files
        action, trace = self.drive({**self.PLAN_PERSON, "delivery/release_approval": [("reject", None)]}, mode="auto")
        self.assertEqual(action["action"], "failed", action)
        steps = [s for _, s in trace]
        self.assertLess(steps.index("delivery/open_findings"), steps.index("delivery/review_pack"))
        self.assertEqual([s for a, s in trace if a == "ask_gate"],
                         self.PLAN_ASKED + ["delivery/release_approval"])
        self.assertIn("Open code-review findings (engine): 0 blocking and 2 major",
                      self.prompts["delivery/release_approval"][0])

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
                "design/plan/brainstorm_confirm": [("write", None)],
                "design/plan/plan_approval": [("approve", None)],
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
            "design/plan/brainstorm_confirm": [("write", None)],
            "design/plan/plan_approval": [("approve", None)],
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
            "design/plan/brainstorm_confirm": [("write", None)],
            "design/plan/plan_approval": [("approve", None)],
            "delivery/release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates, agent_overrides={"fix": fix_outputs})
        self.assertEqual(action["action"], "done", action)
        def slot_steps(slot):
            return [s.rsplit("/", 1)[-1] for _, s in trace
                    if s.startswith(f"delivery/implement[{slot}]/impl/")]

        # slot_1 claims backend (repos are claimed in name order); slot_2 claims frontend
        # domain_rules (optional, never blocks) runs after every passing verify
        self.assertEqual(slot_steps("slot_1")[-10:], ["verify", "fix", "review_resolution", "handoff",
                                                       "verify", "domain_rules", "review_scope",
                                                       "review_head", "review", "review_verdict"])
        self.assertEqual(slot_steps("slot_2")[-6:], ["verify", "domain_rules", "review_scope",
                                                      "review_head", "review", "review_verdict"])
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
        "design/plan/brainstorm_confirm": [("write", None)],
        "design/plan/plan_approval": [("approve", None)],
        "delivery/release_approval": [("approve", None)],
    }

    @staticmethod
    def impl_steps(trace, node):
        """The impl steps of the first repository slot that ran `node` (slots interleave)."""
        slot = next(s.split("]")[0] for _, s in trace if s.endswith(f"/impl/{node}"))
        return [s.rsplit("/", 1)[-1] for _, s in trace if s.startswith(slot + "]/impl/")]

    def test_a_plan_with_two_slice_groups_is_built_by_the_engine_fan_out(self):
        """backend's plan has two slice groups: one agent per group, each in its own slice
        worktree, merged by the engine into the feature branch, then verified and reviewed as
        usual. frontend's one-group plan keeps the single implementer."""
        self.prep_tasks_json()
        backend = Path(self.tmp, ".maestro/runs/demo/build/backend/tasks.json")
        doc = json.loads(backend.read_text())
        doc["slices"] = [{"group_id": "api", "task_ids": ["t1", "t2"]},
                         {"group_id": "jobs", "task_ids": ["t3"]}]
        doc["tasks"] = [
            {**doc["tasks"][0], "id": "t1", "group_id": "api", "writes": ["slice-api.txt"]},
            {**doc["tasks"][0], "id": "t2", "group_id": "api", "writes": ["src/api_test"],
             "depends_on": ["t1"]},
            {**doc["tasks"][0], "id": "t3", "group_id": "jobs", "writes": ["slice-jobs.txt"]}]
        backend.write_text(json.dumps(doc))
        self.real_worktrees = True  # the engine creates the feature worktrees
        action, trace = self.drive(dict(self.IMPL_GATES))
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        # repos are claimed in name order: slot_1 builds backend, slot_2 frontend
        backend_impl = "delivery/implement[slot_1]/impl/"
        slices = sorted(s for s in steps if s.startswith(backend_impl + "slices/")
                        and s.endswith("/implement_slice"))
        self.assertEqual(slices, [backend_impl + "slices/pool[slot_1]/implement_slice",
                                  backend_impl + "slices/pool[slot_2]/implement_slice"])
        self.assertNotIn(backend_impl + "implement", steps)
        self.assertIn("delivery/implement[slot_2]/impl/implement", steps)
        self.assertFalse([s for s in steps
                          if s.startswith("delivery/implement[slot_2]/impl/slices/")])
        order = [backend_impl + n for n in ("facts", "slices/merge", "handoff", "verify", "review")]
        self.assertEqual([steps.index(s) for s in order], sorted(steps.index(s) for s in order))
        prompt = self.prompts[backend_impl + "slices/pool[slot_1]/implement_slice"][0]
        self.assertIn("Implement ONLY slice group api", prompt)
        self.assertIn("- task_ids: t1,t2", prompt)
        # both slices are on the feature branch the release ships
        repo = os.path.join(self.tmp, "codebase", "backend")

        def git_out(*args):
            return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True,
                                  text=True).stdout.strip()
        manifest = json.loads(Path(self.tmp, ".maestro/runs/demo/build/manifest.json").read_text())
        shipped = next(r for r in manifest["repositories"] if r["repo"] == "backend")
        self.assertEqual(shipped["branch"], "feature/demo-backend")
        self.assertEqual(shipped["commit"], git_out("rev-parse", "feature/demo-backend"))
        self.assertEqual(shipped["verification"]["status"], "verified")
        files = git_out("ls-tree", "--name-only", "feature/demo-backend").split()
        self.assertIn("slice-api.txt", files)
        self.assertIn("slice-jobs.txt", files)
        # merged slice branches are deleted with their worktrees
        self.assertEqual(git_out("branch", "--list", "*-slice-*"), "")

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
        self.assertEqual(steps[start:start + 10], ["review_verdict", "fix", "review_resolution",
                                                   "handoff", "verify", "domain_rules",
                                                   "review_scope", "review_head", "review",
                                                   "review_verdict"])

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

    def test_prd_interview_path_when_requirement_empty(self):
        """An empty requirement uses lead-only clarification and a durable interview."""
        req_dir = os.path.join(self.tmp, ".maestro", "runs", "demo", "requirement")
        for name in os.listdir(req_dir):
            os.remove(os.path.join(req_dir, name))
        with statemod.locked("demo", self.tmp):
            resolver.init_run("demo", ".maestro/workflows/design.yaml", {"feature": "Demo", "path": "major"}, self.tmp)

        seen = []
        interview_sections = []
        reached_plan = False
        for _ in range(80):
            run = resolver.Run("demo", self.tmp)
            action = resolver.next_action(run)
            # the plan and the test cases run side by side: a wave holds both
            batch = action["agents"] if action["action"] == "run_agents" else [action]
            for action in batch:
                run = resolver.Run("demo", self.tmp)
                step = action.get("step")
                if action["action"] in ("run_agent", "run_lead"):
                    seen.append(step.rsplit("/", 1)[-1])
                    for rel in action.get("artifacts", []):
                        self.write_agent_artifact(rel, step)
                    node = step.rsplit("/", 1)[-1]
                    if node == "brainstorm":
                        reached_plan = True
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
            if reached_plan:
                break
        else:
            self.fail("PRD interview path did not reach the plan brainstorm")

        self.assertTrue(reached_plan, "never reached the plan brainstorm")
        self.assertIn("project_context", seen)
        self.assertIn("write_prd", seen)
        self.assertEqual(len(interview_sections), 1)
        context_path = os.path.join(self.tmp, ".maestro", "runs", "demo", "decisions",
                                    "prd.json")
        with open(context_path) as fh:
            context = json.load(fh)
        self.assertEqual(len(context["decisions"]), 1)

    # -- the plan flow ------------------------------------------------------------------------

    def test_major_plan_is_discussed_written_checked_filed_unchanged(self):
        """brainstorm (kept going once) -> write -> commit -> approve -> tests -> bind -> deliver
        -> archive with nothing to reconcile: the approved plan is filed as it was approved."""
        self.prep_tasks_json()
        action, trace = self.drive(self.gates(
            brainstorm_confirm=[("more", None), ("write", None)]))
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        # "keep talking" returns to the brainstorm; nothing is written until the person says write
        self.assertEqual(steps.count("design/plan/brainstorm"), 2)
        self.assertEqual(steps.count("design/plan/brainstorm_confirm"), 2)
        self.assertEqual(steps.count("design/plan/write_plan"), 1)
        self.assertGreater(steps.index("design/plan/write_plan"),
                           len(steps) - 1 - steps[::-1].index("design/plan/brainstorm"))
        self.assertIn("Notes: .maestro/runs/demo/decisions/brainstorm.md",
                      self.prompts["design/plan/brainstorm_confirm"][0])
        # the plan is saved before it is asked about
        self.assertIn("docs/plans/active/demo.md", self.prompts["design/plan/plan_approval"][0])
        self.assertEqual(steps.count("design/plan/commit_plan"), 1)
        subjects = self.vcs("log", "--format=%s").splitlines()
        self.assertIn("plan(demo): created", subjects)
        self.assertEqual(subjects[0], "plan(demo): completed")
        # reconciled with nothing to confirm: filed as approved, never asked
        self.assertIn("archive/plan_archive", steps)
        self.assertNotIn("archive/plan_archive_final", steps)
        self.assertNotIn("archive/plan_changes", steps)
        run_dir = Path(self.tmp, ".maestro/runs/demo")
        self.assertTrue((run_dir / ".engine/plan-final.md").is_file())
        self.assertTrue((run_dir / "release/plan-changes.md").is_file())
        # the filed plan is a valid major plan: every repository, every PRD criterion
        self.assertEqual(plan_doc.validate("demo", self.tmp, "major", completed=True), [])
        completed = Path(self.tmp, COMPLETED).read_text()
        self.assertIn("Status: completed", completed)
        self.assertEqual([name for name, _new in plan_doc.repositories(completed)],
                         ["backend", "frontend"])
        self.assertIn("AC-01", completed)
        self.assertNotIn("reconciled", completed)  # the approved text, not the reconciled copy
        self.assertEqual(plan_doc.status("demo", self.tmp),
                         {"active": False, "completed": True, "path": COMPLETED})

    def test_minor_change_has_a_mini_prd_without_approval_and_a_short_plan(self):
        self.plan_type = "minor"
        self.empty_prd_queue = True  # a clear requirement: nothing material to ask
        self.prep_tasks_json()
        action, trace = self.drive({
            "design/plan/brainstorm_confirm": [("write", None)],
            "design/plan/plan_approval": [("approve", None)],
            "delivery/release_approval": [("approve", None)],
        })
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        # a clear minor requirement: the mini PRD is written and goes straight on, unasked
        self.assertNotIn("design/prd/prd_approval", steps)
        self.assertNotIn("design/prd/prd_interview", steps)
        self.assertEqual(steps.count("design/prd/prepare_prd"), 1)
        self.assertLess(steps.index("design/prd/write_prd"), steps.index("design/prd/sync_decisions"))
        self.assertIn("PRD type: minor", self.prompts["design/prd/write_prd"][0])
        prd = Path(self.tmp, ".maestro/runs/demo/requirement/prd.md").read_text()
        for heading in ("## Problem", "## Acceptance criteria", "## Out of scope"):
            self.assertIn(heading, prd)
        self.assertNotIn("## Summary", prd)
        # the plan is 5-10 lines
        self.assertIn("Plan type: minor", self.prompts["design/plan/write_plan"][0])
        completed = Path(self.tmp, COMPLETED).read_text()
        self.assertTrue(5 <= len(plan_doc.parse(completed)["body"]) <= 10, completed)
        self.assertEqual(plan_doc.validate("demo", self.tmp, "minor", completed=True), [])
        self.assertEqual(self.vcs("log", "-1", "--format=%s"), "plan(demo): completed")

    def test_a_minor_plan_over_ten_lines_fails_the_write_plan_check(self):
        self.plan_type = "minor"
        self.empty_prd_queue = True
        self.prep_tasks_json()
        calls = []

        def write_plan():
            calls.append(1)
            text = self.plan_text()
            if len(calls) == 1:  # six more lines than a minor plan may have
                text += "".join(f"- Note {n}: more detail\n" for n in range(6))
            Path(self.tmp, ACTIVE).write_text(text)
            return {"summary": "written"}
        action, trace = self.drive({
            "design/plan/brainstorm_confirm": [("write", None)],
            "design/plan/plan_approval": [("approve", None)],
            "delivery/release_approval": [("approve", None)],
        }, agent_overrides={"write_plan": write_plan})
        self.assertEqual(action["action"], "done", action)
        self.assertEqual(len(calls), 2)
        plan = [s.rsplit("/", 1)[-1] for _, s in trace if s.startswith("design/plan/")]
        start = plan.index("write_plan")
        # the engine's check sends it back to the writer before the plan is ever committed
        self.assertEqual(plan[start:start + 5], ["write_plan", "write_plan#check", "write_plan",
                                                 "write_plan#check", "commit_plan"])
        retry = self.prompts["design/plan/write_plan"][1]
        self.assertIn("failed the engine's check", retry)
        self.assertIn("a minor plan has 5–10 non-blank lines", retry)
        self.assertIn("this one has 13", retry)
        self.assertEqual(plan.count("commit_plan"), 1)

    def test_a_plan_that_misses_a_criterion_goes_back_to_the_writer(self):
        self.prep_tasks_json()
        calls = []

        def write_plan():
            calls.append(1)
            text = self.plan_text()
            if len(calls) == 1:
                text = text.replace("- AC-01 -> backend / the route, frontend / the view\n", "")
            Path(self.tmp, ACTIVE).write_text(text)
            return {"summary": "written"}
        action, trace = self.drive(dict(self.DESIGN_GATES), agent_overrides={"write_plan": write_plan})
        self.assertEqual(action["action"], "done", action)
        self.assertEqual(len(calls), 2)
        self.assertIn("Acceptance coverage does not cover AC-01",
                      self.prompts["design/plan/write_plan"][1])

    def test_plan_approval_later_pauses_and_a_resume_asks_the_same_question(self):
        self.prep_tasks_json()
        action, trace = self.drive(self.gates(plan_approval=[("later", None)]))
        self.assertEqual(action["action"], "paused", action)
        self.assertEqual(action["resume"], "/maestro demo")
        self.assertEqual(trace[-1], ("ask_gate", "design/plan/plan_approval"))
        asked_before = self.prompts["design/plan/plan_approval"][0]
        # nothing was lost: the plan is saved, the delivery has not started
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, ACTIVE)))
        self.assertFalse(os.path.isfile(plan_doc.approval_path("demo", self.tmp)))
        # init resumes the run; the same gate is served again, and nothing is redone
        action, trace = self.drive(self.gates(plan_approval=[("approve", None)]))
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertEqual(trace[0], ("ask_gate", "design/plan/plan_approval"))
        self.assertEqual(self.prompts["design/plan/plan_approval"][1], asked_before)
        for redone in ("design/plan/brainstorm", "design/plan/write_plan", "design/prd/write_prd"):
            self.assertNotIn(redone, steps)
        self.assertTrue(os.path.isfile(plan_doc.approval_path("demo", self.tmp)))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, COMPLETED)))

    def test_plan_revise_sends_the_feedback_to_the_writer_and_commits_an_update(self):
        self.prep_tasks_json()
        calls = []

        def write_plan():
            calls.append(1)
            if len(calls) == 2:  # a targeted edit of the plan the person asked to change
                path = Path(self.tmp, ACTIVE)
                path.write_text(path.read_text().replace(
                    "## Risks and open points\nNone", "## Risks and open points\nLists are paged."))
            return {"summary": "revised" if len(calls) == 2 else "written"}
        action, trace = self.drive(self.gates(plan_approval=[
            ("revise", "page the long lists"), ("approve", None)]), agent_overrides={
                "write_plan": write_plan})
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertIn(("ask_input", "design/plan/plan_approval"), trace)
        self.assertEqual(steps.count("design/plan/write_plan"), 2)
        self.assertEqual(steps.count("design/plan/brainstorm"), 1)  # a revision is not a rethink
        revision = self.prompts["design/plan/write_plan"][1]
        self.assertIn("page the long lists", revision)
        self.assertIn("revise", revision)
        self.assertEqual(steps.count("design/plan/commit_plan"), 2)
        subjects = self.vcs("log", "--format=%s").splitlines()
        self.assertIn("plan(demo): updated", subjects)
        self.assertIn("plan(demo): created", subjects)
        self.assertEqual(trace.count(("ask_gate", "design/plan/plan_approval")), 2)
        # the approval is bound to the revised plan
        self.assertIn("Lists are paged.", Path(self.tmp, COMPLETED).read_text())

    def test_plan_rethink_goes_back_to_the_brainstorm(self):
        self.prep_tasks_json()
        action, trace = self.drive(self.gates(
            brainstorm_confirm=[("write", None), ("write", None)],
            plan_approval=[("rethink", "use a queue instead"), ("approve", None)]))
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertEqual(steps.count("design/plan/brainstorm"), 2)
        self.assertIn("use a queue instead", self.prompts["design/plan/brainstorm"][1])
        self.assertNotIn("use a queue instead", self.prompts["design/plan/brainstorm"][0])
        self.assertEqual(steps.count("design/plan/write_plan"), 2)
        self.assertIn("use a queue instead", self.prompts["design/plan/write_plan"][1])
        self.assertLess(steps.index("design/plan/plan_approval"),
                        len(steps) - 1 - steps[::-1].index("design/plan/brainstorm"))

    def test_rejecting_the_plan_stops_the_run(self):
        self.prep_tasks_json()
        action, trace = self.drive(self.gates(plan_approval=[("reject", None)]))
        self.assertEqual(action["action"], "failed", action)
        self.assertFalse([s for _, s in trace if s.startswith("delivery/")])
        self.assertFalse(os.path.isfile(plan_doc.approval_path("demo", self.tmp)))

    # -- archive: reconciling the plan with what was built ---------------------------------------

    def changing_reconcile(self, calls):
        """A plan_reconcile that finds the code differs from the plan (a new limit) and writes the
        proposed final plan and the change list, with new content on every visit."""
        def plan_reconcile():
            calls.append(1)
            base = Path(self.tmp, ACTIVE).read_text()
            final = plan_doc.stamp_completed(base.replace(
                "404 when the list is missing.", "404 when the list is missing; 413 above 100k items."))
            Path(self.tmp, ".maestro/runs/demo/.engine/plan-final.md").write_text(
                final + f"<!-- pass {len(calls)} -->\n")
            Path(self.tmp, ".maestro/runs/demo/release/plan-changes.md").write_text(
                f"- GET /items returns 413 above 100k items (backend, abc123), pass {len(calls)}.\n")
            return {"changed": True, "summary": "Lists above 100k items now return 413."}
        return plan_reconcile

    def archive_with_changes(self, decisions):
        calls = []
        action, trace = self.drive(
            {**self.DESIGN_GATES, "archive/plan_changes": decisions},
            agent_overrides={"plan_reconcile": self.changing_reconcile(calls)})
        self.assertEqual(action["action"], "done", action)
        return calls, [s for _, s in trace], trace

    def test_archive_asks_which_plan_to_keep_and_accept_files_the_reconciled_plan(self):
        self.prep_tasks_json()
        calls, steps, trace = self.archive_with_changes([("accept", None)])
        self.assertIn(("ask_gate", "archive/plan_changes"), trace)
        prompt = self.prompts["archive/plan_changes"][0]
        self.assertIn("Lists above 100k items now return 413.", prompt)
        self.assertIn(".maestro/runs/demo/release/plan-changes.md", prompt)
        self.assertEqual(len(calls), 1)
        self.assertIn("archive/plan_archive_final", steps)
        self.assertNotIn("archive/plan_archive", steps)
        completed = Path(self.tmp, COMPLETED).read_text()
        self.assertIn("413 above 100k items", completed)
        self.assertIn("Status: completed", completed)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ACTIVE)))
        self.assertEqual(self.vcs("log", "-1", "--format=%s"), "plan(demo): completed")
        self.assertLess(steps.index("archive/plan_commit"), steps.index("archive/harvest/retrospect"))

    def test_archive_keep_files_the_plan_as_approved(self):
        self.prep_tasks_json()
        calls, steps, trace = self.archive_with_changes([("keep", None)])
        self.assertIn("archive/plan_archive", steps)
        self.assertNotIn("archive/plan_archive_final", steps)
        completed = Path(self.tmp, COMPLETED).read_text()
        self.assertIn("404 when the list is missing.", completed)
        self.assertNotIn("413", completed)
        self.assertIn("Status: completed", completed)
        # the differences stay in the change list
        self.assertIn("413", Path(self.tmp, ".maestro/runs/demo/release/plan-changes.md").read_text())

    def test_archive_edit_reconciles_again_with_the_feedback(self):
        self.prep_tasks_json()
        calls, steps, trace = self.archive_with_changes([
            ("edit", "the limit is 50k items, not 100k"), ("accept", None)])
        self.assertEqual(len(calls), 2)
        self.assertEqual(trace.count(("ask_gate", "archive/plan_changes")), 2)
        self.assertIn("the limit is 50k items, not 100k", self.prompts["archive/plan_reconcile"][1])
        self.assertNotIn("the limit is 50k items", self.prompts["archive/plan_reconcile"][0])
        # the second proposal (fresh content) is the one filed
        self.assertIn("<!-- pass 2 -->", Path(self.tmp, COMPLETED).read_text())
        self.assertIn("pass 2", Path(self.tmp, ".maestro/runs/demo/release/plan-changes.md").read_text())

    # -- delivery: the approval is bound to the plan -------------------------------------------------

    def test_a_plan_edited_after_approval_sends_the_run_back_to_design(self):
        self.prep_tasks_json()
        edits = []

        def edit_plan():
            if not edits:  # once: somebody edits the approved plan before delivery starts
                edits.append(1)
                path = Path(self.tmp, ACTIVE)
                path.write_text(path.read_text().replace(
                    "## Out of scope\nNone", "## Out of scope\nOffline mode."))
        action, trace = self.drive({
            **self.DESIGN_GATES,
            "design/prd/prd_approval": [("approve", None)] * 2,
            "design/plan/plan_approval": [("approve", None)] * 2,
        }, after={"design/bind_test_cases": edit_plan}, max_steps=300)
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        # design_check ran the plan_doc verify twice: stale, then current after the re-approval
        self.assertEqual(steps.count("delivery/design_check"), 2)
        self.assertEqual(steps.count("delivery/stale_note"), 1)
        stale = steps.index("delivery/stale_note")
        self.assertEqual(trace.count(("ask_gate", "design/plan/plan_approval")), 2)
        self.assertEqual(steps.count("design/plan/brainstorm"), 1)  # sent back to the writer only
        self.assertEqual(steps.count("design/plan/write_plan"), 2)
        self.assertIn("the plan changed after it was approved", self.prompts["design/plan/write_plan"][1])
        self.assertLess(stale, len(steps) - 1 - steps[::-1].index("design/plan/write_plan"))
        self.assertEqual(len([s for s in steps if s.endswith("/impl/implement")]), 2)
        self.assertIn("Offline mode.", Path(self.tmp, COMPLETED).read_text())

    # -- greenfield and slugs ------------------------------------------------------------------

    def test_greenfield_creates_and_scaffolds_the_repositories_the_plan_marks_new(self):
        self.prep_tasks_json()
        # a new product: no repositories, no recorded knowledge of them
        shutil.rmtree(os.path.join(self.tmp, "codebase"))
        shutil.rmtree(os.path.join(self.tmp, ".maestro", "index"), ignore_errors=True)
        provenance = os.path.join(self.tmp, "docs", "provenance.yaml")
        if os.path.isfile(provenance):
            os.remove(provenance)
        Path(self.tmp, "maestro.config.yaml").write_text("version: 1\nrepos: {}\n")
        # no repository at all: the workspace root is not one either (the plan commit is skipped)
        shutil.rmtree(os.path.join(self.tmp, ".git"))
        self.new_repos = ("backend", "frontend")

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
        action, trace = self.drive(dict(self.DESIGN_GATES), agent_overrides={"scaffold": scaffold})
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertIn("Greenfield (no code yet): true", self.prompts["design/plan/brainstorm"][0])
        # the repositories exist before the plan is approved
        order = ["design/plan/write_plan", "design/plan/commit_plan", "design/plan/scaffold/create",
                 "design/plan/scaffold/scaffold", "design/plan/scaffold/scaffold#check",
                 "design/plan/scaffold/pin", "design/plan/plan_approval"]
        self.assertEqual([steps.index(s) for s in order], sorted(steps.index(s) for s in order))
        config = Path(self.tmp, "maestro.config.yaml").read_text()
        self.assertIn("backend", config)
        manifest = json.loads(Path(self.tmp, ".maestro/runs/demo/build/manifest.json").read_text())
        self.assertEqual({r["repo"]: r["verification"]["status"] for r in manifest["repositories"]},
                         {"backend": "verified", "frontend": "verified"})

    def test_a_delivered_slug_cannot_be_started_again(self):
        import contextlib
        import io
        import maestroctl
        completed = Path(self.tmp, COMPLETED)
        completed.parent.mkdir(parents=True)
        completed.write_text(self.plan_text(status="completed"))

        def ctl(*argv, code=0):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                got = maestroctl.main(["--root", self.tmp, *argv])
            self.assertEqual(got, code, err.getvalue())
            return out.getvalue(), err.getvalue()
        out, _ = ctl("slug-check", "demo")
        report = json.loads(out)
        self.assertFalse(report["available"])
        self.assertIn("delivered feature", report["reason"])
        for extra in ([], ["--force"]):
            _, err = ctl("init", "--slug", "demo", "--workflow", ".maestro/workflows/sdlc-main.yaml",
                         "--input", "path=major", *extra, code=3)
            self.assertIn("delivered feature", err)
        self.assertFalse(os.path.exists(statemod.state_path("demo", self.tmp)))

    def test_only_major_and_minor_paths_start_a_run(self):
        workflow = ".maestro/workflows/sdlc-main.yaml"
        for path in ("light", "full", "auto", ""):
            with self.subTest(path=path), self.assertRaises(resolver.RunError) as caught:
                resolver.init_run("demo", workflow, {"feature": "Demo", "path": path}, self.tmp)
            self.assertIn("major", str(caught.exception))
        with self.assertRaises(resolver.RunError):  # the path is required
            resolver.init_run("demo", workflow, {"feature": "Demo"}, self.tmp)
        self.assertFalse(os.path.exists(statemod.state_path("demo", self.tmp)))
        for path in ("major", "minor"):
            with self.subTest(path=path):
                state, created = resolver.init_run(
                    "demo", workflow, {"feature": "Demo", "path": path}, self.tmp, force=True)
                self.assertTrue(created)

    def test_a_committed_plan_does_not_make_the_living_docs_look_stale(self):
        """The plan lives under docs/plans/, which the living-docs hash skips, so writing and
        committing it never makes the pre-implementation workspace sync ask its gate."""
        self.prep_tasks_json()
        gates = {**self.DESIGN_GATES,
                 "delivery/workspace_sync_pre_impl/sync_gate": [("as_is", None)]}
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        self.assertNotIn(("ask_gate", "delivery/workspace_sync_pre_impl/sync_gate"), trace)


if __name__ == "__main__":
    unittest.main()
