"""design-plan.yaml: brainstorm -> write -> commit -> approval, driven through the resolver with the
real engine scripts (greenfield check, plan status, validate, commit, approve).

A person answers the brainstorm confirmation and the plan approval in every run mode; "later"
pauses the run and a resume asks the same question; revise feedback re-enters the writer; a
release sent back with feedback starts at the writer when a plan exists."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, ".."))
import resolver  # noqa: E402
import state as statemod  # noqa: E402

SLUG = "demo"
WORKFLOW = ".maestro/workflows/design-plan.yaml"
PRD = """# Demo — PRD

**Feature slug:** `demo`
**Status:** Ready for review

## Problem

People cannot export the table.

## Acceptance criteria

- AC-01: The table page shows an Export button.
- AC-02: Export downloads the visible rows as CSV.

## Out of scope

Other formats.
"""
FULL_PRD = "# Demo — PRD\n\n**Feature slug:** `demo`\n**Status:** Ready for review\n\n" + "\n".join(
    f"## {title}\n\n{body}\n" for title, body in (
        ("Summary", "Export the table."), ("Problem and context", "People copy rows by hand."),
        ("Users and jobs", "Analysts share tables."), ("Goals and success signals", "Fewer copies."),
        ("Non-goals", "Other formats."), ("Functional scope", "A CSV download."),
        ("Non-functional requirements", "- None beyond the existing service standards."),
        ("Constraints and assumptions", "None."),
        ("Acceptance criteria", "- AC-01: The table page shows an Export button.\n"
                                "- AC-02: Export downloads the visible rows as CSV."),
        ("Dependencies and risks", "None."), ("Priorities and phasing", "One release."),
        ("References", "The request.")))
MAJOR = """# Demo — plan
Type: major · Run: demo · PRD: .maestro/runs/demo/requirement/prd.md · Status: active

## Summary
Add a CSV export to the table page.

## Decisions
- Stream rows from the API — keeps memory flat — rejected: build the file in the browser.

## Repositories
| repo | role in this change | new? |
|---|---|---|
| api | serves the CSV | no |

## Design
api: a new export handler beside the table handler.

## Interfaces
GET /tables/{id}/export.csv -> 200 text/csv; 404 when the table is missing.

## Infrastructure
None

## Risks and open points
Large tables may be slow.

## Acceptance coverage
- AC-01 -> api / export handler
- AC-02 -> api / export handler

## Out of scope
Other formats.
"""
MINOR = """# Demo — plan
Type: minor · Run: demo · Repositories: api
- Change: add a CSV export endpoint.
- Where: api/handlers/export.go
- Interface: GET /tables/{id}/export.csv
- Data: None
- Tests: handler test for AC-01 and AC-02
- Risk: large tables
"""


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def init_repo(path):
    os.makedirs(path, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "T")
    git(path, "config", "commit.gpgsign", "false")
    with open(os.path.join(path, "README.md"), "w") as fh:
        fh.write("x\n")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "init")


class Workspace(unittest.TestCase):
    """A workspace root (a git repository) with one configured repository and an approved PRD."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-plan-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        shutil.copytree(os.path.join(REPO, "workflows"),
                        os.path.join(self.tmp, ".maestro", "workflows"))
        shutil.copytree(os.path.join(REPO, "engine"), os.path.join(self.tmp, ".maestro", "engine"),
                        ignore=shutil.ignore_patterns("tests", "__pycache__"))
        init_repo(self.tmp)
        init_repo(os.path.join(self.tmp, "codebase", "api"))
        with open(os.path.join(self.tmp, "maestro.config.yaml"), "w") as fh:
            fh.write("version: 1\nrepos:\n  api: {}\n")
        self.write(f".maestro/runs/{SLUG}/requirement/prd.md", PRD)
        self.plan_text = MAJOR
        self.writes = []

    def write(self, rel, text):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def run_obj(self):
        return resolver.Run(SLUG, self.tmp)


