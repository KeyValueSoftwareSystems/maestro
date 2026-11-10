"""Living docs checker, generators and extractors (format v2.3), on the CoFee payment-links fixture.

The fault tests are the v2.3 package's injected faults: each goes into a fresh copy of a passing
workspace, and the checker must report the named rule.
"""
import contextlib
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import living_docs  # noqa: E402

FIXTURE = os.path.join(HERE, "..", "..", "testdata", "living-docs", "workspace")
REPOS = ("cofee-backend", "cofee-payer-app", "cofee-admin-app")
T = "docs/technical/payment-links.md"
F = "docs/functional/payment-links.md"


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   check=True, capture_output=True, text=True)


def init_repo(path):
    git(path, "init", "-q")
    git(path, "add", "-A")
    git(path, "commit", "-qm", "init")


def build_workspace(target):
    """The fixture as a passing workspace: git repos, stamped, reviewed, generated, committed."""
    shutil.copytree(FIXTURE, target)
    for repo in REPOS:
        init_repo(os.path.join(target, "codebase", repo))
    living_docs.stamp(target)
    for rel in ("docs/architecture.md", F, T):
        path = os.path.join(target, rel)
        text = open(path).read().replace("status: draft", "status: verified")
        open(path, "w").write(text)
    report, _ = living_docs.run_check(target, write=True)
    assert not report.errors, report.errors
    for repo in REPOS:
        path = os.path.join(target, "codebase", repo)
        git(path, "add", "-A")
        git(path, "commit", "-qm", "generated facts block", "--allow-empty")


def edit(path, old, new, count=1):
    text = open(path).read()
    assert old in text, f"{old!r} not in {path}"
    open(path, "w").write(text.replace(old, new, count))


def rules(report):
    found = set()
    for line in report.errors:
        found.add("ERROR:" + line.split()[0])
    for line in report.warnings:
        found.add("WARN:" + line.split()[0])
    return found


class LivingDocsBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="living-docs-")
        cls.clean = os.path.join(cls.base, "clean")
        build_workspace(cls.clean)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def copy(self):
        target = tempfile.mkdtemp(prefix="ld-case-", dir=self.base)
        os.rmdir(target)
        shutil.copytree(self.clean, target, symlinks=True)
        return target

    def check(self, root, **kw):
        return living_docs.run_check(root, **kw)[0]


class CleanWorkspaceTest(LivingDocsBase):
    def test_clean_workspace_passes_without_warnings(self):
        report = self.check(self.clean)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_generated_inventory_matches_the_code(self):
        text = open(os.path.join(self.clean, "docs/_generated/payment-links.inventory.md")).read()
        self.assertIn("| POST /v1/links/{id}/disable | cofee-backend | cofee-backend · internal/links/"
                      "handler.go · Handler.Disable | cofee-admin-app · lib/api/links_api.dart · "
                      "disableLink | cofee-backend · api/openapi.yaml · disableLink |", text)
        self.assertIn("| link-expiry-sweep | cron 30 1 * * * | cofee-backend | cofee-backend · "
                      "internal/links/sweep.go · ExpirySweep.Run |", text)
        self.assertIn("| LINKS_EXPIRY_DAYS | 30 | cofee-backend | cofee-backend · internal/config/"
                      "links.go · Config.ExpiryDays |", text)
        self.assertIn("| payment_links | cofee-backend | cofee-backend · migrations/"
                      "0007_payment_links.sql · payment_links |", text)

    def test_facts_blocks_only_in_opted_in_repos_and_never_for_tests(self):
        links = open(os.path.join(self.clean, "codebase/cofee-backend/internal/links/CLAUDE.md")).read()
        self.assertIn("- PL-INV-001: An invoice has at most one active payment link", links)
        self.assertIn("- PL-CS-001: if you change this, also check:", links)
        pay = open(os.path.join(self.clean, "codebase/cofee-payer-app/lib/pay/CLAUDE.md")).read()
        self.assertIn("PL-INV-004", pay)
        admin = open(os.path.join(self.clean, "codebase/cofee-admin-app/CLAUDE.md")).read()
        self.assertNotIn("generated:facts", admin)

    def test_diagram_is_drawn_from_the_flows_table(self):
        text = open(os.path.join(self.clean, "docs/_generated/diagrams/architecture.mmd")).read()
        self.assertIn('Cashfree["Cashfree"] -->|webhook| cofee_backend["cofee-backend"]', text)

    def test_check_write_is_idempotent(self):
        root = self.copy()
        before = {p: open(os.path.join(root, p)).read() for p in (T, "docs/_index/code-to-facts.md")}
        self.check(root, write=True)
        for path, text in before.items():
            self.assertEqual(open(os.path.join(root, path)).read(), text)


