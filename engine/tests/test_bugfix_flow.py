"""bugfix-triage.yaml and delivery.yaml (entry: bugfix), driven through the resolver with the real
engine scripts (requirement check, PRD check, branch check, base map, sandbox, registration, QA
environment, approval) against temporary git repositories; agent steps write canned files.

The person decides whether to reproduce, what to do about a repository without the branch, and
approves the fix in every run mode; "later" pauses and a resume asks the same question. Once
approved, delivery fixes each repository in its sandbox worktree and records the commit."""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import resolver  # noqa: E402
import state as statemod  # noqa: E402
from test_design_plan import PRD, SLUG, Workspace, git, init_repo  # noqa: E402

TRIAGE = ".maestro/workflows/bugfix-triage.yaml"
DELIVERY = ".maestro/workflows/delivery.yaml"
RUN = f".maestro/runs/{SLUG}"
BUG = "# Export button missing — bug report\n\nBranch: release-1 · Repositories: api, web\n"
CASES = ("# Test cases\n\n### TC-demo-001 — export button\n\n- **Traces:** AC-01\n\n"
         "### TC-demo-002 — csv download\n\n- **Traces:** AC-02\n")
# engine steps whose real scripts need configured commands: canned here
CANNED = {
    "bugfix/verify": {"passed": True, "unchanged": False, "summary": "all checks passed",
                      "failed_checks": "", "tests_changed": "",
                      "receipt_path": f"{RUN}/build/api/verify.json"},
}