class DesignPlanTest(Workspace):
    def start(self, path="major", mode=None, feedback=""):
        with statemod.locked(SLUG, self.tmp):
            data, _ = resolver.init_run(SLUG, WORKFLOW, {"path": path, "feedback": feedback},
                                        self.tmp, force=True, mode=mode)
            statemod.save(SLUG, data, self.tmp)

    def advance(self):
        """Do every engine and agent step until a person is asked (or the run ends/pauses).
        Returns the action that waits on the person."""
        for _ in range(60):
            run = self.run_obj()
            self.autopilot = resolver.apply_autopilot(run)
            statemod.save(SLUG, run.state, self.tmp)
            action = resolver.next_action(run)
            kind = action["action"]
            if kind in ("ask_gate", "ask_input", "paused", "done", "failed"):
                return action
            step = action["step"]
            if kind == "run_script":
                proc = subprocess.run(action["argv"], cwd=self.tmp, capture_output=True,
                                      text=True, timeout=60)
                resolver.complete_step(run, step, exit_code=proc.returncode, stdout=proc.stdout)
            elif kind in ("run_agent", "run_lead"):
                node = step.rsplit("/", 1)[-1]
                if node == "brainstorm":
                    self.write(f".maestro/runs/{SLUG}/decisions/brainstorm.md",
                               "## Direction\nStream it.\n## Decisions\n- stream\n## Open points\nNone\n")
                elif node == "write_plan":
                    self.writes.append(action.get("prompt", ""))
                    self.write(f"docs/plans/active/{SLUG}.md", self.plan_text)
                resolver.complete_step(run, step, outputs={"summary": f"{node} done"})
            else:
                self.fail(f"unexpected action {action}")
            statemod.save(SLUG, run.state, self.tmp)
        self.fail("design-plan did not settle")

    def answer(self, step, option, text=None):
        run = self.run_obj()
        resolver.record_gate(run, step, option)
        statemod.save(SLUG, run.state, self.tmp)
        if text is not None:
            run = self.run_obj()
            self.assertEqual(resolver.next_action(run)["action"], "ask_input")
            resolver.record_gate_input(run, step, text)
            statemod.save(SLUG, run.state, self.tmp)
        return self.advance()

    def steps(self):
        return statemod.load(SLUG, self.tmp)["steps"]

    def test_brainstorm_write_commit_and_approve(self):
        self.start()
        action = self.advance()
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "brainstorm_confirm"))
        self.assertEqual([o["id"] for o in action["options"]], ["write", "more"])
        action = self.answer("brainstorm_confirm", "write")
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "plan_approval"))
        self.assertEqual([o["id"] for o in action["options"]],
                         ["approve", "revise", "rethink", "later", "reject"])
        self.assertIn("docs/plans/active/demo.md", action["prompt"])
        self.assertIn("Saved the plan to main.", action["prompt"])
        self.assertEqual(git(self.tmp, "log", "-1", "--format=%s"), "plan(demo): created")
        action = self.answer("plan_approval", "approve")
        self.assertEqual(action["action"], "done")
        outputs = self.steps()["record_approval"]["outputs"]
        self.assertEqual(outputs["repos_csv"], "api")
        with open(os.path.join(self.tmp, ".maestro/runs/demo/.engine/plan-approval.json")) as fh:
            approval = json.load(fh)
        self.assertEqual(approval["plan_path"], "docs/plans/active/demo.md")
        self.assertEqual(approval["repos"], ["api"])

    def test_an_invalid_plan_goes_back_to_the_writer(self):
        self.start()
        self.advance()
        self.plan_text = MAJOR.replace("- AC-02 -> api / export handler\n", "")
        run = self.run_obj()
        resolver.record_gate(run, "brainstorm_confirm", "write")
        statemod.save(SLUG, run.state, self.tmp)
        action = None
        for _ in range(3):  # the writer is re-served with the engine's report
            run = self.run_obj()
            action = resolver.next_action(run)
            if action["action"] in ("run_agent", "run_lead") and action["step"] == "write_plan" \
                    and len(self.writes) >= 1 and "AC-02" in action.get("prompt", ""):
                break
            if action["action"] == "run_script":
                proc = subprocess.run(action["argv"], cwd=self.tmp, capture_output=True, text=True)
                resolver.complete_step(run, action["step"], exit_code=proc.returncode,
                                       stdout=proc.stdout)
            else:
                self.writes.append(action.get("prompt", ""))
                self.write(f"docs/plans/active/{SLUG}.md", self.plan_text)
                resolver.complete_step(run, action["step"], outputs={"summary": "written"})
            statemod.save(SLUG, run.state, self.tmp)
        self.assertEqual(action["step"], "write_plan")
        self.assertIn("AC-02", action["prompt"])

    def test_later_pauses_and_a_resume_asks_the_same_question(self):
        self.start()
        self.advance()
        self.answer("brainstorm_confirm", "write")
        action = self.answer("plan_approval", "later")
        self.assertEqual(action["action"], "paused")
        self.assertEqual(action["resume"], "/maestro demo")
        with statemod.locked(SLUG, self.tmp):
            data, created = resolver.init_run(SLUG, WORKFLOW, {}, self.tmp)
            statemod.save(SLUG, data, self.tmp)
        self.assertFalse(created)
        action = self.advance()
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "plan_approval"))
        self.assertEqual(self.answer("plan_approval", "approve")["action"], "done")

    def test_revise_feedback_reenters_the_writer_and_commits_an_update(self):
        self.start()
        self.advance()
        self.answer("brainstorm_confirm", "write")
        self.plan_text = MAJOR.replace("Large tables may be slow.", "Large tables are paged.")
        action = self.answer("plan_approval", "revise", "page large tables")
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "plan_approval"))
        self.assertEqual(len(self.writes), 2)
        self.assertIn("page large tables", self.writes[-1])
        self.assertEqual(git(self.tmp, "log", "-1", "--format=%s"), "plan(demo): updated")
        # no second brainstorm
        self.assertEqual(self.steps()["brainstorm"]["visits"], 1)

    def test_rethink_goes_back_to_the_brainstorm(self):
        self.start()
        self.advance()
        self.answer("brainstorm_confirm", "write")
        action = self.answer("plan_approval", "rethink", "use a queue instead")
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "brainstorm_confirm"))
        self.assertEqual(self.steps()["brainstorm"]["visits"], 2)

    def test_release_feedback_starts_at_the_writer_when_a_plan_exists(self):
        self.write(f"docs/plans/active/{SLUG}.md", MAJOR)
        self.start(feedback="the export must include hidden columns")
        action = self.advance()
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "plan_approval"))
        self.assertNotIn("brainstorm", self.steps())
        self.assertIn("the export must include hidden columns", self.writes[0])

    def test_minor_plan(self):
        self.plan_text = MINOR
        self.start(path="minor")
        self.advance()
        action = self.answer("brainstorm_confirm", "write")
        self.assertEqual(action["step"], "plan_approval")
        self.assertIn("Plan type: minor", self.writes[0])

    def test_a_person_approves_the_plan_in_design_and_auto_mode(self):
        for mode in ("design", "auto"):
            with self.subTest(mode=mode):
                self.start(mode=mode)
                action = self.advance()
                self.assertEqual((action["action"], action["step"]), ("ask_gate", "brainstorm_confirm"))
                action = self.answer("brainstorm_confirm", "write")
                self.assertEqual((action["action"], action["step"]), ("ask_gate", "plan_approval"))
                self.assertEqual(self.autopilot, [])
                os.remove(os.path.join(self.tmp, "docs/plans/active/demo.md"))

    def test_greenfield_scaffolds_before_the_approval(self):
        shutil.rmtree(os.path.join(self.tmp, "codebase"))
        shutil.rmtree(os.path.join(self.tmp, ".git"))
        os.remove(os.path.join(self.tmp, "maestro.config.yaml"))
        self.plan_text = MAJOR.replace("| api | serves the CSV | no |", "| api | serves the CSV | yes |")
        self.start()
        self.advance()
        run = self.run_obj()
        resolver.record_gate(run, "brainstorm_confirm", "write")
        statemod.save(SLUG, run.state, self.tmp)
        for _ in range(10):
            run = self.run_obj()
            action = resolver.next_action(run)
            if action["step"].startswith("scaffold/"):
                break
            if action["action"] == "run_script":
                proc = subprocess.run(action["argv"], cwd=self.tmp, capture_output=True, text=True)
                resolver.complete_step(run, action["step"], exit_code=proc.returncode,
                                       stdout=proc.stdout)
            else:
                self.write(f"docs/plans/active/{SLUG}.md", self.plan_text)
                resolver.complete_step(run, action["step"], outputs={"summary": "written"})
            statemod.save(SLUG, run.state, self.tmp)
        self.assertEqual(action["step"], "scaffold/create")
        self.assertIn("--slug", action["argv"])


