"""The run folder's layout: the shipped workflows keep to it, and a run written under the earlier
flat layout is moved into it without losing an approval, a receipt or a decision."""
import glob
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lld_set  # noqa: E402
import maestroctl  # noqa: E402
import run_layout  # noqa: E402
import state as statemod  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUN_PATH = re.compile(r"\.maestro/runs/\$\{inputs\.slug\}/((?:\$\{[^}]+\}|[A-Za-z0-9_.<>/-])+)")


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class ShippedWorkflowsTest(unittest.TestCase):
    def paths(self):
        for path in sorted(glob.glob(os.path.join(REPO, "workflows", "*.yaml"))):
            with open(path, encoding="utf-8") as fh:
                for match in RUN_PATH.finditer(fh.read()):
                    yield os.path.basename(path), match.group(1).rstrip("./")

    def test_every_run_path_is_in_a_folder_of_the_layout(self):
        """Nothing but the ledger sits at the top of a run folder."""
        stray = sorted({(name, rel) for name, rel in self.paths()
                        if rel and rel.split("/")[0] not in run_layout.FOLDERS
                        and rel != "state.yaml"})
        self.assertEqual(stray, [])

    def test_no_workflow_names_a_path_of_the_flat_layout(self):
        for path in sorted(glob.glob(os.path.join(REPO, "workflows", "*.yaml"))):
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(run_layout.legacy_paths(fh.read()), [], os.path.basename(path))

    def test_workflows_and_engine_helpers_agree_on_the_shared_files(self):
        """A file a workflow names and a helper finds by itself must be the same file."""
        named = {rel for _name, rel in self.paths()}
        for rel in (run_layout.PRD, run_layout.HLD, run_layout.CONTRACT, run_layout.TEST_CASES,
                    run_layout.IMPACT, run_layout.DECISION_LOG, run_layout.WORKSPACE_LOCK,
                    run_layout.DESIGN_FACTS, run_layout.stage_record("PRD"),
                    run_layout.queue("hld"), run_layout.lld("${inputs.stack}"),
                    run_layout.receipt("${inputs.stack}"), run_layout.reviewed("${inputs.repo}")):
            self.assertIn(rel, named)

    def test_an_edited_old_workflow_is_told_what_to_rename(self):
        text = ('artifact: ".maestro/runs/${inputs.slug}/hld.md"\n'
                'x: .maestro/runs/${inputs.slug}/${inputs.stack}/reviews/findings.json\n'
                'y: .maestro/runs/${inputs.slug}/decision-log.json and requirement/prd.md\n'
                'z: .maestro/runs/${inputs.slug}/qa/report.md\n')
        self.assertEqual(run_layout.legacy_paths(text), [
            ("${inputs.stack}/reviews/findings.json", "reviews/code-${inputs.stack}.findings.json"),
            ("decision-log.json", "no longer written"),
            ("hld.md", "design/hld.md")])


