"""Full-pipeline simulation of the bug-fix flow: the REAL bugfix.yaml (workspace sync -> triage ->
delivery with `entry: bugfix` -> archive) driven through the engine with zero LLM, reusing the
SdlcE2E driver. Agent outputs are canned, gates are scripted, and the engine scripts that matter to
a bug fix (branch check, base map, sandbox worktrees, claim, approval, delivery) run for real
against temporary git repositories that have real branches."""
import json
import os
import re
import stat
import subprocess
import sys
import unittest  # noqa: F401
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import resolver  # noqa: E402
import state as statemod  # noqa: E402
import test_sdlc_e2e as base  # noqa: E402

BUGFIX = ".maestro/workflows/bugfix.yaml"
RUN = ".maestro/runs/demo"
FAKE_GH = """#!/bin/sh
echo "$@" >> "$GH_LOG"
case "$1 $2" in
  "pr list") ;;
  "pr create") echo "https://github.test/pr/$(basename "$PWD")" ;;
esac
"""


class BugfixE2E(base.SdlcE2E):
    plan_type = "minor"      # the mini PRD the triage writes validates as `--type minor`
    real_worktrees = True    # check-base, bases and prepare run for real
    affected = "backend,frontend"
    reproduced = True

    def setUp(self):
        super().setUp()
        self.default = {}
        for repo in ("backend", "frontend"):
            path = self.repo_path(repo)
            self.default[repo] = self.vcs("branch", "--show-current", root=path)
            self.vcs("checkout", "-q", "-b", "release-1", root=path)
            Path(path, "app.txt").write_text(f"{repo} on release-1\n")
            self.vcs("add", "app.txt", root=path)
            self.vcs("commit", "-q", "-m", "release-1", root=path)
            self.vcs("checkout", "-q", self.default[repo], root=path)

    def repo_path(self, repo):
        return os.path.join(self.tmp, "codebase", repo)

    # -- canned agents ---------------------------------------------------------------------
    def claimed(self):
        return statemod.load("demo", self.tmp)["steps"]["delivery/bugfix_claim"]["outputs"]

    def agents(self, **extra):
        def triage():
            Path(self.tmp, RUN, "requirement", "bug.md").write_text(
                "# Export button missing\n\nBranch: release-1\n")
            return {"summary": "Export button hidden", "repos_csv": self.affected}

        def reproduce():
            return {"reproduced": self.reproduced, "summary": "reproduction attempted"}

        def propose_fix():
            return {"summary": "Default the flag on", "cause": "A flag hides the button.",
                    "change": "backend: default the flag on.", "impact": "Users see the button.",
                    "risks": "None"}

        def fix():
            worktree = self.claimed()["worktree"]
            Path(worktree, "fix.txt").write_text(f"fixed {next(base._ARTIFACT_WRITES)}\n")
            self.vcs("add", "fix.txt", root=worktree)
            self.vcs("commit", "-q", "-m", "fix: show the export button", root=worktree)
            return {"fix_summary": "flag defaulted on", "checks_passed": True, "escalate": False}

        def review():
            repo = self.claimed()["repo"]
            return {"review_path": f"{RUN}/reviews/code-{repo}.md", "blocking": False,
                    "summary": "no findings"}

        return {"triage": triage, "reproduce": reproduce, "propose_fix": propose_fix,
                "fix": fix, "review": review, **extra}

    def go(self, gates, **kw):
        kw.setdefault("inputs", {"branch": "release-1"})
        overrides = self.agents(**kw.pop("agents", {}))
        return self.drive(gates, workflow=BUGFIX, agent_overrides=overrides, **kw)

    def bug_gates(self, reproduce="reproduce", **replace):
        gates = {
            "triage/reproduce_choice": [(reproduce, None)],
            "triage/fix_approval": [("approve", None)],
            "delivery/release_approval": [("approve", None)],
        }
        gates.update(replace)
        return gates

    @staticmethod
    def asked(trace, step):
        return [s for a, s in trace if a == "ask_gate"].count(step)

    @staticmethod
    def steps_of(trace):
        return [s for _, s in trace]

    def bases(self):
        return self.read_json(f"{RUN}/.engine/bug-bases.json")

    def read_json(self, rel):
        return json.loads(Path(self.tmp, rel).read_text())

    def sandbox(self):
        return {r["repo"]: r for r in self.read_json(f"{RUN}/.engine/sandbox.json")["repositories"]}

    def drop_branch(self, repo):
        self.vcs("branch", "-q", "-D", "release-1", root=self.repo_path(repo))

    # -- scenarios --------------------------------------------------------------------------
    def test_happy_path_from_bug_to_archive(self):
        action, trace = self.go(self.bug_gates())
        self.assertEqual(action["action"], "done", action)
        steps = self.steps_of(trace)
        order = ["triage/triage", "triage/test_cases/test_cases", "triage/reproduce_choice",
                 "triage/branch_check", "triage/bug_bases", "triage/sandbox",
                 "triage/register_sandbox", "triage/env_up", "triage/reproduce",
                 "triage/env_down", "triage/propose_fix", "triage/fix_approval",
                 "triage/record_approval", "delivery/design_check", "delivery/bugfix_entry",
                 "delivery/bugfix_claim", "delivery/bugfix/fix", "delivery/bugfix/review",
                 "delivery/bugfix_record", "delivery/finalize_implementation",
                 "delivery/release_approval", "archive/deliver"]
        positions = [steps.index(s) for s in order]
        self.assertEqual(positions, sorted(positions))
        for absent in ("triage/missing_branch", "triage/not_reproduced",
                       "delivery/workspace_sync_pre_impl/plan", "delivery/impl_scope_init",
                       "archive/plan_reconcile", "archive/plan_commit"):
            self.assertNotIn(absent, steps)
        self.assertEqual(steps.count("delivery/bugfix/fix"), 2)  # one per affected repository
        self.assertEqual([s for a, s in trace if a == "ask_gate"],
                         ["triage/reproduce_choice", "triage/fix_approval",
                          "delivery/release_approval", "archive/confirm_archive"])
        self.assertIn("design/fix-proposal.md", self.prompts["delivery/bugfix/fix"][0])
        # the branch is the base of every repository
        self.assertEqual(self.bases(), {"backend": "release-1", "frontend": "release-1"})
        sandbox = self.sandbox()
        for repo in ("backend", "frontend"):
            self.assertEqual(sandbox[repo]["branch"], f"fix/demo-{repo}")
            self.assertEqual(sandbox[repo]["base_commit"],
                             self.vcs("rev-parse", "release-1", root=self.repo_path(repo)))
        manifest = self.read_json(f"{RUN}/build/manifest.json")
        self.assertEqual({r["repo"]: r["base"] for r in manifest["repositories"]},
                         {"backend": "release-1", "frontend": "release-1"})
        for row in manifest["repositories"]:
            self.assertEqual(row["branch"], f"fix/demo-{row['repo']}")
            self.assertNotEqual(row["commit"], sandbox[row["repo"]]["base_commit"])
            self.assertEqual(self.vcs("rev-parse", row["branch"],
                                      root=self.repo_path(row["repo"])), row["commit"])
        record = self.read_json(f"{RUN}/release/delivery.json")
        self.assertEqual(record["mode"], "branch")
        self.assertEqual({r["repo"]: r["base"] for r in record["repositories"]},
                         {"backend": "release-1", "frontend": "release-1"})
        self.assertIn("Verified branches ready to merge", action["outputs"]["delivery"])
        # no plan: nothing under docs/plans, no commit in the workspace, the approval says so
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "docs", "plans")))
        approval = self.read_json(f"{RUN}/.engine/plan-approval.json")
        self.assertEqual((approval["plan"], approval["plan_path"]), (False, None))
        self.assertEqual(sorted(approval["repos"]), ["backend", "frontend"])
        self.assertEqual(statemod.load("demo", self.tmp)["steps"][
            "delivery/release_approval"]["outputs"]["by"], "person")

    def test_skip_reproduction_goes_straight_to_the_proposal(self):
        action, trace = self.go(self.bug_gates(reproduce="skip"))
        self.assertEqual(action["action"], "done", action)
        steps = self.steps_of(trace)
        for gone in ("triage/env_up", "triage/reproduce", "triage/env_down",
                     "triage/not_reproduced"):
            self.assertNotIn(gone, steps)
        self.assertLess(steps.index("triage/sandbox"), steps.index("triage/propose_fix"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, RUN, "qa", "reproduction.md")))

    def test_missing_branch_default_bases_that_repo_on_its_default_branch(self):
        self.drop_branch("frontend")
        action, trace = self.go(self.bug_gates(**{"triage/missing_branch": [("default", None)]}))
        self.assertEqual(action["action"], "done", action)
        self.assertIn("frontend", self.prompts["triage/missing_branch"][0])
        self.assertEqual(self.bases(), {"backend": "release-1",
                                        "frontend": self.default["frontend"]})
        manifest = self.read_json(f"{RUN}/build/manifest.json")
        self.assertEqual({r["repo"]: r["base"] for r in manifest["repositories"]},
                         {"backend": "release-1", "frontend": self.default["frontend"]})
        self.assertEqual(self.sandbox()["frontend"]["base_commit"],
                         self.vcs("rev-parse", self.default["frontend"],
                                  root=self.repo_path("frontend")))
        self.assertEqual(self.sandbox()["backend"]["base_commit"],
                         self.vcs("rev-parse", "release-1", root=self.repo_path("backend")))

    def test_missing_branch_named_branch_that_exists_is_used(self):
        self.vcs("branch", "-q", "-m", "release-1", "release-2", root=self.repo_path("frontend"))
        gates = self.bug_gates(**{"triage/missing_branch": [("named", "frontend=release-2")]})
        action, trace = self.go(gates)
        self.assertEqual(action["action"], "done", action)
        self.assertEqual(self.bases(), {"backend": "release-1", "frontend": "release-2"})
        self.assertIn(("ask_input", "triage/missing_branch"), trace)

    def test_missing_branch_wrong_name_asks_again_with_a_problem(self):
        self.vcs("branch", "-q", "-m", "release-1", "release-2", root=self.repo_path("frontend"))
        gates = self.bug_gates(**{"triage/missing_branch": [
            ("named", "frontend=nope"), ("named", "frontend=release-2")]})
        action, trace = self.go(gates)
        self.assertEqual(action["action"], "done", action)
        asked = self.prompts["triage/missing_branch"]
        self.assertEqual(len(asked), 2)
        self.assertNotIn("frontend has no branch nope", asked[0])
        self.assertIn("frontend has no branch nope", asked[1])
        self.assertEqual(self.bases(), {"backend": "release-1", "frontend": "release-2"})

    def test_missing_branch_drop_goes_back_to_triage(self):
        self.drop_branch("frontend")

        def triage():
            out = self.agents()["triage"]()
            if len(self.prompts["triage/triage"]) >= 2:  # the person leaves frontend out
                out["repos_csv"] = "backend"
            return out

        gates = self.bug_gates(**{"triage/missing_branch": [("drop", None)],
                                  "triage/reproduce_choice": [("skip", None), ("skip", None)]})
        action, trace = self.go(gates, agents={"triage": triage})
        self.assertEqual(action["action"], "done", action)
        self.assertEqual(len(self.prompts["triage/triage"]), 2)
        self.assertIn("drop = remove frontend", self.prompts["triage/triage"][1])
        self.assertEqual(self.bases(), {"backend": "release-1"})
        manifest = self.read_json(f"{RUN}/build/manifest.json")
        self.assertEqual([r["repo"] for r in manifest["repositories"]], ["backend"])

    def test_not_reproduced_more_info_returns_to_triage_with_the_feedback(self):
        flags = iter([False, True])
        gates = self.bug_gates(**{
            "triage/reproduce_choice": [("reproduce", None), ("reproduce", None)],
            "triage/not_reproduced": [("more-info", "it only happens for admins")]})
        action, trace = self.go(gates, agents={
            "reproduce": lambda: {"reproduced": next(flags), "summary": "tried"}})
        self.assertEqual(action["action"], "done", action)
        steps = self.steps_of(trace)
        self.assertEqual(self.asked(trace, "triage/not_reproduced"), 1)
        self.assertEqual(steps.count("triage/triage"), 2)
        self.assertIn("it only happens for admins", self.prompts["triage/triage"][1])
        self.assertLess(steps.index("triage/not_reproduced"), steps.index("triage/propose_fix"))

    def test_not_reproduced_proceed_continues_to_the_proposal(self):
        self.reproduced = False
        gates = self.bug_gates(**{"triage/not_reproduced": [("proceed", None)]})
        action, trace = self.go(gates)
        self.assertEqual(action["action"], "done", action)
        steps = self.steps_of(trace)
        self.assertLess(steps.index("triage/not_reproduced"), steps.index("triage/propose_fix"))

    def test_fix_approval_later_pauses_and_a_resume_serves_it_again(self):
        gates = self.bug_gates(**{"triage/fix_approval": [("later", None)]})
        action, trace = self.go(gates)
        self.assertEqual(action["action"], "paused", action)
        self.assertEqual(action["resume"], "/maestro demo")
        self.assertEqual(self.asked(trace, "triage/fix_approval"), 1)
        self.assertNotIn("delivery/design_check", self.steps_of(trace))
        # resume: the same run, the same question, then the run goes on to the end
        gates = self.bug_gates(**{"triage/fix_approval": [("approve", None)]})
        action, trace = self.go(gates)
        self.assertEqual(action["action"], "done", action)
        steps = self.steps_of(trace)
        self.assertEqual(self.asked(trace, "triage/fix_approval"), 1)
        self.assertNotIn("triage/triage", steps)  # nothing before the gate reran
        self.assertIn("delivery/bugfix/fix", steps)

    def test_fix_approval_revise_reruns_the_proposal_with_the_feedback(self):
        gates = self.bug_gates(**{"triage/fix_approval": [
            ("revise", "keep the flag, fix the template"), ("approve", None)]})
        action, trace = self.go(gates)
        self.assertEqual(action["action"], "done", action)
        steps = self.steps_of(trace)
        self.assertEqual(steps.count("triage/propose_fix"), 2)
        self.assertEqual(steps.count("triage/triage"), 1)
        self.assertEqual(steps.count("triage/sandbox"), 1)
        self.assertIn("keep the flag, fix the template", self.prompts["triage/propose_fix"][1])

    def test_fix_approval_re_triage_goes_back_to_triage(self):
        gates = self.bug_gates(**{
            "triage/fix_approval": [("re-triage", "it is the mobile build too"), ("approve", None)],
            "triage/reproduce_choice": [("reproduce", None), ("skip", None)]})
        action, trace = self.go(gates)
        self.assertEqual(action["action"], "done", action)
        steps = self.steps_of(trace)
        self.assertEqual(steps.count("triage/triage"), 2)
        self.assertIn("it is the mobile build too", self.prompts["triage/triage"][1])
        self.assertEqual(self.asked(trace, "triage/fix_approval"), 2)

    def test_auto_mode_serves_the_choice_the_approval_and_the_archive_to_a_person(self):
        action, trace = self.go({
            "triage/reproduce_choice": [("skip", None)],
            "triage/fix_approval": [("approve", None)],
            "archive/confirm_archive": [("archive", None)]}, mode="auto")
        self.assertEqual(action["action"], "done", action)
        asked = [s for a, s in trace if a == "ask_gate"]
        self.assertEqual(asked, ["triage/reproduce_choice", "triage/fix_approval",
                                 "archive/confirm_archive"])
        self.assertIn(("auto_gate", "delivery/release_approval"), trace)
        self.assertEqual(self.autopilot_gates(), {"delivery/release_approval"})
        self.assertEqual(statemod.load("demo", self.tmp)["steps"][
            "delivery/release_approval"]["outputs"]["by"], "autopilot")
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, RUN, "release/delivery.json")))

    def test_release_revise_goes_back_to_triage(self):
        gates = self.bug_gates(**{
            "triage/reproduce_choice": [("skip", None), ("skip", None)],
            "triage/fix_approval": [("approve", None), ("approve", None)],
            "delivery/release_approval": [("revise", "the button is still misaligned"),
                                          ("approve", None)]})
        action, trace = self.go(gates)
        self.assertEqual(action["action"], "done", action)
        steps = self.steps_of(trace)
        self.assertEqual(steps.count("triage/triage"), 2)
        self.assertIn("the button is still misaligned", self.prompts["triage/triage"][1])
        self.assertEqual(self.asked(trace, "delivery/release_approval"), 2)

    def test_starting_without_a_branch_is_refused(self):
        with statemod.locked("demo", self.tmp):
            with self.assertRaises(Exception) as ctx:
                resolver.init_run("demo", BUGFIX, {"feature": "Demo"}, self.tmp)
        self.assertIn("branch", str(ctx.exception))

    def test_pull_requests_target_each_repositorys_own_base(self):
        """delivery.mode pull-request with a faked gh and local bare remotes: each repository's PR
        is opened against the base its sandbox was built from."""
        self.drop_branch("frontend")  # frontend falls back to its default branch
        gh = os.path.join(self.tmp, "gh")
        Path(gh).write_text(FAKE_GH)
        os.chmod(gh, os.stat(gh).st_mode | stat.S_IEXEC)
        log = os.path.join(self.tmp, "gh.log")
        env = {"MAESTRO_GH": gh, "GH_LOG": log}
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)

        def restore():
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        self.addCleanup(restore)
        for repo in ("backend", "frontend"):
            remote = os.path.join(self.tmp, f"{repo}.git")
            subprocess.run(["git", "init", "-q", "--bare", remote], check=True)
            self.vcs("remote", "add", "origin", remote, root=self.repo_path(repo))
        with open(os.path.join(self.tmp, "maestro.config.yaml"), "a") as fh:
            fh.write("delivery: {mode: pull-request}\n")
        gates = self.bug_gates(**{"triage/missing_branch": [("default", None)]})
        action, _ = self.go(gates)
        self.assertEqual(action["action"], "done", action)
        calls = [c for c in Path(log).read_text().splitlines() if c.startswith("pr create")]
        self.assertEqual(len(calls), 2)
        by_head = {re.search(r"--head (\S+)", c).group(1): re.search(r"--base (\S+)", c).group(1)
                   for c in calls}
        self.assertEqual(by_head, {"fix/demo-backend": "release-1",
                                   "fix/demo-frontend": self.default["frontend"]})
        record = self.read_json(f"{RUN}/release/delivery.json")
        self.assertEqual(record["mode"], "pull-request")
        self.assertEqual({r["repo"]: r["base"] for r in record["repositories"]},
                         {"backend": "release-1", "frontend": self.default["frontend"]})


# the inherited feature-pipeline scenarios belong to test_sdlc_e2e.py: do not run them again here
for _name in dir(base.SdlcE2E):
    if _name.startswith("test_"):
        setattr(BugfixE2E, _name, None)

if __name__ == "__main__":
    import unittest as _u
    _u.main()