class FaultInjectionTest(LivingDocsBase):
    """The v2.3 package's 17 faults; each must be caught by its rule."""

    def assert_caught(self, mutate, want, **kw):
        root = self.copy()
        mutate(root)
        found = rules(self.check(root, **kw))
        self.assertIn(want, found, f"{want} not in {found}")
        return found

    def test_retired_id_kind(self):
        self.assert_caught(lambda r: edit(os.path.join(r, T), "- Alert link-expiry-sweep-failed",
                                          "- PL-SIG-002: Alert link-expiry-sweep-failed"), "ERROR:R1")

    def test_duplicate_id(self):
        self.assert_caught(lambda r: edit(os.path.join(r, T), "| PL-INV-004 |", "| PL-INV-003 |"),
                           "ERROR:R1")

    def test_unpadded_id(self):
        self.assert_caught(lambda r: edit(os.path.join(r, T), "see PL-INV-001.", "see PL-INV-1."),
                           "ERROR:R1")

    def test_dangling_id_in_code(self):
        def mutate(root):
            with open(os.path.join(root, "codebase/cofee-backend/internal/links/link.go"), "a") as fh:
                fh.write("// PL-INV-009: one link per invoice\n")
        self.assert_caught(mutate, "ERROR:R2")

    def test_dangling_id_in_design(self):
        def mutate(root):
            os.makedirs(os.path.join(root, ".maestro/runs/fee-groups"))
            open(os.path.join(root, ".maestro/runs/fee-groups/hld.md"), "w").write("Respects PL-CS-007.\n")
        self.assert_caught(mutate, "ERROR:R2")

    def test_renamed_symbol(self):
        self.assert_caught(lambda r: edit(os.path.join(r, "codebase/cofee-backend/internal/links/link.go"),
                                          "ForInvoice", "LinkForInvoice", count=-1), "ERROR:R3")

    def test_hand_edited_inventory(self):
        self.assert_caught(lambda r: edit(os.path.join(r, "docs/_generated/payment-links.inventory.md"),
                                          "| 3 | cofee-backend", "| 5 | cofee-backend"), "ERROR:R4")

    def test_new_route_not_regenerated(self):
        self.assert_caught(lambda r: edit(os.path.join(r, "codebase/cofee-backend/internal/http/routes.go"),
                                          'r.Handle("GET /v1/links/{id}", l.Get)',
                                          'r.Handle("GET /v1/links/{id}", l.Get)\n\tr.Handle("POST /v1/links/{id}/resend", l.Get)'),
                           "ERROR:R4")

    def test_edited_facts_block(self):
        def mutate(root):
            path = os.path.join(root, "codebase/cofee-backend/internal/links/CLAUDE.md")
            text = re.sub(r"^- PL-INV-001: .*$", "- PL-INV-001: anything goes", open(path).read(), flags=re.M)
            open(path, "w").write(text)
        self.assert_caught(mutate, "ERROR:R4")

    def test_app_calls_dead_route(self):
        self.assert_caught(lambda r: edit(os.path.join(r, "codebase/cofee-admin-app/lib/api/links_api.dart"),
                                          "/disable", "/deactivate"), "ERROR:R6")

    def test_missing_required_section(self):
        def mutate(root):
            path = os.path.join(root, T)
            text = re.sub(r"## Change scenarios\n.*?(\n## )", r"\1", open(path).read(), flags=re.S)
            open(path, "w").write(text)
        self.assert_caught(mutate, "ERROR:R7")

    def test_section_not_in_format(self):
        self.assert_caught(lambda r: edit(os.path.join(r, T), "## Gotchas", "## Ownership"), "ERROR:R7")

    def test_unowned_unknown(self):
        self.assert_caught(lambda r: edit(os.path.join(r, T), "Unknown. (ask: data lead, since 2026-11-02)",
                                          "Unknown."), "ERROR:R7")

    def test_pronoun_row(self):
        self.assert_caught(lambda r: edit(os.path.join(r, F), "| Payer | A phone number",
                                          "| It | A phone number"), "ERROR:R7")

    def test_over_budget_warns(self):
        def mutate(root):
            with open(os.path.join(root, F), "a") as fh:
                for i in range(80):
                    fh.write(f"- Filler bullet about payment links that repeats what the code already says, line {i}\n")
        found = self.assert_caught(mutate, "WARN:R8")
        self.assertFalse(any(f.startswith("ERROR") for f in found), found)

    def _touch_anchored_file(self, root):
        repo = os.path.join(root, "codebase/cofee-backend")
        with open(os.path.join(repo, "internal/links/disable.go"), "a") as fh:
            fh.write("// tweak\n")
        git(repo, "commit", "-qam", "tweak")

    def test_stale_anchor_warns(self):
        found = self.assert_caught(self._touch_anchored_file, "WARN:R5")
        self.assertNotIn("ERROR:R5", found)

    def test_stale_anchor_fails_nightly_after_thirty_days(self):
        later = datetime.date.today() + datetime.timedelta(days=45)
        self.assert_caught(self._touch_anchored_file, "ERROR:R5", nightly=True, today=later)


