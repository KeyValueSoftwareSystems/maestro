"""archive.yaml: the feature's plan is reconciled with what was delivered, a person confirms any
difference, and the plan is filed under docs/plans/completed/ in one commit before the harvest.

Driven through the resolver with the real plan_doc.py scripts; the release check, delivery and
cleanup are answered with canned results, the reconcile agent writes canned files, and the walk
stops when the harvest stage starts."""
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
from test_design_plan import MAJOR, SLUG, Workspace, git  # noqa: E402

WORKFLOW = ".maestro/workflows/archive.yaml"
ACTIVE = f"docs/plans/active/{SLUG}.md"
COMPLETED = f"docs/plans/completed/{SLUG}.md"
FINAL = f".maestro/runs/{SLUG}/.engine/plan-final.md"
CHANGES = f".maestro/runs/{SLUG}/release/plan-changes.md"
RECONCILED = MAJOR.replace("404 when the table is missing.",
                           "404 when the table is missing; 413 above 100k rows.")
# engine steps whose real scripts need a released, delivered feature: canned here
CANNED = {
    "check_release": {"delivery_action": "Pull requests will be opened.", "release_by": "person"},
    "deliver": {"summary": "Opened 1 pull request.", "pr_urls_csv": ""},
    "cleanup": {"summary": "removed 1 worktree"},
}


