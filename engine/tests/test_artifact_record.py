"""artifact_record.py — the per-run manifest of published stage artifacts.

Proves the mapping that lets a *revision* update the same shareable link: get returns
empty before anything is recorded; record upserts; a later path-only record (no url)
preserves a url an earlier run established; and the manifest write is atomic + stable.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import artifact_record  # noqa: E402


def run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = artifact_record.main(argv)
    out = buf.getvalue().strip()
    return rc, (json.loads(out) if out else None)


class ArtifactRecordTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_get_empty_before_record(self):
        rc, out = run(["get", self.d, "hld"])
        self.assertEqual(rc, 0)
        self.assertEqual(out, {"key": "hld", "file": "", "url": "", "title": ""})

    def test_record_then_get_roundtrip(self):
        rc, _ = run(["record", self.d, "hld", "--file", "hld.html",
                     "--url", "https://claude.ai/code/artifact/abc", "--title", "HLD"])
        self.assertEqual(rc, 0)
        _, out = run(["get", self.d, "hld"])
        self.assertEqual(out["url"], "https://claude.ai/code/artifact/abc")
        self.assertEqual(out["file"], "hld.html")
        self.assertEqual(out["title"], "HLD")

    def test_revision_updates_same_key(self):
        run(["record", self.d, "hld", "--file", "hld.html", "--url", "u1"])
        run(["record", self.d, "hld", "--file", "hld.html", "--url", "u2"])
        _, out = run(["get", self.d, "hld"])
        self.assertEqual(out["url"], "u2")
        # still one entry, not two
        _, manifest = run(["list", self.d])
        self.assertEqual(list(manifest["artifacts"].keys()), ["hld"])

    def test_path_only_record_preserves_existing_url(self):
        # a Claude Code run sets the link; a later path-only harness must not wipe it
        run(["record", self.d, "hld", "--file", "hld.html", "--url", "keepme"])
        run(["record", self.d, "hld", "--file", "hld.html"])  # no --url
        _, out = run(["get", self.d, "hld"])
        self.assertEqual(out["url"], "keepme")

    def test_manifest_is_valid_json_on_disk(self):
        run(["record", self.d, "prd", "--file", "prd.html", "--url", "u"])
        with open(os.path.join(self.d, "artifacts.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["version"], 1)
        self.assertIn("prd", data["artifacts"])

    def test_malformed_manifest_fails_closed(self):
        with open(os.path.join(self.d, "artifacts.json"), "w", encoding="utf-8") as fh:
            fh.write("not json")
        rc, _ = run(["get", self.d, "hld"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