class MinorPrdRoutingTest(Workspace):
    """design-prd.yaml with path=minor: a first preparation that asks nothing writes the mini PRD
    and ends without the approval gate; anything else keeps the gate."""
    WORKFLOW = ".maestro/workflows/design-prd.yaml"

    def setUp(self):
        super().setUp()
        os.remove(os.path.join(self.tmp, f".maestro/runs/{SLUG}/requirement/prd.md"))
        self.write(f".maestro/runs/{SLUG}/requirement/requirement.md",
                   "Add an Export button that downloads the table as CSV.\n")
        self.clarify_once = False

    def drive(self, path):
        with statemod.locked(SLUG, self.tmp):
            data, _ = resolver.init_run(SLUG, self.WORKFLOW, {"path": path}, self.tmp, force=True)
            statemod.save(SLUG, data, self.tmp)
        served = []
        for _ in range(40):
            run = self.run_obj()
            resolver.apply_autopilot(run)
            action = resolver.next_action(run)
            if action["action"] != "run_script" or not action.get("check"):
                served.append(action.get("step"))
            if action["action"] in ("ask_gate", "done", "failed"):
                return action, served
            step = action["step"]
            if action["action"] == "run_script":
                proc = subprocess.run(action["argv"], cwd=self.tmp, capture_output=True,
                                      text=True, timeout=60)
                resolver.complete_step(run, step, exit_code=proc.returncode, stdout=proc.stdout)
            else:
                outputs = {"summary": "ok"}
                if step == "prepare_prd":
                    self.write(f".maestro/runs/{SLUG}/.engine/queues/prd.json", json.dumps({
                        "schema_version": 2, "questions": [],
                        "audit": {"unresolved": [], "contradictions": []}}))
                    outputs["feature_goal"] = "Export the table as CSV."
                elif step == "write_prd":
                    self.write(f".maestro/runs/{SLUG}/requirement/prd.md",
                               PRD if path == "minor" else FULL_PRD)
                    outputs["needs_clarification"] = self.clarify_once
                    self.clarify_once = False
                resolver.complete_step(run, step, outputs=outputs)
            statemod.save(SLUG, run.state, self.tmp)
        self.fail("design-prd did not settle")

    def test_clear_minor_writes_the_mini_prd_without_approval(self):
        action, served = self.drive("minor")
        self.assertEqual(action["action"], "done")
        self.assertIn("write_prd", served)
        self.assertNotIn("prd_approval", served)

    def test_major_still_asks_for_approval(self):
        action, served = self.drive("major")
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "prd_approval"))
        self.assertEqual(served.count("write_prd"), 1)

    def test_minor_that_needed_another_round_keeps_the_approval(self):
        self.clarify_once = True
        action, served = self.drive("minor")
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "prd_approval"))
        self.assertEqual(served.count("prepare_prd"), 2)


if __name__ == "__main__":
    unittest.main()