class BugfixFlowTest(Workspace):
    def setUp(self):
        super().setUp()
        os.remove(os.path.join(self.tmp, RUN, "requirement", "prd.md"))
        self.write(f"{RUN}/requirement/ticket.md", "The export button is gone on release-1.\n")
        init_repo(os.path.join(self.tmp, "codebase", "web"))
        with open(os.path.join(self.tmp, "maestro.config.yaml"), "w") as fh:
            fh.write("version: 1\nrepos:\n  api: {}\n  web: {}\n")
        self.repos = {name: os.path.join(self.tmp, "codebase", name) for name in ("api", "web")}
        for name, repo in self.repos.items():
            git(repo, "checkout", "-q", "-b", "release-1")
            with open(os.path.join(repo, "app.txt"), "w") as fh:
                fh.write(f"{name} on release-1\n")
            git(repo, "add", "app.txt")
            git(repo, "commit", "-q", "-m", "release")
            git(repo, "checkout", "-q", "main")
        self.affected = "api,web"
        self.reproduced = True
        self.prompts = {}

    # -- driving ---------------------------------------------------------------------------
    def start(self, workflow=TRIAGE, inputs=None, mode=None):
        with statemod.locked(SLUG, self.tmp):
            data, _ = resolver.init_run(SLUG, workflow, inputs or {"branch": "release-1"},
                                        self.tmp, force=True, mode=mode)
            statemod.save(SLUG, data, self.tmp)

    def agent(self, step):
        node = step.rsplit("/", 1)[-1]
        outputs = {"summary": f"{node} done"}
        if node == "triage":
            self.write(f"{RUN}/requirement/bug.md", BUG)
            self.write(f"{RUN}/requirement/prd.md", PRD)
            outputs["repos_csv"] = self.affected
        elif node == "test_cases":
            self.write(f"{RUN}/design/test-cases.md", CASES)
            outputs = {"test_cases_path": f"{RUN}/design/test-cases.md", "case_count": 2}
        elif node == "reproduce":
            self.write(f"{RUN}/qa/reproduction.md",
                       f"# Reproduction\n\nreproduced: {self.reproduced}\n"
                       f"<!-- {len(self.prompts.get(node, []))} -->\n")
            outputs["reproduced"] = self.reproduced
        elif node == "propose_fix":
            self.write(f"{RUN}/design/fix-proposal.md",
                       "# Fix proposal\n\n## Cause\nThe button is hidden.\n"
                       f"<!-- {len(self.prompts.get(node, []))} -->\n")
            outputs.update({"cause": "A feature flag hides the button.",
                            "change": "api: default the flag on.",
                            "impact": "Every user sees the button again.",
                            "risks": "None"})
        elif node == "fix":  # commit the fix in the sandbox worktree it was given
            self.claimed = dict(self.claim())
            worktree = self.claimed["worktree"]
            with open(os.path.join(worktree, "fix.txt"), "w") as fh:
                fh.write("fixed\n")
            git(worktree, "add", "fix.txt")
            git(worktree, "commit", "-q", "-m", "fix: show the export button")
            outputs = {"fix_summary": "flag defaulted on", "checks_passed": True,
                       "escalate": False}
        elif node == "review":
            self.write(f"{RUN}/reviews/code-api.md", "# Review\n\nFine.\n")
            self.write(f"{RUN}/reviews/code-api.findings.json",
                       json.dumps({"schema_version": 1, "findings": []}))
            outputs = {"review_path": f"{RUN}/reviews/code-api.md", "blocking": False,
                       "summary": "no findings"}
        return outputs

    def claim(self):
        return self.steps()["bugfix_claim"]["outputs"]

    def advance(self, stop=()):
        """Run engine and agent steps until a person is asked, the run ends or pauses, or a step
        whose id starts with one of `stop` is served (returned unexecuted)."""
        for _ in range(80):
            run = self.run_obj()
            self.autopilot = resolver.apply_autopilot(run)
            statemod.save(SLUG, run.state, self.tmp)
            action = resolver.next_action(run)
            kind = action["action"]
            if kind in ("ask_gate", "ask_input", "paused", "done", "failed"):
                return action
            step = action["step"]
            if any(step.startswith(prefix) for prefix in stop):
                return action
            if kind in ("run_agent", "run_lead"):
                self.prompts.setdefault(step.rsplit("/", 1)[-1], []).append(action["prompt"])
            if kind == "run_script":
                if step in CANNED:
                    resolver.complete_step(run, step, exit_code=0,
                                           stdout=json.dumps(CANNED[step]))
                else:
                    proc = subprocess.run(action["argv"], cwd=self.tmp, capture_output=True,
                                          text=True, timeout=120)
                    resolver.complete_step(run, step, exit_code=proc.returncode,
                                           stdout=proc.stdout)
            elif kind in ("run_agent", "run_lead"):
                resolver.complete_step(run, step, outputs=self.agent(step))
            else:
                self.fail(f"unexpected action {action}")
            statemod.save(SLUG, run.state, self.tmp)
        self.fail("the bug fix did not settle")

    def answer(self, step, option, text=None, stop=()):
        run = self.run_obj()
        resolver.record_gate(run, step, option)
        statemod.save(SLUG, run.state, self.tmp)
        if text is not None:
            run = self.run_obj()
            self.assertEqual(resolver.next_action(run)["action"], "ask_input")
            resolver.record_gate_input(run, step, text)
            statemod.save(SLUG, run.state, self.tmp)
        return self.advance(stop)

    def steps(self):
        return statemod.load(SLUG, self.tmp)["steps"]

    def read_json(self, rel):
        with open(os.path.join(self.tmp, rel)) as fh:
            return json.load(fh)

    def sandbox(self):
        return {row["repo"]: row for row in self.read_json(f"{RUN}/.engine/sandbox.json")
                ["repositories"]}

    def to_choice(self, mode=None):
        self.start(mode=mode)
        action = self.advance()
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "reproduce_choice"))
        self.assertEqual([o["id"] for o in action["options"]], ["reproduce", "skip"])
        self.assertTrue(action.get("say"))
        return action

    def assert_gate(self, action, step):
        self.assertEqual((action["action"], action.get("step")), ("ask_gate", step), action)

    # -- triage --------------------------------------------------------------------------------
    def test_branch_everywhere_builds_the_sandbox_on_it(self):
        self.to_choice()
        action = self.answer("reproduce_choice", "reproduce")
        self.assert_gate(action, "fix_approval")
        self.assertNotIn("missing_branch", self.steps())
        self.assertEqual(self.read_json(f"{RUN}/.engine/bug-bases.json"),
                         {"api": "release-1", "web": "release-1"})
        rows = self.sandbox()
        for name, repo in self.repos.items():
            self.assertEqual(rows[name]["branch"], f"fix/{SLUG}-{name}")
            self.assertEqual(rows[name]["base_commit"], git(repo, "rev-parse", "release-1"))
            self.assertEqual(git(rows[name]["worktree"], "branch", "--show-current"),
                             f"fix/{SLUG}-{name}")
        pool = self.read_json(f"{RUN}/.engine/implementation-pool.json")
        self.assertEqual(sorted(pool["implementations"]), ["api", "web"])
        # no environment configured: the reproduction is a failing test only
        self.assertFalse(self.steps()["env_up"]["outputs"]["configured"])
        self.assertIn("App running: false", self.prompts["reproduce"][0])
        for word in ("A feature flag hides the button.", "api: default the flag on.",
                     "Every user sees the button again.", "reproduce done"):
            self.assertIn(word, action["prompt"])
        self.assertEqual([o["id"] for o in action["options"]],
                         ["approve", "revise", "re-triage", "later", "reject"])

    def test_missing_branch_asks_the_person(self):
        git(self.repos["web"], "branch", "-q", "-D", "release-1")
        self.to_choice()
        action = self.answer("reproduce_choice", "skip")
        self.assert_gate(action, "missing_branch")
        self.assertIn("web", action["prompt"])
        self.assertEqual([o["id"] for o in action["options"]], ["default", "named", "drop"])
        self.assertNotIn("sandbox", self.steps())
        self.assertEqual(self.autopilot, [])

    def test_default_choice_bases_that_repository_on_its_default_branch(self):
        git(self.repos["web"], "branch", "-q", "-D", "release-1")
        self.to_choice()
        self.answer("reproduce_choice", "skip")
        action = self.answer("missing_branch", "default")
        self.assert_gate(action, "fix_approval")
        self.assertEqual(self.read_json(f"{RUN}/.engine/bug-bases.json"),
                         {"api": "release-1", "web": "main"})
        rows = self.sandbox()
        self.assertEqual(rows["web"]["base_commit"], git(self.repos["web"], "rev-parse", "main"))
        self.assertEqual(rows["api"]["base_commit"],
                         git(self.repos["api"], "rev-parse", "release-1"))

    def test_named_branch_and_a_wrong_name_asks_again(self):
        git(self.repos["web"], "branch", "-q", "-m", "release-1", "release-2")
        self.to_choice()
        self.answer("reproduce_choice", "skip")
        action = self.answer("missing_branch", "named", "web=nope")
        self.assert_gate(action, "missing_branch")
        self.assertIn("web has no branch nope", action["prompt"])
        action = self.answer("missing_branch", "named", "web=release-2")
        self.assert_gate(action, "fix_approval")
        self.assertEqual(self.read_json(f"{RUN}/.engine/bug-bases.json"),
                         {"api": "release-1", "web": "release-2"})

    def test_drop_goes_back_to_triage(self):
        git(self.repos["web"], "branch", "-q", "-D", "release-1")
        self.to_choice()
        self.answer("reproduce_choice", "skip")
        self.affected = "api"  # the person leaves web out
        action = self.answer("missing_branch", "drop")
        self.assertEqual(len(self.prompts["triage"]), 2)
        self.assertIn("drop = remove web", self.prompts["triage"][1])
        self.assert_gate(action, "reproduce_choice")
        action = self.answer("reproduce_choice", "skip")
        self.assert_gate(action, "fix_approval")
        self.assertEqual(self.read_json(f"{RUN}/.engine/bug-bases.json"), {"api": "release-1"})

    def test_skip_goes_straight_to_the_proposal(self):
        self.to_choice()
        action = self.answer("reproduce_choice", "skip")
        self.assert_gate(action, "fix_approval")
        for step in ("env_up", "reproduce", "env_down", "not_reproduced"):
            self.assertNotIn(step, self.steps())
        self.assertIn("sandbox", self.steps())

    def test_not_reproduced_asks_and_more_info_goes_back_to_triage(self):
        self.reproduced = False
        self.to_choice()
        action = self.answer("reproduce_choice", "reproduce")
        self.assert_gate(action, "not_reproduced")
        self.assertEqual([o["id"] for o in action["options"]], ["proceed", "more-info", "reject"])
        self.assertNotIn("propose_fix", self.steps())
        action = self.answer("not_reproduced", "more-info", "it only happens for admins")
        self.assert_gate(action, "reproduce_choice")
        self.assertIn("it only happens for admins", self.prompts["triage"][-1])
        self.reproduced = True
        action = self.answer("reproduce_choice", "reproduce")
        self.assert_gate(action, "fix_approval")

    def test_proceed_after_not_reproduced_proposes_a_fix(self):
        self.reproduced = False
        self.to_choice()
        self.answer("reproduce_choice", "reproduce")
        self.assert_gate(self.answer("not_reproduced", "proceed"), "fix_approval")

    def test_a_person_approves_the_fix_in_auto_mode(self):
        self.to_choice(mode="auto")  # reproduce_choice has no policy either
        action = self.answer("reproduce_choice", "skip")
        self.assert_gate(action, "fix_approval")
        self.assertEqual(self.autopilot, [])

    def test_revise_reworks_the_proposal(self):
        self.to_choice()
        self.answer("reproduce_choice", "skip")
        action = self.answer("fix_approval", "revise", "keep the flag, fix the template")
        self.assert_gate(action, "fix_approval")
        self.assertEqual(len(self.prompts["propose_fix"]), 2)
        self.assertIn("keep the flag, fix the template", self.prompts["propose_fix"][-1])

    def test_later_pauses_and_a_resume_asks_the_same_question(self):
        self.to_choice()
        self.answer("reproduce_choice", "skip")
        action = self.answer("fix_approval", "later")
        self.assertEqual(action["action"], "paused")
        self.assertEqual(action["resume"], f"/maestro {SLUG}")
        with statemod.locked(SLUG, self.tmp):
            data, created = resolver.init_run(SLUG, TRIAGE, {}, self.tmp)
            statemod.save(SLUG, data, self.tmp)
        self.assertFalse(created)
        self.assert_gate(self.advance(), "fix_approval")
        self.assertEqual(self.answer("fix_approval", "approve")["action"], "done")

    # -- approve -> delivery -------------------------------------------------------------------
    def test_approve_then_delivery_fixes_the_sandbox_worktree(self):
        self.affected = "api"
        self.to_choice()
        self.answer("reproduce_choice", "skip")
        action = self.answer("fix_approval", "approve")
        self.assertEqual(action["action"], "done")
        approval = self.read_json(f"{RUN}/.engine/plan-approval.json")
        self.assertEqual((approval["plan"], approval["plan_path"]), (False, None))
        self.assertEqual(approval["repos"], ["api"])
        sandbox = self.sandbox()["api"]

        self.start(DELIVERY, {"entry": "bugfix", "bug_repos": "api"})
        action = self.advance(stop=("qa/",))
        self.assertEqual(action["step"].split("/")[0], "qa", action)
        steps = self.steps()
        self.assertFalse(steps["design_check"]["outputs"]["stale"])
        for skipped in ("workspace_sync_pre_impl", "impl_scope_init", "worktrees", "implement"):
            self.assertNotIn(skipped, steps)
        self.assertEqual((self.claimed["repo"], self.claimed["worktree"], self.claimed["commit"]),
                         ("api", sandbox["worktree"], sandbox["commit"]))
        # the fixer was handed the bug report, the reproduction and the approved proposal
        fix_prompt = self.prompts["fix"][0]
        for rel in ("requirement/bug.md", "qa/reproduction.md", "design/fix-proposal.md"):
            self.assertIn(f"{RUN}/{rel}", fix_prompt)
        self.assertIn("stays inside it", fix_prompt)
        manifest = self.read_json(f"{RUN}/build/manifest.json")
        entry = manifest["repositories"][0]
        head = git(sandbox["worktree"], "rev-parse", "HEAD")
        self.assertEqual((entry["repo"], entry["branch"], entry["commit"], entry["base"]),
                         ("api", f"fix/{SLUG}-api", head, "release-1"))
        self.assertNotEqual(head, sandbox["base_commit"])

    def test_release_autopilot_needs_no_drift_check_without_a_plan(self):
        """No plan (a bug fix): the drift check is skipped and does not block the release
        autopilot; with a plan, the drift verdict must have run and be clean."""
        sys.path.insert(0, os.path.join(HERE, ".."))
        import condctl
        import wf
        delivery = wf.load_file(os.path.join(HERE, "..", "..", "workflows", "delivery.yaml"))
        nodes = {node["id"]: node for node in delivery["nodes"]}
        self.assertEqual(nodes["ac_trace"]["next"], "plan_check")
        self.assertEqual([r["to"] for r in nodes["plan_check"]["routes"]],
                         ["drift_check", "assumptions"])
        cond = next(c for c in nodes["release_approval"]["auto"]["when"]
                    if "drift_verdict" in c)

        def holds(blocking, active):
            values = {"steps.drift_verdict.outputs.blocking": blocking,
                      "steps.plan_check.outputs.active": active}
            return condctl.evaluate(cond, lambda text: text.replace(
                "${steps.drift_verdict.outputs.blocking}", values[
                    "steps.drift_verdict.outputs.blocking"]).replace(
                "${steps.plan_check.outputs.active}", values["steps.plan_check.outputs.active"]))

        self.assertTrue(holds("", "false"))        # bug fix: no plan, no drift check
        self.assertTrue(holds("false", "true"))    # feature: clean drift check
        self.assertFalse(holds("true", "true"))    # feature: blocking drift
        self.assertFalse(holds("", "true"))        # feature: drift check never ran

    def test_a_changed_test_case_after_approval_is_stale(self):
        self.affected = "api"
        self.to_choice()
        self.answer("reproduce_choice", "skip")
        self.answer("fix_approval", "approve")
        self.write(f"{RUN}/design/test-cases.md", CASES + "\n### TC-demo-003 — more\n\n- **Traces:** AC-01\n")
        self.start(DELIVERY, {"entry": "bugfix", "bug_repos": "api"})
        action = self.advance()
        self.assertEqual(action["action"], "done")
        self.assertTrue(self.steps()["design_check"]["outputs"]["stale"])
        self.assertNotIn("bugfix_entry", self.steps())


if __name__ == "__main__":
    unittest.main()
