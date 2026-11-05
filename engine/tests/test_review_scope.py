"""review_scope: a re-review gets the changes since its last round and that round's findings."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import review_scope  # noqa: E402


class ReviewScopeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="review-scope-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.reviews = os.path.join(self.dir, "reviews")
        self.doc = os.path.join(self.dir, "lld-backend.md")
        self.findings = os.path.join(self.reviews, "findings.json")

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def prepare(self):
        return review_scope.prepare(self.reviews, "lld", [self.doc], self.findings)

    def diff(self, result):
        with open(result["diff_path"]) as fh:
            return fh.read()

    def test_first_round_then_only_the_changes(self):
        self.write(self.doc, "# LLD\n\nretry: none\n")
        first = self.prepare()
        self.assertEqual((first["rereview"], first["previous_findings"]), (False, ""))
        self.assertIn("First review", self.diff(first))
        self.write(self.findings, json.dumps({"findings": [{"id": "LR-1"}]}))
        self.write(self.doc, "# LLD\n\nretry: once, after 5 s\n")
        second = self.prepare()
        self.assertTrue(second["rereview"])
        self.assertEqual(second["changed_csv"], self.doc)
        text = self.diff(second)
        self.assertIn("-retry: none", text)
        self.assertIn("+retry: once, after 5 s", text)
        with open(second["previous_findings"]) as fh:
            self.assertEqual(json.load(fh)["findings"][0]["id"], "LR-1")
        third = self.prepare()  # nothing changed since the second round
        self.assertEqual(third["changed_csv"], "")
        self.assertIn("No changes", self.diff(third))

    def test_code_review_keeps_only_the_previous_findings(self):
        result = review_scope.prepare(self.reviews, "code-review", [], self.findings)
        self.assertEqual((result["rereview"], result["diff_path"]), (False, ""))
        self.write(self.findings, json.dumps({"findings": []}))
        result = review_scope.prepare(self.reviews, "code-review", [], self.findings)
        self.assertTrue(result["rereview"])
        self.assertTrue(os.path.exists(result["previous_findings"]))


if __name__ == "__main__":
    unittest.main()
