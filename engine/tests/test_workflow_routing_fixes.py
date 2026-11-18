"""Regression tests for routing fixes in the shipped workflows, driven through the real resolver
with the full-pipeline simulation of test_sdlc_e2e.py (canned agents, scripted gates, real engine
scripts). Each test names the failure it guards against.

Only the tests of this file run (the inherited scenarios of the base class are not repeated)."""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import state as statemod  # noqa: E402
import lld_set  # noqa: E402
import test_sdlc_e2e as e2e  # noqa: E402

APPROVE = {"design/prd/prd_approval": [("approve", None)],
           "design/hld/hld_approval": [("approve", None)],
           "design/lld/lld_scope": [("all", None)],
           "delivery/release_approval": [("approve", None)]}


def _git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


class WorkflowRoutingFixes(e2e.SdlcE2E):
    def steps(self, trace):
        return [s for _, s in trace]

    # -- design-hld: facts come from the HLD as finally approved ------------------------------

    def test_fix_hld_approved_after_an_escalation_reports_the_final_interfaces(self):
        """The first HLD lists no interface; the revision made while escalating adds one and the
        person approves. The stage must report interfaces_changed from the approved HLD, so the
        contract stage runs."""
        self.prep_tasks_json()
        hld = Path(self.tmp, ".maestro/runs/demo/design/hld.md")

        def write_hld():
            self.write_agent_artifact(".maestro/runs/demo/design/hld.md", "design/hld/write_hld")
            hld.write_text(hld.read_text().replace(
                "- The frontend calls the backend to load and save state (synchronous).",
                "None — nothing crosses repositories."))
            return {"hld_summary": "no interface", "needs_clarification": False}

        def escalate():
            hld.write_text(hld.read_text().replace(
                "None — nothing crosses repositories.",
                "- The frontend calls the backend to load and save state (synchronous)."))
            return {"hld_summary": "added an interface", "needs_clarification": False}
        resolutions = Path(self.tmp, ".maestro/runs/demo/reviews/architecture.resolutions.json")
        original = self.write_review_files

        def write_review_files(act, node, outputs):
            original(act, node, outputs)
            if node == "revise_from_review":
                resolutions.write_text(json.dumps({"schema_version": 1, "resolutions": [
                    {"id": "F1", "resolution": "escalated", "note": "a new interface"}]}))
        self.write_review_files = write_review_files
        blocked = {"review_path": "reviews/architecture.md", "blocking": True, "summary": "1 blocker"}
        action, trace = self.drive(dict(APPROVE), agent_overrides={
            "write_hld": write_hld, "arch_review": blocked, "revise_from_review": escalate})
        self.assertEqual(action["action"], "done", action)
        steps = self.steps(trace)
        self.assertLess(steps.index("design/hld/hld_approval"),
                        steps.index("design/hld/final_hld_facts"))
        self.assertIn("design/contract/contract", steps)
        outputs = statemod.load("demo", self.tmp)["steps"][e2e.SOLUTION + "hld"]["outputs"]
        self.assertTrue(outputs["interfaces_changed"] in (True, "true"), outputs)

    # -- impl / qa-bugfix: the commit reviewed is the worktree's HEAD at the gate decision ----

    def test_fix_review_after_the_gate_reads_the_worktree_head_the_fixer_left(self):
        """A fixer that committed and then escalated leaves HEAD ahead of the last handoff. The gate's
        "continue to code review" must review that HEAD, and delivery must record it."""
        self.prep_tasks_json()
        calls = []
        heads = {}

        def review():
            calls.append(1)
            return {"review_path": "reviews/summary.md", "blocking": len(calls) == 1,
                    "summary": "1 blocking" if len(calls) == 1 else "clean"}
        original = self.write_review_files

        def write_review_files(act, node, outputs):
            original(act, node, outputs)
            if node == "fix":
                worktree = re.search(r"^- worktree: (.+)$", act["prompt"], re.M).group(1).strip()
                Path(worktree, "fixed.txt").write_text("fixed\n")
                _git(worktree, "add", "-A")
                _git(worktree, "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-qm", "fix")
                heads[os.path.basename(worktree)] = _git(worktree, "rev-parse", "HEAD")
        self.write_review_files = write_review_files
        gates = dict(self.IMPL_GATES)
        for slot in ("slot_1", "slot_2"):
            gates[f"delivery/implement[{slot}]/impl/impl_gate"] = [("review", None)]
        action, trace = self.drive(gates, agent_overrides={
            "review": review,
            "fix": {"fix_summary": "committed, then needs a person", "checks_passed": True,
                    "escalate": True}})
        self.assertEqual(action["action"], "done", action)
        self.assertEqual(len(heads), 1)
        repo, head = next(iter(heads.items()))
        steps = self.impl_steps(trace, "fix")
        start = steps.index("impl_gate")
        self.assertEqual(steps[start:start + 5], ["impl_gate", "review_scope", "review_head",
                                                  "review", "review_verdict"])
        second_review = next(p[1] for st, p in self.prompts.items()
                             if st.endswith("/impl/review") and len(p) > 1)
        self.assertIn(f"exact commit {head}", second_review)
        self.assertIn(f"commit: {head}", second_review)
        reviewed = json.loads(Path(self.tmp, f".maestro/runs/demo/.engine/reviews/code-{repo}"
                                   ".reviewed.json").read_text())
        self.assertEqual(reviewed["commit"], head)
        manifest = json.loads(Path(self.tmp, ".maestro/runs/demo/build/manifest.json").read_text())
        recorded = {r["repo"]: r["commit"] for r in manifest["repositories"]}
        self.assertEqual(recorded[repo], head)

    def test_fix_accepting_at_the_gate_records_the_worktree_head(self):
        """"Accept as-is" after a fix that committed: delivery records HEAD, not the commit
        from before the fix (record would abort on the mismatch)."""
        self.prep_tasks_json()
        calls = []

        def review():
            calls.append(1)
            return {"review_path": "reviews/summary.md", "blocking": len(calls) == 1,
                    "summary": "1 blocking"}
        heads = {}
        original = self.write_review_files

        def write_review_files(act, node, outputs):
            original(act, node, outputs)
            if node == "fix":
                worktree = re.search(r"^- worktree: (.+)$", act["prompt"], re.M).group(1).strip()
                Path(worktree, "fixed.txt").write_text("fixed\n")
                _git(worktree, "add", "-A")
                _git(worktree, "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-qm", "fix")
                heads[os.path.basename(worktree)] = _git(worktree, "rev-parse", "HEAD")
        self.write_review_files = write_review_files
        gates = dict(self.IMPL_GATES)
        for slot in ("slot_1", "slot_2"):
            gates[f"delivery/implement[{slot}]/impl/impl_gate"] = [("accept", None)]
        action, trace = self.drive(gates, agent_overrides={
            "review": review,
            "fix": {"fix_summary": "committed, then needs a person", "checks_passed": True,
                    "escalate": True}})
        self.assertEqual(action["action"], "done", action)
        repo, head = next(iter(heads.items()))
        manifest = json.loads(Path(self.tmp, ".maestro/runs/demo/build/manifest.json").read_text())
        self.assertEqual({r["repo"]: r["commit"] for r in manifest["repositories"]}[repo], head)

    # -- impl: a second pass starts its review rounds from scratch ---------------------------

    def test_fix_a_fresh_pass_reviews_in_full_whatever_an_earlier_pass_left(self):
        self.prep_tasks_json()
        reviews = Path(self.tmp, ".maestro/runs/demo/reviews")
        reviews.mkdir(parents=True, exist_ok=True)
        (reviews / "code-backend.findings.json").write_text(json.dumps({"schema_version": 1, "findings": [
            {"id": "F1", "severity": "blocking", "area": "fit", "status": "open",
             "finding": "from the first pass", "evidence": "x"}]}))
        (reviews / "code-backend.md").write_text("first pass report\n")
        action, trace = self.drive(dict(self.IMPL_GATES))
        self.assertEqual(action["action"], "done", action)
        backend = next(p[0] for st, p in self.prompts.items()
                       if st.endswith("/impl/review") and "repo_path: codebase/backend" in p[0])
        flat = " ".join(backend.split())
        self.assertIn("review round 1 of this implementation pass", flat)
        self.assertIn("Round 1 is a first review of the whole implementation", flat)
        self.assertNotIn("${", backend)

    # -- impl: stopping a stack ends that stack only --------------------------------------------

    def test_fix_stopping_one_stack_ends_only_that_stack(self):
        self.prep_tasks_json()
        real = self.implementation_outputs
        calls = []

        def implementation_outputs(act):
            calls.append(1)
            outputs = real(act)
            if len(calls) == 1:
                outputs.update(escalate=True, escalation="needs an unplanned table")
            return outputs
        self.implementation_outputs = implementation_outputs
        gates = dict(self.IMPL_GATES)
        gates["delivery/implement[slot_1]/impl/stop_gate"] = [("abandon", None)]
        action, trace = self.drive(gates)
        steps = self.steps(trace)
        # the stopped stack's slot records nothing; the other stack is built, reviewed and recorded
        self.assertNotIn("delivery/implement[slot_1]/record", steps)
        self.assertIn("delivery/implement[slot_2]/record", steps)
        self.assertEqual(action["action"], "failed", action)
        # no "step failed - retry / skip / abort the run" gate for the stopped stack
        self.assertNotIn("delivery/implement[slot_1]/impl#ask", steps)
        # the run stops at the implementation check, which names what was left out
        self.assertEqual(steps[-1], "delivery/finalize_implementation")

    # -- design-lld: nothing is approved unvalidated -------------------------------------------

    def test_fix_llds_edited_while_escalating_are_checked_before_the_gate_and_before_approval(self):
        """The author escalates after editing an LLD into an invalid one: readiness_resolution sent
        that straight to the gate, and approving recorded hashes of the invalid file."""
        self.prep_tasks_json()
        self.fix_resolution = "escalated"
        broken = lld_set.lld_path("demo", "backend", self.tmp)
        calls = []

        def revise():
            calls.append(1)
            if len(calls) == 1:
                Path(broken).write_text("# broken LLD\n")
            return {"summary": "revised", "contract_change_needed": False,
                    "contract_change": "None", "needs_clarification": False}
        reviews = []

        def readiness():
            reviews.append(1)
            return {"review_path": "reviews/lld-readiness.md", "blocking": len(reviews) == 1,
                    "summary": "1 blocking"}
        action, trace = self.drive(dict(APPROVE), agent_overrides={
            "revise_llds": revise, "readiness_review": readiness})
        self.assertEqual(action["action"], "done", action)
        lld = [s.rsplit("/", 1)[-1] for _, s in trace if s.startswith("design/lld/")]
        first_gate = lld.index("lld_approval")
        self.assertEqual(lld[first_gate - 3:first_gate + 1],
                         ["readiness_resolution", "approval_validate", "approval_trace",
                          "lld_approval"])
        self.assertIn("valid false", self.prompts["design/lld/lld_approval"][0])
        # approving the invalid LLDs re-ran the check, which sent them back to the author
        self.assertEqual(lld[first_gate + 1:first_gate + 4],
                         ["final_validate", "revise_llds", "readiness_resolution"])
        self.assertEqual(lld.count("record_approval"), 1)
        self.assertEqual(lld[-3:], ["final_validate", "final_trace", "record_approval"])
        approval = json.loads(Path(lld_set.approval_path("demo", self.tmp)).read_text())
        self.assertEqual(approval["llds"]["backend"], statemod.sha256_file(broken))

    def test_fix_autopilot_does_not_approve_llds_the_engine_check_rejects(self):
        self.prep_tasks_json()
        broken = lld_set.lld_path("demo", "backend", self.tmp)
        calls = []

        def revise():
            calls.append(1)
            if len(calls) == 1:
                Path(broken).write_text("# broken LLD\n")
            return {"summary": "revised", "contract_change_needed": False,
                    "contract_change": "None", "needs_clarification": False}
        self.fix_resolution = "escalated"
        reviews = []

        def readiness():
            reviews.append(1)
            return {"review_path": "reviews/lld-readiness.md", "blocking": len(reviews) == 1,
                    "summary": "1 blocking"}
        action, trace = self.drive(dict(APPROVE), mode="auto", agent_overrides={
            "revise_llds": revise, "readiness_review": readiness})
        self.assertEqual(action["action"], "done", action)
        # the first arrival at the gate (invalid LLDs) was left to a person, not answered by autopilot
        gates = [(a, s) for a, s in trace if s == "design/lld/lld_approval"]
        self.assertEqual(gates[0][0], "ask_gate", gates)

    # -- qa: a person's extra fix round re-runs QA --------------------------------------------

    def test_fix_each_extra_qa_fix_round_reruns_qa_before_the_gate_shows_results(self):
        self.prep_tasks_json()
        gates = self._qa_gates([("retry", "try again")] * 4 + [("accept", None)])
        action, trace = self.drive(gates, agent_overrides={
            "qa_run": {"passed": False, "failed_count": 1, "summary": "still failing"},
            "qa_fix": {"fix_summary": "tried", "checks_passed": True, "escalate": False,
                       "product_bug": False, "bug_repos": ""}})
        self.assertEqual(action["action"], "done", action)
        qa = [s.rsplit("/", 1)[-1] for a, s in trace
              if s.startswith("delivery/qa/") and a != "ask_input"]
        gate_at = [i for i, s in enumerate(qa) if s == "qa_gate"]
        self.assertEqual(len(gate_at), 5)
        for i in gate_at:
            self.assertEqual(qa[i - 1], "qa_run", qa)  # the gate never shows a stale run

    # -- design-solution: a new product plans its architecture even when light was asked ---------

    def test_fix_greenfield_with_path_light_still_writes_the_hld_and_scaffolds(self):
        self.prep_tasks_json()
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
                map_path = Path(e2e.codebase_scan.map_path(self.tmp, repo))
                map_path.parent.mkdir(parents=True, exist_ok=True)
                map_path.write_text(f"# {repo} map\n")
                _git(path, "add", "-A")
                _git(path, "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-qm", "scaffold")
                report["repos"][repo] = {"stack": "python", "commands": {
                    "build": "test -f README.md", "test": "test ! -f BROKEN"}}
            Path(self.tmp, ".maestro/runs/demo/build/scaffold.json").write_text(json.dumps(report))
            return {"summary": "scaffolded"}
        action, trace = self.drive(dict(self.DESIGN_GATES), inputs={"path": "light"},
                                   agent_overrides={"write_hld": write_hld, "scaffold": scaffold})
        self.assertEqual(action["action"], "done", action)
        steps = self.steps(trace)
        self.assertIn("design/hld/write_hld", steps)
        self.assertIn("design/scaffold/scaffold", steps)
        self.assertLess(steps.index("design/scaffold/scaffold"), steps.index("design/lld/lld_scope_init"))

    # -- sdlc-main: the "design is current" sentence is not release feedback -----------------------

    def test_fix_release_revise_feedback_carries_only_the_person_note(self):
        """A release sent back with a note re-enters design with that note alone; the engine's
        "approved LLDs match the HLD" line (printed when nothing is stale) is not feedback. The
        second delivery pass also reviews from round 1 again."""
        self.prep_tasks_json()
        gates = {
            "design/prd/prd_approval": [("approve", None)] * 2,
            "design/hld/hld_approval": [("approve", None)] * 2,
            "design/lld/lld_scope": [("all", None)] * 2,
            "delivery/release_approval": [("revise", "tighten the retry limit"), ("approve", None)],
        }
        action, trace = self.drive(gates, max_steps=260)
        self.assertEqual(action["action"], "done", action)
        designs = [p for st, ps in self.prompts.items() if st.startswith("design/") for p in ps]
        self.assertTrue([p for p in designs if "tighten the retry limit" in p])
        self.assertFalse([p for p in designs if "approved LLDs match the HLD" in p])
        backend = [p for st, ps in self.prompts.items() if st.endswith("/impl/review")
                   for p in ps if "repo_path: codebase/backend" in p]
        self.assertEqual(len(backend), 2)  # one review per delivery pass
        for prompt in backend:  # the second pass is not a re-review of the first pass's files
            self.assertIn("review round 1 of this implementation pass", " ".join(prompt.split()))


def load_tests(loader, standard_tests, pattern):
    """Only this file's scenarios: the base class's own tests are test_sdlc_e2e.py's."""
    suite = unittest.TestSuite()
    for name in loader.getTestCaseNames(WorkflowRoutingFixes):
        if name.startswith("test_fix_"):
            suite.addTest(WorkflowRoutingFixes(name))
    return suite


if __name__ == "__main__":
    unittest.main()
