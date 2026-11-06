"""prd_source: a client's own PRD is normalized (and a client prd.md kept as prd.original.md);
a short request goes through the interview."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import prd_source  # noqa: E402

LONG = " ".join(["The client needs a clear rule for every exported report."] * 30)
MAESTRO_PRD = "# Demo — PRD\n\n**Feature slug:** `demo`\n**Status:** Ready for review\n"


class PrdSourceTest(unittest.TestCase):
    def setUp(self):
        self.req = tempfile.mkdtemp(prefix="prd-source-")
        self.addCleanup(shutil.rmtree, self.req, ignore_errors=True)

    def write(self, name, text, mode="w"):
        with open(os.path.join(self.req, name), mode) as fh:
            fh.write(text)

    def run_source(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(prd_source.main(["--requirement", self.req]), 0)
        return json.loads(out.getvalue())

    def test_short_request_goes_to_the_interview(self):
        self.write("request.md", "Let admins export reports as CSV.\n")
        self.write("links.txt", "https://figma.example/file\n")
        result = self.run_source()
        self.assertEqual((result["state"], result["source_count"]), ("interview", 0))

    def test_long_document_or_office_file_is_normalized(self):
        self.write("request.md", "Short note.\n")
        self.write("client-spec.md", LONG)
        self.write("brief.pdf", b"%PDF-1.4 ...", mode="wb")
        self.write(".hidden.md", LONG)
        result = self.run_source()
        self.assertEqual(result["state"], "normalize")
        self.assertEqual([os.path.basename(p) for p in result["sources_csv"].split(",")],
                         ["brief.pdf", "client-spec.md"])
        self.assertIn("client-spec.md", result["summary"])

    def test_a_jira_xml_export_is_a_source_beside_a_wireframe_pdf(self):
        self.write("request.md", "Short note.\n")
        self.write("wireframes.pdf", b"%PDF-1.4 ...", mode="wb")
        self.write("COF-6965.xml", '<rss><channel><item><title>Transfer tickets</title>'
                                   '<description>Let a holder transfer a ticket.</description>'
                                   '</item></channel></rss>\n')
        result = self.run_source()
        self.assertEqual([os.path.basename(p) for p in result["sources_csv"].split(",")],
                         ["COF-6965.xml", "wireframes.pdf"])

    def test_client_prd_md_is_kept_as_the_original_once(self):
        self.write("prd.md", LONG)
        result = self.run_source()
        original = os.path.join(self.req, "prd.original.md")
        self.assertEqual(result["sources_csv"], original)
        # normalizing overwrites prd.md; the original copy is never replaced
        self.write("prd.md", MAESTRO_PRD)
        result = self.run_source()
        with open(original) as fh:
            self.assertEqual(fh.read(), LONG)
        self.assertEqual(result["sources_csv"], original)

    def test_a_maestro_prd_is_not_a_client_source(self):
        self.write("prd.md", MAESTRO_PRD + LONG)
        result = self.run_source()
        self.assertEqual(result["state"], "interview")
        self.assertFalse(os.path.exists(os.path.join(self.req, "prd.original.md")))


if __name__ == "__main__":
    unittest.main()
