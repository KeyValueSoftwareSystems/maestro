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

    def baseline(self, name="lld", folder=None):
        with open(os.path.join(folder or self.reviews, f"{name}.baseline.json")) as fh:
            return json.load(fh)

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
            self.assertEqual(json.load(fh)["finding_ids"], ["LR-1"])
        third = self.prepare()  # nothing changed since the second round
        self.assertEqual(third["changed_csv"], "")
        self.assertIn("No changes", self.diff(third))

    def test_one_baseline_file_per_review_and_no_copies_of_the_documents(self):
        """The last round's text lives in one file: no folder of document copies for a search
        (or an agent) to mistake for the documents."""
        self.write(self.doc, "# LLD\n\nretry: none\n")
        other = os.path.join(self.dir, "lld-web.md")
        self.write(other, "# LLD web\n")
        state = os.path.join(self.dir, ".engine", "reviews")
        review_scope.prepare(self.reviews, "lld", [self.doc, other], self.findings, state)
        self.assertEqual(sorted(os.listdir(state)), ["lld.baseline.json", "lld.diff"])
        self.assertEqual(os.listdir(self.reviews), [])  # the reviewer's folder holds only reports
        kept = self.baseline(folder=state)
        self.assertEqual(kept["files"], {self.doc: "# LLD\n\nretry: none\n",
                                         other: "# LLD web\n"})
        self.assertIsNone(kept["finding_ids"])  # no review round has happened yet
        # a document added for the second round shows whole in the diff
        new = os.path.join(self.dir, "lld-infra.md")
        self.write(new, "# LLD infra\n")
        second = review_scope.prepare(self.reviews, "lld", [self.doc, other, new], self.findings,
                                      state)
        self.assertEqual(second["changed_csv"], new)
        self.assertIn("+# LLD infra", self.diff(second))

    def test_code_review_keeps_only_the_previous_findings(self):
        result = review_scope.prepare(self.reviews, "code-review", [], self.findings)
        self.assertEqual((result["rereview"], result["diff_path"]), (False, ""))
        self.assertEqual(os.listdir(self.reviews), [])  # nothing to keep before the first round
        self.write(self.findings, json.dumps({"findings": [{"id": "F1"}, {"id": "F2"}]}))
        result = review_scope.prepare(self.reviews, "code-review", [], self.findings)
        self.assertTrue(result["rereview"])
        self.assertEqual(self.baseline("code-review"), {
            "schema_version": 1, "files": None, "finding_ids": ["F1", "F2"]})
        # findings.py verdict --previous reads the ids from the baseline
        import findings as findingsmod
        self.assertEqual(findingsmod.previous_ids(result["previous_findings"]), {"F1", "F2"})
        os.remove(self.findings)  # the stage starts over: no round to compare with
        result = review_scope.prepare(self.reviews, "code-review", [], self.findings)
        self.assertEqual((result["rereview"], result["previous_findings"]), (False, ""))
        self.assertFalse(os.path.exists(os.path.join(self.reviews, "code-review.baseline.json")))


if __name__ == "__main__":
    unittest.main()