class StructureTest(LivingDocsBase):
    def test_doc_without_front_matter_is_reported_not_a_crash(self):
        root = self.copy()
        path = os.path.join(root, F)
        text = open(path).read()
        open(path, "w").write(text.split("---\n", 2)[2])
        report = self.check(root)
        self.assertTrue(any("front-matter has no 'doc'" in e for e in report.errors), report.errors)

    def test_domain_doc_missing_from_domain_map(self):
        root = self.copy()
        for kind in ("functional", "technical"):
            src = open(os.path.join(root, f"docs/{kind}/payment-links.md")).read()
            open(os.path.join(root, f"docs/{kind}/reminders.md"), "w").write(
                src.replace("domain: payment-links", "domain: reminders").replace("id_prefix: PL", "id_prefix: RM")
                .replace("PL-", "RM-"))
        report = self.check(root)
        self.assertTrue(any("has no row in architecture's Domain map" in e for e in report.errors))

    def test_domain_needs_both_docs(self):
        root = self.copy()
        os.remove(os.path.join(root, F))
        report = self.check(root)
        self.assertTrue(any("has no functional doc" in e for e in report.errors), report.errors)

    def test_wrong_table_columns(self):
        root = self.copy()
        edit(os.path.join(root, F), "| ID | Rule | Edge | Why / source |", "| ID | Rule | Why / source |")
        report = self.check(root)
        self.assertTrue(any("use the columns ID | Rule | Edge | Why / source" in e for e in report.errors))

    def test_id_defined_in_the_wrong_doc_kind(self):
        root = self.copy()
        edit(os.path.join(root, T), "| PL-INV-004 |", "| PL-BR-009 |")
        report = self.check(root)
        self.assertTrue(any("defined in the wrong place" in e for e in report.errors), report.errors)

    def test_retired_row_stays_defined_but_leaves_facts_blocks(self):
        root = self.copy()
        path = os.path.join(root, T)
        text = re.sub(r"^\| PL-INV-002 \| [^|]*\|", "| PL-INV-002 | Retired 2026-11-10: merged into PL-INV-001. |",
                      open(path).read(), flags=re.M)
        open(path, "w").write(text)
        report, _ = living_docs.run_check(root, write=True)
        self.assertFalse([e for e in report.errors if e.startswith("R2")])
        links = open(os.path.join(root, "codebase/cofee-backend/internal/links/CLAUDE.md")).read()
        self.assertNotIn("PL-INV-002", links)

    def test_unknown_repo_in_front_matter(self):
        root = self.copy()
        edit(os.path.join(root, F), "repos: [cofee-backend,", "repos: [cofee-billing, cofee-backend,")
        report = self.check(root)
        self.assertTrue(any("cofee-billing" in e for e in report.errors), report.errors)


