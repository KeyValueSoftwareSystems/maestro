#!/usr/bin/env python3
"""UI <-> engine anti-drift tests.

    python3 testdata/test_ui_schema_sync.py

Asserts ui/builder.html's embedded data blocks match their sources of truth
(regenerate with `python3 ui/embed.py`), that the UI's lint rule ids exist in the
engine catalog, and — when node is available — that YAML dumped by the vendored
js-yaml parses identically in the engine's strict-subset loader (wf.py).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))
import validate  # noqa: E402
import wf  # noqa: E402


def block(html, block_id):
    m = re.search(rf'<script type="application/json" id="{block_id}">(.*?)</script>', html, re.S)
    if not m:
        raise AssertionError(f"block #{block_id} missing from builder.html")
    return m.group(1).replace("<\\/", "</")


class SyncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "ui", "builder.html"), encoding="utf-8") as fh:
            cls.html = fh.read()

    def test_schema_block_matches_engine_schema(self):
        with open(os.path.join(ROOT, "engine", "schemas", "workflow.schema.json"), encoding="utf-8") as fh:
            src = fh.read().strip()
        self.assertEqual(block(self.html, "workflow-schema").strip(), src,
                         "stale schema embed — run: python3 ui/embed.py")

    def test_lint_rules_block_matches_engine_catalog(self):
        embedded = json.loads(block(self.html, "lint-rules"))
        self.assertEqual(embedded, validate.RULE_IDS,
                         "stale lint-rules embed — run: python3 ui/embed.py")

    def test_ui_lint_rule_ids_subset_of_engine(self):
        # the ids the client-side linter emits (mirrors the list in builder.html's selftest)
        used = re.findall(r'(?:err|warn)\("([a-z-]+)"', self.html)
        self.assertTrue(used, "no client lint rules found in builder.html")
        unknown = sorted(set(used) - set(validate.RULE_IDS))
        self.assertEqual(unknown, [], f"UI emits rule ids missing from engine catalog: {unknown}")

    def test_jsyaml_output_parses_in_engine_loader(self):
        """Cross-parser: js-yaml.dump(load(workflow)) must be parseable by wf.py and
        semantically identical. Skipped when node isn't installed."""
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        vendor = re.search(r"<script>/\* vendored js-yaml.*?\n(.*?)</script>", self.html, re.S)
        self.assertIsNotNone(vendor, "vendored js-yaml block missing")
        import tempfile
        for name in ("sdlc-main", "design", "impl", "qa"):
            path = os.path.join(ROOT, "workflows", f"{name}.yaml")
            with open(path, encoding="utf-8") as fh:
                original_text = fh.read()
            with tempfile.TemporaryDirectory() as tmp:
                lib = os.path.join(tmp, "jsyaml.js")
                with open(lib, "w", encoding="utf-8") as fh:
                    fh.write(vendor.group(1))
                js = os.path.join(tmp, "t.js")
                with open(js, "w", encoding="utf-8") as fh:
                    fh.write("""
const fs = require('fs');
const jsyaml = require('./jsyaml.js');
const doc = jsyaml.load(fs.readFileSync(process.argv[2], 'utf8'));
process.stdout.write(jsyaml.dump(doc, {lineWidth: -1, noRefs: true, noCompatMode: true}));
""")
                proc = subprocess.run([node, js, path], capture_output=True, text=True, timeout=30)
                self.assertEqual(proc.returncode, 0, f"{name}: node failed: {proc.stderr[:400]}")
                redumped = proc.stdout
            engine_view = wf.loads(redumped)          # must not raise
            original = wf.loads(original_text)
            self.assertEqual(engine_view, original,
                             f"{name}: js-yaml round-trip changed the document")


if __name__ == "__main__":
    unittest.main(verbosity=1)
