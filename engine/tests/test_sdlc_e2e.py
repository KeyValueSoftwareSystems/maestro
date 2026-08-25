"""Full-pipeline simulation: drives the REAL shipped workflows (sdlc-main.yaml +
design/impl/qa subworkflows) through the engine with zero LLM — canned agent outputs,
scripted gate decisions, artifacts touched on disk. This is the proof that the example
pack and the engine agree."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import resolver  # noqa: E402
import state as statemod  # noqa: E402
import codebase_scan  # noqa: E402
import workspace_sync  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def canned_agent_outputs(step, action):
    """Outputs by node id — mirrors each node's declared outputs list."""
    node = step.rsplit("/", 1)[-1]
    table = {
        "project_context": {"project_context": "A test product with backend and frontend repositories."},
        "feature_goal": {"feature_goal": "Deliver the demo feature for test users."},
        "prepare_prd_questions": {"summary": "Prepared the next focused product questions"},
        "author_prd": {"summary": "PRD written from confirmed context"},
        "repair_prd": {"summary": "PRD repaired to match the contract"},
        "prepare_hld_questions": {"summary": "Prepared architecture questions"},
        "author_hld": {"hld_summary": "3 services, 2 new tables"},
        "repair_hld": {"hld_summary": "Repaired the HLD"},
        "prepare_lld_questions": {"summary": "Prepared repository design questions"},
        "author_lld": {"lld_path": "lld.md", "contract_notes": "repo contract notes"},
        "repair_lld": {"lld_path": "lld.md", "contract_notes": "repo contract notes"},
        "contract": {"contract_summary": "5 endpoints"},
        "test_cases": {"test_cases_path": "test-cases.md", "case_count": 12},
        "arch_review": {"review_path": "reviews/architecture.md", "blocking": False,
                        "summary": "sound"},
        "tasks": {"task_count": 4, "slice_count": 2},
        "implement": {"branch": "feature/x", "worktree": "/tmp/simulated",
                      "commit": "0" * 40, "summary": "built", "tests_passed": True},
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
        # lld_repo_pool.py discovers repos under codebase/* — give it exactly backend+frontend
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
            map_path = os.path.join(path, "docs", "codebase-map.md")
            os.makedirs(os.path.dirname(map_path), exist_ok=True)
            with open(map_path, "w") as fh:
                fh.write(f"# {stack} map\n")
            head = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], check=True,
                                  capture_output=True, text=True).stdout.strip()
            codebase_scan.write_marker(map_path, head)
        # Simulate the normal /maestro-init result so the happy path proves the new sync
        # checkpoint is zero-agent/no-gate when code and knowledge are already current.
        os.makedirs(os.path.join(self.tmp, "docs"), exist_ok=True)
        with open(os.path.join(self.tmp, "docs", "architecture.md"), "w") as fh:
            fh.write("# Architecture\n")
        for surface in ("technical", "functional"):
            directory = os.path.join(self.tmp, "docs", surface)
            os.makedirs(directory)
            with open(os.path.join(directory, "demo.md"), "w") as fh:
                fh.write(f"# Demo {surface}\n")
        evidence = os.path.join(self.tmp, ".maestro", "bootstrap-evidence.md")
        with open(evidence, "w") as fh:
            fh.write("Indexed test workspace.\n")
        with __import__("contextlib").redirect_stdout(__import__("io").StringIO()):
            self.assertEqual(workspace_sync.cmd_record_knowledge(self.tmp, evidence), 0)

    def write_agent_artifact(self, rel, step):
        full = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        if any(rel.endswith(name) for name in (
                "prd-questions.json", "hld-questions.json", "lld-questions.json")):
            if rel.endswith("hld-questions.json"):
                context_name = "hld-context.json"
            elif rel.endswith("lld-questions.json"):
                context_name = "lld-context.json"
            else:
                context_name = "prd-context.json"
            decisions = os.path.join(os.path.dirname(full), context_name)
            questions = [] if os.path.exists(decisions) else [{
                "id": "conflict-behavior",
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
        if rel.endswith("hld-post-questions.json") or rel.endswith("lld-post-questions.json"):
            with open(full, "w") as fh:
                json.dump({
                    "schema_version": 2,
                    "questions": [],
                    "audit": {"unresolved": [], "contradictions": []},
                }, fh)
            return
        if os.path.exists(full):
            return
        if rel.endswith("/requirement/prd.md"):
            sections = {
                "Summary": "Deliver the confirmed demo feature.",
                "Problem and context": "The product needs the demo behavior described in this run.",
                "Users and jobs": "Test users need to complete the demo workflow.",
                "Goals and success signals": "The behavior works and its acceptance checks pass.",
                "Non-goals": "Unrelated product and platform changes are excluded.",
                "Functional scope": "Implement the confirmed demo behavior across the required surfaces.",
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
        elif rel.endswith("/hld.md"):
            sections = {
                "Decision summary": "\n".join(
                    f"- Confirmed architecture decision {index}." for index in range(1, 6)
                ),
                "Context and scope": "The approved demo spans the backend and frontend.",
                "Proposed design": "The backend owns decisions. The frontend renders server state.",
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
        elif rel.endswith("/lld.md"):
            parts = rel.split("/")
            slug = parts[parts.index("runs") + 1]
            child_state = statemod.load(slug, self.tmp)
            parent_slug = child_state["inputs"]["parent_slug"]
            repo = child_state["inputs"]["repo"]
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
        elif rel.endswith("requirement-questions.json") or rel.endswith("open-questions.json"):
            with open(full, "w") as fh:
                json.dump({"schema_version": 1, "feature_slug": "demo", "questions": []}, fh)
        else:
            with open(full, "w") as fh:
                fh.write("artifact\n")

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
                "summary": "built", "tests_passed": True}

    def drive_lld_workstreams(self, trace, gate_script):
        """Drive every repo-owned child run without mutating the parent feature state."""
        queue_path = os.path.join(
            self.tmp, ".maestro", "runs", "demo", "lld-repos.json",
        )
        with open(queue_path, encoding="utf-8") as fh:
            workstreams = json.load(fh)["workstreams"]
        for item in workstreams:
            slug, repo = item["slug"], item["repo"]
            decisions = gate_script.get(f"lld:{repo}", [("approve", None)])
            gate_index = 0
            for _ in range(20):
                run = resolver.Run(slug, self.tmp)
                action = resolver.next_action(run)
                if action["action"] == "done":
                    break
                step = action["step"]
                trace_step = f"lld:{repo}/{step}"
                trace.append((action["action"], trace_step))
                run = resolver.Run(slug, self.tmp)
                if action["action"] in ("run_agent", "run_lead"):
                    for rel in action.get("artifacts", []):
                        self.write_agent_artifact(rel, trace_step)
                    resolver.complete_step(
                        run, step, outputs=canned_agent_outputs(step, action),
                    )
                elif action["action"] == "ask_interview":
                    resolver.record_interview(
                        run, step, action["section"],
                        answer=None if action.get("proposal") else f"Confirmed {action['title']}",
                        accept=bool(action.get("proposal")),
                    )
                elif action["action"] == "ask_interview_batch":
                    resolver.record_interview_batch(run, step, {
                        question["section"]: (
                            {"accept": True} if question.get("proposal")
                            else {"answer": f"Confirmed {question['title']}"}
                        )
                        for question in action["questions"]
                    })
                elif action["action"] == "run_script":
                    proc = subprocess.run(
                        action["argv"], cwd=self.tmp, capture_output=True, text=True, timeout=30,
                    )
                    resolver.complete_step(
                        run, step, exit_code=proc.returncode, stdout=proc.stdout,
                    )
                elif action["action"] == "ask_gate":
                    self.assertLess(gate_index, len(decisions), f"{repo} LLD gate overscripted")
                    option, feedback = decisions[gate_index]
                    gate_index += 1
                    selected = next(o for o in action["options"] if o["id"] == option)
                    resolver.record_gate(run, step, option)
                    if selected.get("input"):
                        self.assertIsNotNone(feedback)
                        pending = resolver.next_action(run)
                        self.assertEqual(pending["action"], "ask_input")
                        trace.append(("ask_input", trace_step))
                        resolver.record_gate_input(run, step, feedback)
                else:
                    self.fail(f"unexpected child LLD action: {action}")
                statemod.save(slug, run.state, self.tmp)
            else:
                self.fail(f"LLD workstream {slug} did not finish")

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
                if act["action"] in ("run_agent", "run_lead"):
                    for rel in act.get("artifacts", []):
                        self.write_agent_artifact(rel, step)
                    node = step.rsplit("/", 1)[-1]
                    outputs = (overrides.get(node) or
                               (self.implementation_outputs(act) if node == "implement"
                                else canned_agent_outputs(step, act)))
                    resolver.complete_step(run, step, outputs=outputs)
                elif act["action"] == "run_script":
                    # actually run the real script where it's an engine helper; stub others
                    if ("oq_serve" in step or "validate_tasks" in step
                            or any(a.endswith("validate_prd.py") or a.endswith("validate_prd_questions.py")
                                   or a.endswith("validate_hld.py")
                                   for a in act.get("argv", []))
                            or any("mem_consolidate" in a or "lld_repo_pool" in a
                                   or "implementation_pool" in a or "workspace_sync" in a
                                   for a in act.get("argv", []))):
                        proc = subprocess.run(act["argv"], cwd=self.tmp, capture_output=True,
                                              text=True, timeout=30)
                        code, out = proc.returncode, proc.stdout
                    else:
                        code, out = canned_script(step)
                    resolver.complete_step(run, step, exit_code=code, stdout=out)
                elif act["action"] == "ask_gate":
                    if step == "design/lld_workstreams_wait":
                        self.drive_lld_workstreams(trace, gate_script)
                        resolver.record_gate(run, step, "refresh")
                        statemod.save("demo", run.state, self.tmp)
                        continue
                    decisions = gate_script.get(step)
                    if decisions is None and step.rsplit("/", 1)[-1] in (
                            "project_context_confirm", "feature_goal_confirm"):
                        decisions = [("confirm", None)] * 20
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
            "design/lld_scope": [("all", None)],
            "contract_approval": [("approve", None)],
            "release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        self.assertEqual(action["outputs"]["hld"], ".maestro/runs/demo/hld.md")
        self.assertEqual(action["outputs"]["implementation_manifest"],
                         ".maestro/runs/demo/implementation-manifest.json")
        steps = [s for _, s in trace]
        self.assertIn("workspace_sync_initial/plan", steps)
        self.assertIn("workspace_sync_initial/lock", steps)
        self.assertIn("workspace_sync_pre_impl/plan", steps)
        self.assertIn("workspace_sync_pre_impl/lock", steps)
        self.assertNotIn("workspace_sync_initial/refresh_knowledge", steps)
        # both selected repos implemented through runtime claims, not hard-coded stacks
        impl_steps = [s for s in steps if s.endswith("/impl/implement")]
        review_steps = [s for s in steps if s.endswith("/impl/review")]
        self.assertEqual(len(impl_steps), 2)
        self.assertEqual(len(review_steps), 2)
        # the lead confirms context, grills one material edge, and writes once before HLD
        self.assertIn("design/project_context", steps)
        self.assertIn("design/prd_interview", steps)
        self.assertIn("design/author_prd", steps)
        self.assertLess(steps.index("design/author_prd"), steps.index("design/author_hld"))
        # the LLDs are approved by a human before any implementation begins
        gate_steps = [s for a, s in trace if a == "ask_gate"]
        self.assertIn("design/lld_workstreams_wait", gate_steps)
        child_approvals = [step for step in gate_steps if step.endswith("/lld_approval")]
        self.assertEqual(len(child_approvals), 2)
        child_authors = [step for step in steps if step.endswith("/author_lld")]
        child_interviews = [step for step in steps if step.endswith("/lld_interview")]
        self.assertEqual(len(child_authors), 2)
        self.assertEqual(len(child_interviews), 2)
        self.assertTrue(all(
            steps.index(step.replace("/author_lld", "/lld_interview")) < steps.index(step)
            for step in child_authors
        ))
        self.assertFalse(any(step.endswith("/lld_post_interview") for step in steps))
        self.assertFalse(any(step.endswith("/repair_lld") for step in steps))
        self.assertLess(steps.index("design/lld_workstreams_wait"), steps.index(impl_steps[0]))
        # design ran before implementation, qa after
        self.assertLess(steps.index("design/author_hld"), steps.index("arch_review"))
        self.assertLess(steps.index("finalize_implementation"), steps.index("qa/qa_run"))

    def test_valid_existing_prd_uses_fast_path(self):
        self.prep_tasks_json()
        self.write_agent_artifact(
            ".maestro/runs/demo/requirement/prd.md", "existing-prd-fixture"
        )
        gates = {
            "design/collect_references": [("none", None)],
            "design/prd_approval": [("approve", None)],
            "design/hld_approval": [("approve", None)],
            "design/lld_scope": [("all", None)],
            "contract_approval": [("approve", None)],
            "release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        steps = [step for _, step in trace]
        self.assertIn("design/check_existing_prd", steps)
        self.assertNotIn("design/prepare_prd_questions", steps)
        self.assertNotIn("design/prd_interview", steps)
        self.assertNotIn("design/author_prd", steps)

    def test_revise_cascade_from_contract_gate(self):
        self.prep_tasks_json()
        gates = {
            "design/collect_references": [("none", None), ("none", None)],
            "design/prd_approval": [("approve", None), ("approve", None)],
            "design/hld_approval": [("approve", None), ("approve", None)],
            "design/lld_scope": [("all", None), ("all", None)],
            "contract_approval": [("revise", "tighten the API"), ("approve", None)],
            "release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        # Shared design ran twice. Repo approvals remain separate child ledgers and are reused
        # only because the deterministic fixture produced the same HLD bytes.
        self.assertEqual(steps.count("design/author_hld"), 2)
        self.assertEqual(steps.count("design/contract"), 2)
        self.assertEqual(len([s for s in steps if s.endswith("/lld_approval")]), 2)

    def test_revise_cascade_from_prd_gate(self):
        """PRD feedback re-confirms the feature, interview, and single-write stage."""
        self.prep_tasks_json()
        gates = {
            "design/collect_references": [("none", None)],
            "design/prd_approval": [("revise", "sharpen the scope"), ("approve", None)],
            "design/hld_approval": [("approve", None)],
            "design/lld_scope": [("all", None)],
            "contract_approval": [("approve", None)],
            "release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        # PRD authored twice (revision forces the interview path despite a valid old file).
        self.assertEqual(steps.count("design/author_prd"), 2)
        self.assertEqual(steps.count("design/prd_interview"), 1)
        self.assertEqual(steps.count("design/author_hld"), 1)

    def test_repo_lld_revise_is_isolated_and_requires_feedback(self):
        self.prep_tasks_json()
        gates = {
            "design/collect_references": [("none", None)],
            "design/prd_approval": [("approve", None)],
            "design/hld_approval": [("approve", None)],
            "design/lld_scope": [("all", None)],
            "lld:backend": [
                ("revise", "Rotate refresh tokens and document the failure path."),
                ("approve", None),
            ],
            "contract_approval": [("approve", None)],
            "release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        self.assertIn(("ask_input", "lld:backend/lld_approval"), trace)
        state = statemod.load("demo--lld--backend", self.tmp)
        revisions = [g for g in state["gates"]
                     if g["step"] == "lld_approval" and g["option"] == "revise"]
        self.assertEqual(len(revisions), 1)
        self.assertIn("rotate refresh tokens", revisions[0]["input"].lower())
        frontend = statemod.load("demo--lld--frontend", self.tmp)
        self.assertFalse(any(g["option"] == "revise" for g in frontend["gates"]))

    def test_blocking_arch_review_gate_waive(self):
        self.prep_tasks_json()
        gates = {
            "design/collect_references": [("none", None)],
            "design/prd_approval": [("approve", None)],
            "design/hld_approval": [("approve", None)],
            "design/lld_scope": [("all", None)],
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
                "design/lld_scope": [("all", None)],
                "contract_approval": [("approve", None)],
                "release_approval": [("approve", None)],
            }
            action, trace = self.drive(gates)
        finally:
            globals()["canned_agent_outputs"] = orig
        self.assertEqual(action["action"], "done", action)
        steps = [s for _, s in trace]
        self.assertEqual(len([s for s in steps if s.endswith("/impl/fix")]), 2)

    def test_hld_clarifies_before_single_write(self):
        """The HLD resolves one grouped architecture round before writing once."""
        self.prep_tasks_json()
        gates = {
            "design/collect_references": [("none", None)],
            "design/prd_approval": [("approve", None)],
            "design/hld_approval": [("approve", None)],
            "design/lld_scope": [("all", None)],
            "contract_approval": [("approve", None)],
            "release_approval": [("approve", None)],
        }
        action, trace = self.drive(gates)
        self.assertEqual(action["action"], "done", action)
        steps = [step for _, step in trace]
        self.assertEqual(steps.count("design/hld_interview"), 1)
        self.assertEqual(steps.count("design/author_hld"), 1)
        self.assertIn("design/validate_hld_post_questions", steps)
        self.assertIn("design/validate_hld", steps)
        self.assertNotIn("design/hld_post_interview", steps)
        self.assertNotIn("design/repair_hld", steps)

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
                if node == "author_hld":
                    reached_hld = True
                    outputs = {"hld_summary": "ok"}
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
                    resolver.record_gate(run, step, "clarify")
                elif step == "collect_references":
                    resolver.record_gate(run, step, "provide")
                    resolver.record_gate_input(run, step, "https://figma.com/file/demo")
                elif step in ("project_context_confirm", "feature_goal_confirm"):
                    resolver.record_gate(run, step, "confirm")
                elif step == "prd_approval":
                    resolver.record_gate(run, step, "approve")
                elif step == "map_stale_gate":
                    resolver.record_gate(run, step, "proceed")
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
            self.fail("PRD interview path did not reach author_hld")

        self.assertTrue(reached_hld, "never reached author_hld")
        self.assertIn("project_context", seen)
        self.assertIn("author_prd", seen)
        self.assertEqual(len(interview_sections), 1)
        context_path = os.path.join(self.tmp, ".maestro", "runs", "demo", "prd-context.json")
        with open(context_path) as fh:
            context = json.load(fh)
        self.assertEqual(len(context["decisions"]), 1)


if __name__ == "__main__":
    unittest.main()