class CommandsTest(LivingDocsBase):
    def test_snippet_reads_a_row_on_its_own(self):
        defs = living_docs.collect_ids(living_docs.load_docs(self.clean), living_docs.Report())
        text = living_docs.snippet(defs, "PL-INV-001")
        self.assertTrue(text.startswith("PL-INV-001 (technical/payment-links.md · Invariants and consistency)"))
        self.assertIn("Enforces: PL-BR-001", text)

    def test_cited_writes_only_the_cited_rows(self):
        root = self.copy()
        lld = os.path.join(root, "lld.md")
        open(lld, "w").write("Keep PL-INV-001 and PL-CS-002. Unrelated: AC-01.\n")
        out = os.path.join(root, "facts.md")
        found, _ = living_docs.cited(root, [lld])
        self.assertEqual(found, ["PL-INV-001", "PL-CS-002"])
        with contextlib.redirect_stdout(io.StringIO()):
            rc = living_docs.main(["cited", "--root", root, "--from", lld, "--out", out])
        self.assertEqual(rc, 0)
        text = open(out).read()
        self.assertIn("- PL-CS-002 (technical/payment-links.md · Change scenarios)", text)
        self.assertNotIn("PL-BR-003", text)

    def test_domains_by_repo(self):
        rows = living_docs.domains_for(self.clean, ["cofee-admin-app"])
        self.assertEqual([r["domain"] for r in rows], ["payment-links"])
        self.assertEqual(living_docs.domains_for(self.clean, ["unknown"]), [])

    def test_stamp_marks_only_changed_docs_and_sets_draft(self):
        root = self.copy()
        snap = os.path.join(root, "snap.json")
        with contextlib.redirect_stdout(io.StringIO()):
            living_docs.main(["snapshot", "--root", root, "--out", snap])
        edit(os.path.join(root, F), "Out of scope: invoice amounts", "Out of scope: invoice totals")
        repo = os.path.join(root, "codebase/cofee-backend")
        with open(os.path.join(repo, "README.md"), "w") as fh:
            fh.write("x\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "new head")
        stamped = living_docs.stamp(root, snap)
        self.assertEqual(stamped, ["functional/payment-links.md"])
        doc = living_docs.Doc(os.path.join(root, F), root, "functional")
        self.assertEqual(doc.fm["status"], "draft")
        self.assertEqual(doc.fm["verified_at"]["cofee-backend"], living_docs._head(repo))
        tech = living_docs.Doc(os.path.join(root, T), root, "technical")
        self.assertEqual(tech.fm["status"], "verified")

    def test_only_generated_changes_detects_managed_edits(self):
        root = self.copy()
        repo = os.path.join(root, "codebase/cofee-backend")
        path = os.path.join(repo, "internal/links/CLAUDE.md")
        edit(path, "- PL-INV-002:", "- PL-INV-002 (regenerated):")
        self.assertTrue(living_docs.only_generated_changes(repo, "internal/links/CLAUDE.md"))
        edit(path, "Read docs/functional", "Please read docs/functional")
        self.assertFalse(living_docs.only_generated_changes(repo, "internal/links/CLAUDE.md"))

    def test_check_report_mode_ends_with_json(self):
        root = self.copy()
        edit(os.path.join(root, T), "## Gotchas", "## Ownership")
        proc = subprocess.run([sys.executable, os.path.join(HERE, "..", "living_docs.py"), "check",
                               "--root", root, "--report"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertFalse(payload["valid"])
        self.assertIn("R7", payload["issues_summary"])


class IntegrationTest(LivingDocsBase):
    def test_workspace_sync_treats_a_facts_only_change_as_managed(self):
        import workspace_sync
        root = self.copy()
        repo = os.path.join(root, "codebase/cofee-backend")
        path = os.path.join(repo, "internal/links/CLAUDE.md")
        edit(path, "- PL-INV-002:", "- PL-INV-002 (regenerated):")
        self.assertEqual(workspace_sync._dirty_paths(repo), [])
        edit(path, "Read docs/functional", "Please read docs/functional")
        self.assertEqual(workspace_sync._dirty_paths(repo), ["internal/links/CLAUDE.md"])

    def test_project_config_checks_the_docs_section(self):
        import project_config
        config = project_config.load(self.clean)
        self.assertFalse([i for i in project_config.check(config, list(REPOS)) if i.level == "error"])
        config["docs"] = {"facts_blocks": "cofee-backend", "extract": [
            {"kind": "route", "pattern": "Handle\\((?P<verb>\\w+)"},
            {"kind": "queue", "pattern": "x"}, {"kind": "call", "pattern": "(", "glob": "*.go"}],
            "budget": 1}
        messages = [i.msg for i in project_config.check(config, list(REPOS))]
        self.assertTrue(any("list of repository names" in m for m in messages), messages)
        self.assertTrue(any("needs a named group (?P<path>" in m for m in messages), messages)
        self.assertTrue(any("kind must be one of" in m for m in messages), messages)
        self.assertTrue(any("does not compile" in m for m in messages), messages)
        self.assertTrue(any("unknown key `budget`" in m for m in messages), messages)


class TeamOwnedTest(LivingDocsBase):
    """Invariants and change scenarios belong to the team: a writer step cannot change them."""

    def snapshot(self, root):
        return living_docs.team_snapshot(root)

    def test_writer_edit_to_a_team_section_fails_and_is_restored(self):
        root = self.copy()
        snap = self.snapshot(root)
        path = os.path.join(root, T)
        before = open(path).read()
        edit(path, "| PL-INV-001 | An invoice has at most one active payment link",
             "| PL-INV-001 | An invoice has any number of payment links")
        report, _ = living_docs.run_check(root, write=True, locked_from=snap)
        self.assertTrue(any(e.startswith("R9 technical/payment-links.md §Invariants and consistency")
                            for e in report.errors), report.errors)
        self.assertEqual(open(path).read(), before)

    def test_writer_may_not_add_rules_to_a_new_doc(self):
        root = self.copy()
        snap = self.snapshot(root)
        living_docs.write_minimal_docs(os.path.join(root, "scratch"), "reminders", ["cofee-backend"])
        for kind in ("functional", "technical"):
            text = open(os.path.join(root, f"scratch/docs/{kind}/reminders.md")).read()
            text = text.replace("id_prefix: DM", "id_prefix: RM").replace("DM-", "RM-")
            text = text.replace("cofee-backend/src", "cofee-backend/internal/links")
            if kind == "technical":
                text = text.replace("## Invariants and consistency\nNone.",
                                    "## Invariants and consistency\n| ID | Invariant | Enforces | Where (repo · path · symbol) | Consistency | Tested by |\n| --- | --- | --- | --- | --- | --- |\n| RM-INV-001 | Reminders stop when a link is disabled. | RM-BR-001 | cofee-backend · internal/links/disable.go · Service.Disable | eventual | Unknown. (ask: team, since 2026-11-10) |")
            open(os.path.join(root, f"docs/{kind}/reminders.md"), "w").write(text)
        report, _ = living_docs.run_check(root, write=True, locked_from=snap)
        self.assertTrue(any(e.startswith("R9 technical/reminders.md") for e in report.errors), report.errors)
        self.assertNotIn("RM-INV-001", open(os.path.join(root, "docs/technical/reminders.md")).read())

    def test_writer_may_not_touch_side_effects(self):
        root = self.copy()
        snap = self.snapshot(root)
        path = os.path.join(root, "docs/impact/side-effects.yaml")
        before = open(path).read()
        edit(path, "summary: Disabling a payment link", "summary: Anything")
        report, _ = living_docs.run_check(root, write=True, locked_from=snap)
        self.assertTrue(any(e.startswith("R9 docs/impact/side-effects.yaml") for e in report.errors))
        self.assertEqual(open(path).read(), before)

    def test_team_problems_are_warnings_in_a_writer_check(self):
        root = self.copy()
        edit(os.path.join(root, "codebase/cofee-backend/internal/links/link_test.go"),
             "TestForInvoiceReusesActiveLink", "TestReuse")
        plain = self.check(root)
        self.assertTrue(any(e.startswith("R3") for e in plain.errors), plain.errors)
        locked = living_docs.run_check(root, locked_from=self.snapshot(root))[0]
        self.assertFalse([e for e in locked.errors if e.startswith("R3")], locked.errors)
        self.assertTrue(any("team-owned; the team should" in w for w in locked.warnings))

    def test_proposals_take_no_id_and_a_known_kind(self):
        root = self.copy()
        edit(os.path.join(root, T), "| invariant | A payment link's expiry",
             "| PL-INV-009 | A payment link's expiry")
        report = self.check(root)
        self.assertTrue(any("gives a proposal an ID" in e or "proposal kind" in e for e in report.errors),
                        report.errors)

    def test_invariant_not_cited_in_code_warns(self):
        root = self.copy()
        edit(os.path.join(root, "codebase/cofee-backend/internal/webhooks/cashfree.go"),
             "// PL-INV-003: apply each Cashfree event id at most once.\n", "")
        report = self.check(root)
        self.assertTrue(any("PL-INV-003 is cited in no code or test" in w for w in report.warnings))

    def test_side_effects_names_rules_and_rows_are_checked(self):
        root = self.copy()
        path = os.path.join(root, "docs/impact/side-effects.yaml")
        edit(path, "queues: [link.disabled]", "queues: [link.removed]")
        edit(path, "rules: [PL-INV-001]", "rules: [PL-INV-099]")
        report = self.check(root)
        self.assertTrue(any("queue 'link.removed' no longer appears" in e for e in report.errors), report.errors)
        self.assertTrue(any("cites rule PL-INV-099" in e for e in report.errors), report.errors)

    def test_status_rules_scaffold_next(self):
        root = self.copy()
        status = living_docs.rules_status(root)
        self.assertEqual((status["present"], status["rule_count"], status["scenario_count"]), (True, 6, 3))
        result = living_docs.rules_check(root)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(living_docs.next_ids(root, "PL"),
                         {"br": "PL-BR-005", "inv": "PL-INV-005", "cs": "PL-CS-004"})
        self.assertEqual(living_docs.scaffold_side_effects(root)["created"], False)
        empty = tempfile.mkdtemp(dir=self.base)
        self.assertTrue(living_docs.scaffold_side_effects(empty)["created"])
        self.assertFalse(living_docs.rules_status(empty)["present"])

    def test_rules_reads_the_feature_worktree(self):
        root = self.copy()
        worktree = os.path.join(self.base, "wt-" + os.path.basename(root))
        shutil.copytree(os.path.join(root, "codebase/cofee-backend"), worktree, symlinks=True)
        edit(os.path.join(worktree, "internal/links/disable.go"), "func (s *Service) Disable",
             "func (s *Service) Deactivate")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            living_docs.main(["rules", "--root", root, "--repo", "cofee-backend", "--worktree", worktree])
        result = json.loads(out.getvalue().strip())
        self.assertFalse(result["valid"])
        self.assertIn("Disable", result["issues_summary"])
        self.assertTrue(living_docs.rules_check(root)["valid"])


class ExtractorTest(unittest.TestCase):
    def repo(self, files):
        root = tempfile.mkdtemp(prefix="ld-extract-")
        self.addCleanup(shutil.rmtree, root, True)
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").write(text)
        init_repo(root)
        return root

    def test_python_routes_calls_and_config(self):
        api = self.repo({
            "app/routes.py": "import os\nTIMEOUT = os.getenv(\"API_TIMEOUT\", \"30\")\n\n"
                             "@router.get(\"/v1/orders/{order_id}\")\nasync def get_order(order_id):\n    return 1\n",
        })
        client = self.repo({
            "client/orders.py": "class OrdersClient:\n    def fetch(self, oid):\n"
                                "        return requests.get(f\"{BASE}/v1/orders/{oid}\")\n",
        })
        inv = living_docs.extract({"api": api, "client": client})
        self.assertEqual([(r["method"], r["path"], r["anchor"]) for r in inv.routes],
                         [("GET", "/v1/orders/{order_id}", "api · app/routes.py · get_order")])
        self.assertEqual(inv.calls[0]["anchor"], "client · client/orders.py · OrdersClient.fetch")
        self.assertIs(living_docs.serving_route(inv, inv.calls[0]), inv.routes[0])
        self.assertEqual(inv.config[("api", "API_TIMEOUT")]["default"], "30")

    def test_express_route_and_axios_call_with_base_prefix(self):
        api = self.repo({"src/server.js": "router.post('/orders/:id/cancel', cancelOrder);\n"
                                          "function cancelOrder(req, res) {}\n"})
        web = self.repo({"src/api.ts": "export async function cancel(id) {\n"
                                       "  return axios.post(`/api/orders/${id}/cancel`);\n}\n"})
        inv = living_docs.extract({"api": api, "web": web})
        self.assertEqual(inv.routes[0]["anchor"], "api · src/server.js · cancelOrder")
        route = living_docs.serving_route(inv, inv.calls[0])
        self.assertIsNotNone(route)
        self.assertEqual(inv.calls[0]["anchor"], "web · src/api.ts · cancel")

    def test_spring_mapping(self):
        api = self.repo({"src/main/java/OrderController.java":
                         "class OrderController {\n  @GetMapping(\"/orders/{id}\")\n"
                         "  public Order getOrder(@PathVariable String id) {\n    return null;\n  }\n}\n"})
        inv = living_docs.extract({"api": api})
        self.assertEqual(inv.routes[0]["anchor"], "api · src/main/java/OrderController.java · getOrder")

    def test_contracts_openapi_block_style_asyncapi_sql_env_and_cronjob(self):
        repo = self.repo({
            "api/openapi.yaml": "openapi: 3.0.0\npaths:\n  /orders/{id}:\n    get:\n"
                                "      operationId: getOrder\n    delete:\n      operationId: deleteOrder\n",
            "api/asyncapi.yaml": "asyncapi: 3.0.0\nchannels:\n  orderCreated:\n    address: order.created\n"
                                 "operations:\n  publishOrderCreated:\n    action: send\n"
                                 "    channel: {$ref: '#/channels/orderCreated'}\n",
            "db/001_init.sql": "CREATE TABLE IF NOT EXISTS public.orders (id int);\n",
            ".env.example": "ORDERS_PAGE_SIZE=50\nSTRIPE_SECRET_KEY=sk_live_x\n",
            "deploy/cron.yaml": "apiVersion: batch/v1\nkind: CronJob\nmetadata:\n  name: order-cleanup\n"
                                "spec:\n  schedule: \"0 3 * * *\"\n",
        })
        inv = living_docs.extract({"orders": repo})
        self.assertEqual(sorted((o["method"], o["op"]) for o in inv.ops),
                         [("DELETE", "deleteOrder"), ("GET", "getOrder")])
        self.assertEqual(living_docs.event_rows(inv)[0]["producers"],
                         ["orders · api/asyncapi.yaml · publishOrderCreated"])
        self.assertEqual(inv.tables[0]["anchor"], "orders · db/001_init.sql · orders")
        self.assertEqual(inv.config[("orders", "ORDERS_PAGE_SIZE")]["default"], "50")
        self.assertEqual(inv.config[("orders", "STRIPE_SECRET_KEY")]["default"], "(secret)")
        self.assertEqual(inv.jobs[0]["trigger"], "cron 0 3 * * *")
        rows = living_docs.api_rows(inv)
        self.assertEqual([r["handler"] for r in rows], [None, None])

    def test_custom_pattern_from_config(self):
        repo = self.repo({"lib/bus.ex": "Bus.emit(\"invoice.paid\", payload)\n"})
        inv = living_docs.extract({"billing": repo}, [
            {"kind": "event_out", "glob": "lib/*.ex", "pattern": r'Bus\.emit\("(?P<name>[\w.]+)"'}])
        self.assertEqual([e["name"] for e in inv.events], ["invoice.paid"])


if __name__ == "__main__":
    unittest.main()
