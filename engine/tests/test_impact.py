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


if __name__ == "__main__":
    unittest.main()
