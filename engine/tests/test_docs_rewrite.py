import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import docs_rewrite


def _doc(root, rel, status):
    p = os.path.join(root, "docs", rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(f"---\ndoc: {rel.split('/')[0].replace('.md', '')}\nstatus: {status}\n---\n# x\n")


class DocsRewriteTest(unittest.TestCase):
    def test_gate_only_for_verified_docs(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertFalse(docs_rewrite.check(root)["needs_approval"])
            _doc(root, "architecture.md", "draft")
            self.assertFalse(docs_rewrite.check(root)["needs_approval"])
            _doc(root, "technical/a.md", "verified")
            r = docs_rewrite.check(root)
            self.assertTrue(r["needs_approval"])
            self.assertEqual((r["doc_count"], r["verified_count"]), (2, 1))
            self.assertEqual(len(r["summary"].splitlines()), 3)


if __name__ == "__main__":
    unittest.main()