class MigrationTest(unittest.TestCase):
    """A run from before the folders-by-kind layout (run_format 3)."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="run-layout-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_dir = os.path.join(self.root, ".maestro", "runs", "demo")
        r = ".maestro/runs/demo"
        self.write("requirement/prd.md", "# Demo — PRD\n\n- AC-01: it works.\n")
        self.write("hld.md", "# Demo — HLD\n")
        self.write("openapi.yaml", "openapi: 3.1.0\n")
        self.write("lld/api.md", "# Demo api — LLD\n")
        self.write("test-cases.md", "### TC-demo-001 — works\n\n- **Traces:** AC-01\n")
        self.write("lld-repos.json", {"schema_version": 3, "selected": ["api"]})
        self.write("lld/approval.json", {
            "schema_version": 1, "repos": ["api"], "light": False,
            "prd_sha256": sha(self.path("requirement/prd.md")),
            "hld_sha256": sha(self.path("hld.md")),
            "contract_sha256": sha(self.path("openapi.yaml")),
            "llds": {"api": sha(self.path("lld/api.md"))}})
        self.write("prd-context.json", {"schema_version": 2, "rounds": [], "decisions": [
            {"id": "retention", "topic": "retention", "title": "Retention",
             "proposal": "Keep 30 days", "answer": "Keep 30 days", "source": "assumption",
             "by": "autopilot", "why": "It sets the storage cost."},
            {"id": "owner", "topic": "owner", "title": "Owner", "proposal": "Billing",
             "answer": "Support owns it", "source": "user-answer"},
            {"id": "settled-format", "topic": "format", "title": "Format", "answer": "CSV",
             "source": "evidence", "evidence": f"{r}/hld.md#Interfaces"}]})
        self.write("prd-questions.json", {"schema_version": 2, "questions": [],
                                          "audit": {"unresolved": [], "contradictions": []}})
        self.write("decision-log.json", {"schema_version": 1, "entries": []})
        self.write("decision-log.md", "# Decision log\n\nstale\n")
        self.write("assumptions.md", "# Assumptions — demo\n")
        self.write("memory-snapshot.json", {"knowledge": {"codebase": "lesson"}})
        self.write("reviews/lld-readiness.md", "# Readiness\n")
        self.write("reviews/lld-readiness-findings.json", {"findings": [{"id": "LR-1"}]})
        self.write("reviews/lld-readiness-findings.previous.json", {"findings": [{"id": "LR-1"}]})
        self.write("reviews/.lld-readiness-snapshot/.maestro__runs__demo__lld__api.md",
                   "# Demo api — LLD (as last reviewed)\n")
        self.write("reviews/lld-readiness.diff", "First review\n")
        self.write("api/tasks.json", {"tasks": []})
        self.write("api/verify-logs/test.log", "ok\n")
        self.write("api/verify.json", {"passed": True, "commit": "c1", "checks": [
            {"name": "test", "status": "passed", "log": f"{r}/api/verify-logs/test.log"}]})
        self.write("api/reviews/summary.md", "# Code review\n")
        self.write("api/reviews/findings.json", {"findings": []})
        self.write("api/reviews/reviewed.json", {"commit": "c1", "blocking": False})
        self.write("api/reviews/code-review-findings.previous.json", {"findings": []})
        self.write("implementation-manifest.json", {"feature_slug": "demo", "repositories": [
            {"repo": "api", "commit": "c1", "verification": {
                "status": "verified", "receipt": f"{r}/api/verify.json",
                "receipt_sha256": sha(self.path("api/verify.json"))}}]})
        self.write("qa/tasks.json", {"tasks": ["a QA scenario plan, not a repository's"]})
        self.write("qa/report.md", "# QA\n")
        self.write("state.yaml.lock", "")
        self.write("state.yaml.replaced-20261113T045012Z", "version: 1\n")
        state = statemod.new_state("demo", ".maestro/workflows/sdlc-main.yaml", "0" * 64,
                                   {"slug": "demo"})
        state["run_format"] = 3
        state["memory"] = {"snapshot": "memory-snapshot.json", "sha256": "x"}
        state["gates"] = [{"step": "design/lld/lld_approval", "option": "approve",
                           "auto": "auto", "at": "2026-11-02T10:00:00Z"}]
        state["steps"] = {
            "design/hld/write_hld": {
                "status": "done", "attempts": 0, "visits": 1, "outputs": {},
                "artifact": [f"{r}/hld.md", f"{r}/open-questions.json"],
                "artifact_baseline": {f"{r}/hld.md": None}},
            "design/lld/lld_scope_init": {
                "status": "done", "attempts": 0, "visits": 1,
                "outputs": {"lld_paths_csv": f"{r}/lld/api.md,{r}/lld/web.md"}},
            "delivery/finalize_implementation": {
                "status": "done", "attempts": 0, "visits": 1, "outputs": {
                    "manifest_path": f"{r}/implementation-manifest.json",
                    "manifest_sha256": sha(self.path("implementation-manifest.json"))}},
            "delivery/qa/qa_run": {
                "status": "done", "attempts": 0, "visits": 1,
                "outputs": {"summary": f"Report at {r}/qa/report.md."},
                "artifact": [f"{r}/qa/report.md"]},
        }
        statemod.save("demo", state, self.root)

    def path(self, rel):
        return os.path.join(self.run_dir, *rel.split("/"))

    def write(self, rel, doc):
        full = self.path(rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(doc if isinstance(doc, str) else json.dumps(doc, indent=2))

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as fh:
            text = fh.read()
        return json.loads(text) if rel.endswith(".json") else text

    def files(self):
        return sorted(run_layout._files(self.run_dir))

    def migrate(self, **kwargs):
        with statemod.locked("demo", self.root):
            return run_layout.migrate("demo", self.root, **kwargs)

    def test_files_land_in_their_folders_and_duplicates_go(self):
        approved = {rel: sha(self.path(rel)) for rel in ("hld.md", "openapi.yaml", "lld/api.md")}
        report = self.migrate()
        self.assertTrue(report["migrated"])
        self.assertEqual(report["kept"], [])
        self.assertEqual(self.files(), [
            ".engine/ledgers/replaced-20261113T045012Z.yaml",
            ".engine/lld-approval.json",
            ".engine/lld-scope.json",
            ".engine/logs/verify/api/test.log",
            ".engine/memory-snapshot.json",
            ".engine/queues/prd.json",
            ".engine/reviews/code-api.baseline.json",
            ".engine/reviews/code-api.reviewed.json",
            ".engine/reviews/lld-readiness.baseline.json",
            ".engine/reviews/lld-readiness.diff",
            ".engine/state.lock",
            "build/api/tasks.json",
            "build/api/verify.json",
            "build/manifest.json",
            "decisions/decision-log.md",
            "decisions/prd.json",
            "design/hld.md",
            "design/lld/api.md",
            "design/openapi.yaml",
            "design/test-cases.md",
            "qa/report.md",
            "qa/tasks.json",            # QA's own plan is not a repository's task list
            "requirement/prd.md",
            "reviews/code-api.findings.json",
            "reviews/code-api.md",
            "reviews/lld-readiness.findings.json",
            "reviews/lld-readiness.md",
            "state.yaml",
        ])
        # the top of the run folder is the ledger and the folders, nothing else
        self.assertEqual(sorted(os.listdir(self.run_dir)), sorted(
            [".engine", "build", "decisions", "design", "qa", "requirement", "reviews",
             "state.yaml"]))
        # a document is moved, never rewritten
        self.assertEqual(sha(self.path("design/hld.md")), approved["hld.md"])
        self.assertEqual(sha(self.path("design/lld/api.md")), approved["lld/api.md"])

    def test_an_approved_design_is_still_approved(self):
        self.migrate()
        self.assertEqual(lld_set.selected("demo", self.root), ["api"])
        self.assertEqual(lld_set.stale_reasons("demo", self.root), [])

    def test_review_copies_become_one_baseline_keyed_by_the_new_paths(self):
        self.migrate()
        baseline = self.read(".engine/reviews/lld-readiness.baseline.json")
        self.assertEqual(baseline["files"], {
            ".maestro/runs/demo/design/lld/api.md": "# Demo api — LLD (as last reviewed)\n"})
        self.assertEqual(baseline["finding_ids"], ["LR-1"])
        self.assertEqual(self.read(".engine/reviews/code-api.baseline.json"),
                         {"schema_version": 1, "files": {}, "finding_ids": []})

    def test_ledger_and_engine_records_follow_the_files(self):
        self.migrate()
        state = statemod.load("demo", self.root)
        self.assertEqual(state["run_format"], statemod.RUN_FORMAT_VERSION)
        steps = state["steps"]
        r = ".maestro/runs/demo"
        self.assertEqual(steps["design/hld/write_hld"]["artifact"],
                         [f"{r}/design/hld.md", f"{r}/design/open-questions.json"])
        self.assertEqual(steps["design/hld/write_hld"]["artifact_baseline"],
                         {f"{r}/design/hld.md": None})
        self.assertEqual(steps["design/lld/lld_scope_init"]["outputs"]["lld_paths_csv"],
                         f"{r}/design/lld/api.md,{r}/design/lld/web.md")
        self.assertEqual(steps["delivery/qa/qa_run"]["outputs"]["summary"],
                         f"Report at {r}/qa/report.md.")  # unchanged paths stay as written
        self.assertEqual(state["memory"]["snapshot"], ".engine/memory-snapshot.json")
        # the receipt names its log's new place, the manifest the receipt's, and every recorded
        # hash is the hash of the file as it now is
        receipt = self.read("build/api/verify.json")
        self.assertEqual(receipt["checks"][0]["log"], f"{r}/.engine/logs/verify/api/test.log")
        entry = self.read("build/manifest.json")["repositories"][0]["verification"]
        self.assertEqual(entry["receipt"], f"{r}/build/api/verify.json")
        self.assertEqual(entry["receipt_sha256"], sha(self.path("build/api/verify.json")))
        finalize = steps["delivery/finalize_implementation"]["outputs"]
        self.assertEqual(finalize["manifest_path"], f"{r}/build/manifest.json")
        self.assertEqual(finalize["manifest_sha256"], sha(self.path("build/manifest.json")))
        # a settled decision's evidence points at the document's new place
        decisions = {d["id"]: d for d in self.read("decisions/prd.json")["decisions"]}
        self.assertEqual(decisions["settled-format"]["evidence"], f"{r}/design/hld.md#Interfaces")
        # an accepted recommendation is kept once; one the person overrode stays for context
        self.assertNotIn("proposal", decisions["retention"])
        self.assertEqual(decisions["owner"]["proposal"], "Billing")

    def test_decision_log_is_rendered_from_the_records_with_the_unconfirmed_first(self):
        self.migrate()
        log = self.read("decisions/decision-log.md")
        self.assertNotIn("stale", log)
        self.assertIn("Run mode: human. 1 assumption, 0 left open, 1 autopilot gate decision.", log)
        self.assertIn("- **PRD · Retention** (autopilot): Keep 30 days", log)
        self.assertIn("Why it matters: It sets the storage cost.", log)
        self.assertIn("- design/lld/lld_approval → approve (auto mode", log)
        self.assertIn("[settled by evidence]: CSV", log)

    def test_a_relative_workspace_root_works_like_an_absolute_one(self):
        """The CLI is run as `--root .` (or another relative folder)."""
        parent, name = os.path.split(self.root)
        cwd = os.getcwd()
        os.chdir(parent)
        self.addCleanup(os.chdir, cwd)
        with statemod.locked("demo", name):
            report = run_layout.migrate("demo", name)
        self.assertNotIn("decision_log", report)
        self.assertIn("Run mode: human.", self.read("decisions/decision-log.md"))
        self.assertEqual(sorted(os.listdir(self.root)), [".maestro"])  # nothing written astray

    def test_migrating_twice_changes_nothing(self):
        self.migrate()
        before = {rel: sha(self.path(rel)) for rel in self.files() if rel != "state.yaml"}
        again = self.migrate()
        self.assertFalse(again["migrated"])
        self.assertEqual({rel: sha(self.path(rel)) for rel in self.files()
                          if rel != "state.yaml"}, before)

    def test_dry_run_reports_and_touches_nothing(self):
        before = self.files()
        report = run_layout.migrate("demo", self.root, dry_run=True)
        self.assertIn(["hld.md", "design/hld.md"], report["moved"])
        self.assertIn("decision-log.json", report["removed"])
        self.assertEqual(self.files(), before)

    def test_a_file_whose_new_place_is_taken_is_left_alone(self):
        self.write("design/hld.md", "# written by hand\n")
        report = self.migrate()
        self.assertEqual(report["kept"], ["hld.md"])
        self.assertEqual(self.read("design/hld.md"), "# written by hand\n")
        self.assertTrue(os.path.isfile(self.path("hld.md")))

    # -- through the CLI ----------------------------------------------------------------------

    def ctl(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = maestroctl.main(["--root", self.root, *argv])
        return code, out.getvalue(), err.getvalue()

    def test_commands_refuse_an_unmigrated_run_and_migrate_fixes_it(self):
        code, _out, err = self.ctl("todo", "--slug", "demo")
        self.assertEqual(code, 3)
        self.assertIn("maestroctl migrate --slug demo", err)
        code, out, _err = self.ctl("migrate", "--slug", "demo", "--dry-run")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["migrated"])
        self.assertTrue(os.path.isfile(self.path("hld.md")))  # a dry run moved nothing
        code, out, _err = self.ctl("migrate", "--slug", "demo")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(self.path("design/hld.md")))
        self.assertEqual(statemod.load("demo", self.root)["run_format"],
                         statemod.RUN_FORMAT_VERSION)

    def test_starting_a_stage_on_an_old_feature_migrates_it_first(self):
        """`init --force` with a stage workflow on a feature designed before the layout: the
        old ledger is kept and the new run finds the approved documents."""
        workflow = os.path.join(self.root, "stage.yaml")
        with open(workflow, "w", encoding="utf-8") as fh:
            fh.write("nodes:\n  - id: work\n    instruction: Do the work.\n")
        code, out, _err = self.ctl("init", "--slug", "demo", "--workflow", "stage.yaml", "--force")
        self.assertEqual(code, 0, out)
        result = json.loads(out)
        self.assertIn("folders-by-kind layout", result["migrated"])
        self.assertTrue(os.path.isfile(self.path("design/hld.md")))
        self.assertEqual(lld_set.stale_reasons("demo", self.root), [])
        self.assertEqual(len(os.listdir(statemod.ledgers_dir("demo", self.root))), 2)


if __name__ == "__main__":
    unittest.main()
