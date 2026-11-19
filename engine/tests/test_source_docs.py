#!/usr/bin/env python3
"""source_docs.py: the team's own documents are never rewritten by a docs writer, additions are
kept, rewrites and reported conflicts go to a person, and only an approved proposal is applied."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, ENGINE)
import source_docs  # noqa: E402

DOMAIN = "---\ndoc: domain\ndomain: payments\n---\n# Payments\n"
ARCH = "---\ndoc: architecture\n---\n# Architecture\n"
SPEC = "# Refund policy\n\nRefunds are allowed within 30 days.\nPartial refunds need approval.\n"


class SourceDocsTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.snap = os.path.join(self.root, ".maestro", "runs", "r", ".engine", "knowledge", "sources")
        self.write("docs/architecture.md", ARCH)
        self.write("docs/payments.md", DOMAIN)
        self.write("docs/architecture.mmd", "graph TD\n")
        self.write("docs/codebase-maps/api.md", "# api\n")
        self.write("docs/impact/side-effects.yaml", "scenarios: []\n")
        self.write("docs/product/refunds.md", SPEC)
        self.write("docs/notes.md", "# Team notes\n")

    def tearDown(self):
        shutil.rmtree(self.root)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def read(self, rel):
        with open(os.path.join(self.root, rel), encoding="utf-8") as fh:
            return fh.read()

    def guard(self, conflicts=None):
        return source_docs.guard(self.root, self.snap, conflicts, "decisions/source-conflicts.md")

    def test_sources_are_every_file_maestro_does_not_write(self):
        self.assertEqual(source_docs.source_paths(self.root),
                         ["docs/notes.md", "docs/product/refunds.md"])

    def test_configured_sources_outside_docs(self):
        self.write("specs/billing.md", "# Billing\n")
        self.write("maestro.config.yaml", "docs:\n  sources: [\"specs/**\"]\n")
        self.assertIn("specs/billing.md", source_docs.source_paths(self.root))

    def test_untouched_sources_give_no_conflicts(self):
        source_docs.snapshot(self.root, self.snap)
        out = self.guard()
        self.assertTrue(out["valid"])
        self.assertFalse(out["has_source_conflicts"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "decisions/source-conflicts.md")))

    def test_an_addition_is_kept(self):
        source_docs.snapshot(self.root, self.snap)
        added = SPEC.replace("Partial", "See docs/payments.md (PAY-BR-002).\nPartial")
        self.write("docs/product/refunds.md", added)
        out = self.guard()
        self.assertEqual(self.read("docs/product/refunds.md"), added)
        self.assertEqual(out["source_additions"], 1)
        self.assertFalse(out["has_source_conflicts"])

    def test_a_rewrite_is_put_back_and_kept_as_a_proposal(self):
        source_docs.snapshot(self.root, self.snap)
        self.write("docs/product/refunds.md", SPEC.replace("30 days", "14 days"))
        out = self.guard()
        self.assertTrue(out["valid"])
        self.assertTrue(out["has_source_conflicts"])
        self.assertEqual(self.read("docs/product/refunds.md"), SPEC)
        report = self.read("decisions/source-conflicts.md")
        self.assertIn("-Refunds are allowed within 30 days.", report)
        self.assertIn("+Refunds are allowed within 14 days.", report)
        review = source_docs.review(self.snap)
        self.assertTrue(review["has_source_conflicts"])
        self.assertIn("docs/product/refunds.md", review["summary"])

    def test_a_proposal_survives_a_later_hand_off(self):
        """The check list runs again after a failed living-docs check: the first rewrite was
        already put back, so the proposal must not be lost."""
        source_docs.snapshot(self.root, self.snap)
        self.write("docs/product/refunds.md", "# replaced\n")
        self.guard()
        out = self.guard()
        self.assertEqual(out["source_proposals"], 1)

    def test_a_deleted_source_comes_back(self):
        source_docs.snapshot(self.root, self.snap)
        os.remove(os.path.join(self.root, "docs/notes.md"))
        out = self.guard()
        self.assertEqual(self.read("docs/notes.md"), "# Team notes\n")
        self.assertTrue(out["has_source_conflicts"])

    def test_a_binary_source_is_never_changed(self):
        with open(os.path.join(self.root, "docs/spec.pdf"), "wb") as fh:
            fh.write(b"%PDF\0original")
        source_docs.snapshot(self.root, self.snap)
        with open(os.path.join(self.root, "docs/spec.pdf"), "wb") as fh:
            fh.write(b"%PDF\0original plus")
        out = self.guard()
        with open(os.path.join(self.root, "docs/spec.pdf"), "rb") as fh:
            self.assertEqual(fh.read(), b"%PDF\0original")
        self.assertTrue(out["has_source_conflicts"])

    def test_reported_conflicts_are_checked_and_listed(self):
        source_docs.snapshot(self.root, self.snap)
        path = os.path.join(self.root, "conflicts.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"conflicts": [{"source": "docs/product/refunds.md",
                                      "source_says": "refunds within 30 days",
                                      "code_says": "the API allows 60 days",
                                      "evidence": "api · refunds/window.go · MaxRefundAge",
                                      "doc": "docs/payments.md"}]}, fh)
        out = self.guard(path)
        self.assertTrue(out["valid"])
        self.assertEqual(out["source_conflicts"], 1)
        self.assertIn("the API allows 60 days", self.read("decisions/source-conflicts.md"))

    def test_a_conflict_must_name_a_source_doc(self):
        source_docs.snapshot(self.root, self.snap)
        path = os.path.join(self.root, "conflicts.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"conflicts": [{"source": "docs/payments.md", "source_says": "a",
                                      "code_says": "b", "evidence": "c"}]}, fh)
        out = self.guard(path)
        self.assertFalse(out["valid"])
        self.assertIn("not one of the team's source docs", out["issues_summary"])

    def test_a_new_stray_file_under_docs_is_refused(self):
        source_docs.snapshot(self.root, self.snap)
        self.write("docs/payments-extra.md", "# more\n")
        self.write("docs/orders.md", DOMAIN.replace("payments", "orders"))
        out = self.guard()
        self.assertFalse(out["valid"])
        self.assertIn("docs/payments-extra.md", out["issues_summary"])
        self.assertNotIn("docs/orders.md", out["issues_summary"])

    def test_apply_writes_only_proposals_whose_source_is_unchanged(self):
        source_docs.snapshot(self.root, self.snap)
        self.write("docs/product/refunds.md", "# refunds v2\n")
        self.write("docs/notes.md", "# notes v2\n")
        self.guard()
        self.write("docs/notes.md", "# a person edited this meanwhile\n")
        out = source_docs.apply(self.root, self.snap)
        self.assertEqual((out["applied"], out["skipped"]), (1, 1))
        self.assertEqual(self.read("docs/product/refunds.md"), "# refunds v2\n")
        self.assertEqual(self.read("docs/notes.md"), "# a person edited this meanwhile\n")

    def test_a_team_architecture_doc_stops_the_first_build(self):
        self.write("docs/architecture.md", "# Our architecture\n")
        with self.assertRaises(SystemExit) as caught:
            source_docs.snapshot(self.root, self.snap)
        self.assertIn("docs/product/architecture.md", str(caught.exception))

    def test_an_old_maestro_architecture_doc_is_not_a_source(self):
        self.write("docs/architecture.md", "# Architecture (format 2)\n")
        self.write("docs/provenance.yaml", "schema_version: 1\n")
        self.assertNotIn("docs/architecture.md", source_docs.source_paths(self.root))

    def test_snapshot_copies_are_git_ignored(self):
        source_docs.snapshot(self.root, self.snap)
        with open(os.path.join(self.snap, ".gitignore"), encoding="utf-8") as fh:
            self.assertIn("*", fh.read().split())

    def test_cli(self):
        script = os.path.join(ENGINE, "source_docs.py")
        run = lambda *a: json.loads(subprocess.run(  # noqa: E731
            [sys.executable, script, *a, "--root", self.root], capture_output=True, text=True,
            check=True).stdout)
        self.assertEqual(run("list")["count"], 2)
        snap = ".maestro/runs/r/.engine/knowledge/sources"
        self.assertEqual(run("snapshot", "--out", snap)["count"], 2)
        self.write("docs/notes.md", "# changed\n")
        out = run("guard", "--snapshot", snap, "--report", "decisions/source-conflicts.md")
        self.assertTrue(out["has_source_conflicts"])
        self.assertEqual(self.read("docs/notes.md"), "# Team notes\n")
        self.assertTrue(run("review", "--snapshot", snap)["has_source_conflicts"])
        self.assertEqual(run("apply", "--snapshot", snap)["applied"], 1)
        self.assertEqual(self.read("docs/notes.md"), "# changed\n")


if __name__ == "__main__":
    unittest.main()
