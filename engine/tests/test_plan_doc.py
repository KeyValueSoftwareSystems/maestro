"""plan_doc: the plan document's structure per type, its hash-bound approval, the move to
completed/, and committing the plan file and nothing else."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import plan_doc  # noqa: E402

SLUG = "demo"

PRD = """# Demo — PRD

**Feature slug:** `demo`
**Status:** Ready for review

## Problem

People cannot export data.

## Acceptance criteria

- AC-01: an export downloads.
- AC-02: an empty export says so.

## Out of scope

Imports.
"""

MAJOR = """# Export — plan
Type: major · Run: {run} · PRD: .maestro/runs/demo/requirement/prd.md · Status: active

## Summary
Add an export endpoint and a button.

## Decisions
- CSV only — simplest for users — rejected XLSX

## Repositories
| repo | role in this change | new? |
|------|---------------------|------|
| api | export endpoint | no |
| `web` | export button | no |
{extra_row}
## Design
api: new route. web: new button.

## Interfaces
GET /export -> text/csv

## Infrastructure
None

## Risks and open points
Large exports may be slow.

## Acceptance coverage
- AC-01 → api / export route
{ac2}
## Out of scope
Imports.
"""

MINOR = """# Export — plan
Type: minor · Run: demo · Repositories: api, web
- Change: add a CSV export
- Where: api/routes/export.py, web/ExportButton.tsx
- Interface: GET /export
- Data: None
- Tests: route test, button test
- Risk: large exports
"""


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = plan_doc.main(list(argv))
    text = out.getvalue().strip()
    return code, (json.loads(text) if text else None), err.getvalue()


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="plan-doc-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.write("maestro.config.yaml", "version: 1\nrepos:\n  api: {}\n  web: {}\n")
        self.write(".maestro/runs/demo/requirement/prd.md", PRD)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def plan(self, text):
        return self.write("docs/plans/active/demo.md", text)

    def major(self, run="demo", extra_row="", ac2="- AC-02 → web / empty state\n"):
        return self.plan(MAJOR.format(run=run, extra_row=extra_row, ac2=ac2))

    def validate(self, kind):
        code, out, _err = run("validate", "--root", self.root, "--slug", SLUG, "--type", kind)
        self.assertEqual(code, 0)
        return out


class ValidateTest(Base):
    def test_a_complete_major_plan_is_valid(self):
        self.major()
        out = self.validate("major")
        self.assertTrue(out["valid"], out["issues"])
        self.assertEqual(out["repos_csv"], "api,web")
        self.assertEqual(out["new_repos_csv"], "")

    def test_major_missing_section_and_wrong_type(self):
        self.plan(MAJOR.format(run="demo", extra_row="", ac2="").replace("## Infrastructure\nNone\n",
                                                                         ""))
        out = self.validate("minor")
        self.assertFalse(out["valid"])
        self.assertTrue(any("Type: minor" in issue for issue in out["issues"]))
        out = self.validate("major")
        self.assertTrue(any("## Infrastructure" in issue for issue in out["issues"]))

    def test_every_prd_criterion_must_be_covered(self):
        self.major(ac2="")
        out = self.validate("major")
        self.assertFalse(out["valid"])
        self.assertIn("AC-02", out["issues_summary"])

    def test_an_unknown_repository_must_be_marked_new(self):
        self.major(extra_row="| billing | invoices | no |\n")
        out = self.validate("major")
        self.assertIn("'billing'", out["issues_summary"])
        self.major(extra_row="| billing | invoices | yes |\n")
        out = self.validate("major")
        self.assertTrue(out["valid"], out["issues"])
        self.assertEqual(out["new_repos_csv"], "billing")
        self.assertEqual(plan_doc.new_repositories(SLUG, self.root), ["billing"])

    def test_a_plan_bound_to_another_run_is_refused(self):
        self.major(run="other")
        out = self.validate("major")
        self.assertFalse(out["valid"])
        self.assertIn("belongs to run 'other'", out["issues_summary"])

    def test_a_missing_plan_is_invalid(self):
        out = self.validate("major")
        self.assertFalse(out["valid"])
        self.assertIn("missing", out["issues_summary"])

    def test_a_minor_plan(self):
        self.plan(MINOR)
        out = self.validate("minor")
        self.assertTrue(out["valid"], out["issues"])
        self.assertEqual(out["repos_csv"], "api,web")

    def test_minor_needs_every_key(self):
        self.plan(MINOR.replace("- Risk: large exports\n", ""))
        out = self.validate("minor")
        self.assertFalse(out["valid"])
        self.assertIn("- Risk:", out["issues_summary"])

    def test_minor_line_cap(self):
        self.plan(MINOR + "".join(f"- Note {n}: more\n" for n in range(4)))
        out = self.validate("minor")
        self.assertFalse(out["valid"])
        self.assertIn("this one has 11", out["issues_summary"])
        self.plan("# Export — plan\nType: minor · Run: demo · Repositories: api\n- Change: x\n"
                  "- Where: y\n")
        self.assertIn("this one has 3", self.validate("minor")["issues_summary"])

    def test_minor_new_repository_marker(self):
        self.plan(MINOR.replace("Repositories: api, web", "Repositories: api, billing (new)"))
        out = self.validate("minor")
        self.assertTrue(out["valid"], out["issues"])
        self.assertEqual(out["new_repos_csv"], "billing")

    def test_repos_command(self):
        self.major()
        code, out, _ = run("repos", "--root", self.root, "--slug", SLUG)
        self.assertEqual((code, out["repos_csv"], out["count"]), (0, "api,web", 2))


class ApprovalTest(Base):
    def verify(self):
        code, out, _ = run("verify", "--root", self.root, "--slug", SLUG)
        self.assertEqual(code, 0)
        return out

    def test_no_record_is_stale(self):
        self.assertTrue(self.verify()["stale"])

    def test_approve_writes_scope_and_binds_hashes(self):
        self.major()
        self.write(".maestro/runs/demo/design/test-cases.md", "# cases\n")
        code, out, err = run("approve", "--root", self.root, "--slug", SLUG)
        self.assertEqual(code, 0, err)
        with open(plan_doc.scope_path(SLUG, self.root), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["selected"], ["api", "web"])
        self.assertFalse(self.verify()["stale"])
        with open(os.path.join(self.root, "docs/plans/active/demo.md"), "a") as fh:
            fh.write("\nedited\n")
        out = self.verify()
        self.assertTrue(out["stale"])
        self.assertIn("the plan changed", out["reasons_summary"])

    def test_test_case_and_prd_edits_are_stale(self):
        self.major()
        self.write(".maestro/runs/demo/design/test-cases.md", "# cases\n")
        run("approve", "--root", self.root, "--slug", SLUG)
        self.write(".maestro/runs/demo/design/test-cases.md", "# cases 2\n")
        self.write(".maestro/runs/demo/requirement/prd.md", PRD + "\n")
        reasons = self.verify()["reasons"]
        self.assertEqual(len(reasons), 2)

    def test_bugfix_binds_prd_and_test_cases_only(self):
        self.write(".maestro/runs/demo/design/test-cases.md", "# cases\n")
        code, _out, err = run("approve", "--root", self.root, "--slug", SLUG, "--no-plan")
        self.assertEqual(code, 0, err)
        self.assertFalse(self.verify()["stale"])
        self.assertFalse(os.path.exists(plan_doc.scope_path(SLUG, self.root)))
        self.write(".maestro/runs/demo/design/test-cases.md", "# changed\n")
        self.assertTrue(self.verify()["stale"])

    def test_approve_without_a_plan_is_refused(self):
        code, _out, err = run("approve", "--root", self.root, "--slug", SLUG)
        self.assertEqual(code, 1)
        self.assertIn("no plan", err)


class ArchiveTest(Base):
    def test_status_and_archive_move(self):
        self.major()
        code, out, _ = run("status", "--root", self.root, "--slug", SLUG)
        self.assertEqual(out, {"active": True, "completed": False,
                               "path": "docs/plans/active/demo.md"})
        code, out, err = run("archive", "--root", self.root, "--slug", SLUG)
        self.assertEqual(code, 0, err)
        self.assertEqual(out["moved_by"], "move")
        done = os.path.join(self.root, "docs/plans/completed/demo.md")
        with open(done, encoding="utf-8") as fh:
            header = fh.read().splitlines()[1]
        self.assertTrue(header.endswith("Status: completed"), header)
        self.assertFalse(os.path.exists(os.path.join(self.root, "docs/plans/active/demo.md")))
        _code, out, _ = run("status", "--root", self.root, "--slug", SLUG)
        self.assertEqual(out["path"], "docs/plans/completed/demo.md")

    def test_final_replaces_content_and_minor_gets_a_status(self):
        self.major()
        final = self.write("final.md", MINOR)
        code, _out, err = run("archive", "--root", self.root, "--slug", SLUG, "--final", final)
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.root, "docs/plans/completed/demo.md"), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(lines[1], "Type: minor · Run: demo · Repositories: api, web · "
                                   "Status: completed")

    def test_never_overwrites_a_completed_plan(self):
        self.major()
        self.write("docs/plans/completed/demo.md", "# shipped\n")
        code, _out, err = run("archive", "--root", self.root, "--slug", SLUG)
        self.assertEqual(code, 1)
        self.assertIn("never overwritten", err)
        self.assertTrue(os.path.exists(os.path.join(self.root, "docs/plans/active/demo.md")))


class CommitTest(Base):
    def init_git(self):
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "T")
        git(self.root, "config", "commit.gpgsign", "false")
        self.write("README.md", "hi\n")
        git(self.root, "add", "README.md")
        git(self.root, "commit", "-q", "-m", "init")

    def commit(self, event):
        code, out, _ = run("commit", "--root", self.root, "--slug", SLUG, "--event", event)
        self.assertEqual(code, 0)
        return out

    def test_commits_only_the_plan_and_leaves_staged_work_alone(self):
        self.init_git()
        self.write("README.md", "staged change\n")
        git(self.root, "add", "README.md")
        self.write("other.txt", "untracked\n")
        self.major()
        out = self.commit("created")
        self.assertTrue(out["committed"], out)
        self.assertEqual(out["branch"], "main")
        self.assertEqual(out["say"], "Saved the plan to main.")
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "plan(demo): created")
        self.assertEqual(git(self.root, "show", "--name-only", "--format=", "HEAD"),
                         "docs/plans/active/demo.md")
        status = git(self.root, "status", "--porcelain")
        self.assertIn("M  README.md", status)       # still staged, not committed
        self.assertIn("?? other.txt", status)
        with open(os.path.join(self.root, ".maestro/runs/demo/.engine/plan-commits.json")) as fh:
            history = json.load(fh)
        self.assertEqual(history[0]["event"], "created")
        self.assertEqual(history[0]["commit"], out["commit"])
        # nothing changed -> skipped
        out = self.commit("updated")
        self.assertFalse(out["committed"])
        self.assertIn("not changed", out["reason"])

    def test_completed_commits_the_rename(self):
        self.init_git()
        self.major()
        self.commit("created")
        code, out, err = run("archive", "--root", self.root, "--slug", SLUG)
        self.assertEqual(code, 0, err)
        self.assertEqual(out["moved_by"], "git-mv")
        out = self.commit("completed")
        self.assertTrue(out["committed"], out)
        names = git(self.root, "show", "--name-status", "--format=", "-M", "HEAD")
        self.assertIn("docs/plans/completed/demo.md", names)
        self.assertIn("docs/plans/active/demo.md", names)
        self.assertEqual(git(self.root, "status", "--porcelain", "--", "docs"), "")

    def test_auto_event_is_created_then_updated(self):
        self.init_git()
        self.major()
        out = self.commit("auto")
        self.assertEqual((out["committed"], out["event"]), (True, "created"))
        with open(os.path.join(self.root, "docs/plans/active/demo.md"), "a") as fh:
            fh.write("\nOne more line.\n")
        out = self.commit("auto")
        self.assertEqual((out["committed"], out["event"]), (True, "updated"))
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "plan(demo): updated")

    def test_skips_outside_git_and_during_a_merge(self):
        self.major()
        out = self.commit("created")
        self.assertFalse(out["committed"])
        self.assertIn("not a git repository", out["reason"])
        self.init_git()
        with open(os.path.join(self.root, ".git", "MERGE_HEAD"), "w") as fh:
            fh.write(git(self.root, "rev-parse", "HEAD") + "\n")
        out = self.commit("created")
        self.assertFalse(out["committed"])
        self.assertIn("merge", out["reason"])


if __name__ == "__main__":
    unittest.main()