class ArchivePlanTest(Workspace):
    def setUp(self):
        super().setUp()
        self.write(ACTIVE, MAJOR)
        git(self.tmp, "add", ACTIVE)
        git(self.tmp, "commit", "-q", "-m", "plan(demo): created")
        self.changed = False
        self.reconcile_prompts = []

    def start(self, mode=None):
        with statemod.locked(SLUG, self.tmp):
            data, _ = resolver.init_run(SLUG, WORKFLOW, {}, self.tmp, force=True, mode=mode)
            statemod.save(SLUG, data, self.tmp)

    def advance(self):
        """Run engine and agent steps until a person is asked, the run ends, or the harvest
        starts (returned as its first served action)."""
        for _ in range(40):
            run = self.run_obj()
            self.autopilot = resolver.apply_autopilot(run)
            statemod.save(SLUG, run.state, self.tmp)
            action = resolver.next_action(run)
            kind = action["action"]
            if kind in ("ask_gate", "ask_input", "paused", "done", "failed"):
                return action
            step = action["step"]
            if step.startswith("harvest/"):
                return action
            if kind == "run_script":
                if step in CANNED:
                    resolver.complete_step(run, step, exit_code=0,
                                           stdout=json.dumps(CANNED[step]))
                else:
                    proc = subprocess.run(action["argv"], cwd=self.tmp, capture_output=True,
                                          text=True, timeout=60)
                    resolver.complete_step(run, step, exit_code=proc.returncode,
                                           stdout=proc.stdout)
            elif kind in ("run_agent", "run_lead"):
                self.assertEqual(step, "plan_reconcile")
                self.reconcile_prompts.append(action.get("prompt", ""))
                visit = len(self.reconcile_prompts)
                self.write(FINAL, (RECONCILED if self.changed else MAJOR).replace(
                    "Status: active", "Status: completed") + f"<!-- pass {visit} -->\n")
                self.write(CHANGES, "# Plan changes\n\n"
                           + ("- Export refuses tables above 100k rows (api, abc123).\n"
                              if self.changed else "The delivered code matches the plan.\n"))
                summary = ("Export now refuses tables above 100k rows." if self.changed
                           else "The delivered code matches the plan.")
                resolver.complete_step(run, step, outputs={"changed": self.changed,
                                                           "summary": summary})
            else:
                self.fail(f"unexpected action {action}")
            statemod.save(SLUG, run.state, self.tmp)
        self.fail("archive did not settle")

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

    def to_plan(self, mode=None):
        """Start the stage and confirm the archive."""
        self.start(mode=mode)
        action = self.advance()
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "confirm_archive"))
        self.assertIn("docs/plans/active/", " ".join(o.get("description", "") for o in action["options"]))
        return self.answer("confirm_archive", "archive")

    def read(self, rel):
        with open(os.path.join(self.tmp, rel), encoding="utf-8") as fh:
            return fh.read()

    def assert_filed(self, text_marker):
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ACTIVE)))
        text = self.read(COMPLETED)
        self.assertIn("Status: completed", text)
        self.assertIn(text_marker, text)
        self.assertEqual(git(self.tmp, "log", "-1", "--format=%s"), "plan(demo): completed")
        self.assertEqual(git(self.tmp, "status", "--porcelain", "--", "docs"), "")
        with open(os.path.join(self.tmp, f".maestro/runs/{SLUG}/.engine/plan-commits.json")) as fh:
            self.assertEqual(json.load(fh)[-1]["event"], "completed")
        self.assertTrue(self.steps()["plan_commit"]["outputs"]["committed"])
        return text

    def test_no_active_plan_goes_straight_to_the_harvest(self):
        git(self.tmp, "rm", "-q", ACTIVE)
        git(self.tmp, "commit", "-q", "-m", "drop")
        action = self.to_plan()
        self.assertEqual(action["step"], "harvest/plan_maps")
        self.assertEqual(self.reconcile_prompts, [])
        self.assertNotIn("plan_archive", self.steps())

    def test_an_archived_plan_is_not_filed_again(self):
        """Running archive on its own after the plan was filed: nothing to reconcile."""
        os.makedirs(os.path.join(self.tmp, "docs/plans/completed"))
        git(self.tmp, "mv", ACTIVE, COMPLETED)
        git(self.tmp, "commit", "-q", "-m", "filed")
        action = self.to_plan()
        self.assertEqual(action["step"], "harvest/plan_maps")
        self.assertEqual(self.reconcile_prompts, [])

    def test_unchanged_plan_is_filed_without_asking(self):
        action = self.to_plan()
        self.assertEqual(action["step"], "harvest/plan_maps")
        self.assertEqual(len(self.reconcile_prompts), 1)
        self.assertIn("reviews/drift.md", self.reconcile_prompts[0])
        self.assertNotIn("plan_changes", self.steps())
        self.assertNotIn("plan_archive_final", self.steps())
        text = self.assert_filed("404 when the table is missing.")
        self.assertNotIn("<!-- pass", text)  # the original, not the reconciled copy

    def test_a_difference_asks_a_person(self):
        self.changed = True
        action = self.to_plan()
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "plan_changes"))
        self.assertEqual([o["id"] for o in action["options"]], ["accept", "keep", "edit"])
        self.assertIn("Export now refuses tables above 100k rows.", action["prompt"])
        self.assertIn(CHANGES, action["prompt"])
        self.assertTrue(action.get("say"))
        # nothing is filed until the person answers
        self.assertTrue(os.path.exists(os.path.join(self.tmp, ACTIVE)))

    def test_accept_files_the_reconciled_plan(self):
        self.changed = True
        self.to_plan()
        action = self.answer("plan_changes", "accept")
        self.assertEqual(action["step"], "harvest/plan_maps")
        self.assertNotIn("plan_archive", self.steps())
        self.assert_filed("413 above 100k rows")

    def test_keep_files_the_approved_plan(self):
        self.changed = True
        self.to_plan()
        action = self.answer("plan_changes", "keep")
        self.assertEqual(action["step"], "harvest/plan_maps")
        self.assertNotIn("plan_archive_final", self.steps())
        text = self.assert_filed("404 when the table is missing.")
        self.assertNotIn("413", text)

    def test_edit_reconciles_again_with_the_feedback(self):
        self.changed = True
        self.to_plan()
        action = self.answer("plan_changes", "edit", "the limit is 50k rows, not 100k")
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "plan_changes"))
        self.assertEqual(len(self.reconcile_prompts), 2)
        self.assertIn("the limit is 50k rows, not 100k", self.reconcile_prompts[-1])
        self.assertTrue(os.path.exists(os.path.join(self.tmp, ACTIVE)))
        action = self.answer("plan_changes", "accept")
        self.assertEqual(action["step"], "harvest/plan_maps")
        self.assertIn("<!-- pass 2 -->", self.assert_filed("413 above 100k rows"))

    def test_a_person_answers_plan_changes_in_auto_mode(self):
        self.changed = True
        action = self.to_plan(mode="auto")
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "plan_changes"))
        self.assertEqual(self.autopilot, [])

    def test_not_now_leaves_the_plan_in_active(self):
        self.start()
        self.advance()
        action = self.answer("confirm_archive", "skip")
        self.assertEqual(action["action"], "done")
        self.assertEqual(self.read(ACTIVE), MAJOR)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, COMPLETED)))
        self.assertEqual(self.reconcile_prompts, [])


if __name__ == "__main__":
    unittest.main()
