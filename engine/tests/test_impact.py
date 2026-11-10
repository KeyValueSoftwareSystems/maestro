"""impact: the engine checks the assessment names real repositories and states every flag."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import impact  # noqa: E402


class ImpactTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="impact-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for name in ("backend", "web"):
            path = os.path.join(self.root, "codebase", name)
            os.makedirs(path)
            subprocess.run(["git", "init", "-q", path], check=True)
        self.path = os.path.join(self.root, "impact.json")

    def check(self, doc):
        with open(self.path, "w") as fh:
            fh.write(doc if isinstance(doc, str) else json.dumps(doc))
        return impact.validate(self.root, self.path)

    def doc(self, repos, **flags):
        return {"schema_version": 1, "repos": repos, "interfaces_change": True,
                "data_migration": False, "infrastructure_change": False, "size": "major", **flags}

    def test_valid_assessment_names_repos_and_boundaries(self):
        result = self.check(self.doc([{"name": "Backend", "change": "store transfers"},
                                      {"name": "web", "change": "transfer screen"}]))
        self.assertTrue(result["valid"])
        self.assertEqual((result["repos_csv"], result["count"]), ("backend,web", 2))
        self.assertIn("interfaces between repositories", result["summary"])

    def test_size_must_be_minor_or_major(self):
        ok = self.check(self.doc([{"name": "web", "change": "x"}], size="Minor"))
        self.assertEqual((ok["valid"], ok["size"]), (True, "minor"))
        for bad in ("", "huge", None):
            result = self.check(self.doc([{"name": "web", "change": "x"}], size=bad))
            self.assertFalse(result["valid"])
            self.assertIn("size must be minor or major", result["issues_summary"])

    def test_unknown_repo_missing_change_or_flag_is_invalid(self):
        cases = [
            (self.doc([{"name": "mobile", "change": "x"}]), "'mobile' is not a repository"),
            (self.doc([{"name": "web", "change": ""}]), "must say what changes in web"),
            (self.doc([]), "at least one repository"),
            ({"repos": [{"name": "web", "change": "x"}]}, "interfaces_change must be true or false"),
            ("not json", "not readable JSON"),
        ]
        for doc, issue in cases:
            with self.subTest(issue=issue):
                result = self.check(doc)
                self.assertFalse(result["valid"])
                self.assertIn(issue, result["issues_summary"])

    def test_v2_items_need_reason_evidence_and_defined_ids(self):
        os.makedirs(os.path.join(self.root, "docs", "technical"))
        with open(os.path.join(self.root, "docs", "technical", "payments.md"), "w") as fh:
            fh.write("---\ndoc: technical\ndomain: payments\nid_prefix: PL\n---\n## Invariants and consistency\n| ID | Invariant |\n| --- | --- |\n| PL-INV-001 | One active link per invoice. |\n")
        ok = {"name": "payment_links", "reason": "new column", "evidence": "docs/codebase-map.md"}
        good = self.check(self.doc([{"name": "web", "change": "x"}], schema_version=2, tables=[ok],
                                   rules=[{"id": "PL-INV-001", "reason": "r", "evidence": "e"}]))
        self.assertEqual((good["valid"], good["item_count"]), (True, 2), good["issues_summary"])
        cases = [
            ({"tables": [{"name": "t", "evidence": "e"}]}, "reason is required"),
            ({"rules": [{"id": "PL-INV-009", "reason": "r", "evidence": "e"}]}, "not defined"),
            ({"rules": [{"id": "PL-1", "reason": "r", "evidence": "e"}]}, "not a <PREFIX>-INV-NNN"),
            ({"scenarios": [{"id": "PL-CS-001", "reason": "r", "evidence": "e"}]}, "not defined in the living docs"),
            ({"domains": [{"name": "billing", "reason": "r", "evidence": "e"}]}, "'billing' has no docs/functional"),
        ]
        for extra, issue in cases:
            with self.subTest(issue=issue):
                result = self.check(self.doc([{"name": "web", "change": "x"}], schema_version=2, **extra))
                self.assertFalse(result["valid"])
                self.assertIn(issue, result["issues_summary"])

    def test_prd_triggers_scenario_merge(self):
        os.makedirs(os.path.join(self.root, "docs", "impact"))
        os.makedirs(os.path.join(self.root, "docs", "technical"))
        with open(os.path.join(self.root, "docs", "technical", "payments.md"), "w") as fh:
            fh.write("---\ndoc: technical\ndomain: payments\nid_prefix: PL\n---\n## Invariants and consistency\n| ID | Invariant |\n| --- | --- |\n| PL-INV-001 | One active link per invoice. |\n")
        with open(os.path.join(self.root, "docs", "impact", "side-effects.yaml"), "w") as fh:
            fh.write("version: 1\nscenarios:\n  - id: PL-CS-001\n    summary: Disabling a link\n"
                     "    rules: [PL-INV-001]\n    when_changing: [links.Service.Disable]\n"
                     "    also_impacts:\n      tables: [payment_links]\n")
        prd = os.path.join(self.root, "prd.md")
        with open(prd, "w") as fh:
            fh.write("Admins can call links.Service.Disable from the new screen.\n")
        self.check(self.doc([{"name": "web", "change": "x"}]))
        result = impact.validate(self.root, self.path, prd)
        self.assertTrue(result["valid"], result["issues_summary"])
        self.assertEqual(result["scenarios_csv"], "PL-CS-001")
        self.assertIn("engine added scenario PL-CS-001", result["summary"])
        with open(self.path) as fh:
            doc = json.load(fh)
        self.assertEqual(doc["schema_version"], 2)
        self.assertEqual([t["name"] for t in doc["tables"]], ["payment_links"])
        self.assertEqual(impact.validate(self.root, self.path, prd)["item_count"], 3)  # idempotent


if __name__ == "__main__":
    unittest.main()
