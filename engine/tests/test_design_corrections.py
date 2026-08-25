"""Approved-correction receipts, effective context, and one-time archive fold."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import design_corrections  # noqa: E402
import state as statemod  # noqa: E402


class DesignCorrectionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-corrections-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        parent = statemod.new_state("feature", "workflows/main.yaml", "hash", {"slug": "feature"})
        statemod.save("feature", parent, self.tmp)

    def write(self, relative, text):
        path = os.path.join(self.tmp, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_separate_immutable_receipts_render_effective_context(self):
        first = design_corrections.record(
            "feature", self.tmp, "architecture", "The API service owns token rotation.",
        )
        second = design_corrections.record(
            "feature", self.tmp, "contract", "Return HTTP 409 for a duplicate active claim.",
        )
        duplicate = design_corrections.record(
            "feature", self.tmp, "architecture", "The API service owns token rotation.",
        )
        self.assertNotEqual(first["id"], second["id"])
        self.assertTrue(duplicate["duplicate"])
        approval_dir = os.path.join(
            self.tmp, ".maestro", "runs", "feature", "approved-corrections",
        )
        self.assertEqual(len(os.listdir(approval_dir)), 2)
        self.assertFalse(os.path.exists(os.path.join(
            self.tmp, ".maestro", "runs", "feature", "approved-corrections.md",
        )))
        rendered = design_corrections._render("feature", self.tmp)
        context = Path(self.tmp, rendered["corrections_path"]).read_text(encoding="utf-8")
        self.assertIn(first["id"], context)
        self.assertIn(second["id"], context)
        manifest = json.loads(Path(self.tmp, rendered["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["corrections"]), 2)

    def test_child_correction_targets_parent_without_parent_state_edit(self):
        child = statemod.new_state(
            "feature--lld--be", "workflows/repo-lld.yaml", "hash",
            {"slug": "feature--lld--be", "parent_slug": "feature", "repo": "be"},
        )
        statemod.save("feature--lld--be", child, self.tmp)
        parent_before = Path(statemod.state_path("feature", self.tmp)).read_text(encoding="utf-8")
        result = design_corrections.record(
            "feature--lld--be", self.tmp, "repository", "Use a serializable claim transaction.",
        )
        self.assertEqual(result["parent_slug"], "feature")
        receipt = json.loads(Path(self.tmp, result["receipt_path"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["repo"], "be")
        self.assertEqual(
            Path(statemod.state_path("feature", self.tmp)).read_text(encoding="utf-8"),
            parent_before,
        )

    def test_fold_changes_final_copy_once_and_preserves_original(self):
        original = "openapi: 3.0.0\ninfo:\n  title: Original\n  version: 1.0.0\n"
        source = self.write(".maestro/runs/feature/openapi.yaml", original)
        correction = design_corrections.record(
            "feature", self.tmp, "contract", "Rename the public API title to Booking API.",
        )
        prepared = design_corrections.prepare_fold("feature", self.tmp)
        self.assertTrue(prepared["pending"])
        final = os.path.join(self.tmp, prepared["final_design_dir"], "openapi.yaml")
        with open(final, "w", encoding="utf-8") as fh:
            fh.write(original.replace("Original", "Booking API"))
        report = self.write(
            ".maestro/runs/feature/correction-fold-report.json",
            json.dumps({
                "schema_version": 1,
                "correction_ids": [correction["id"]],
                "updated_paths": [os.path.relpath(final, self.tmp)],
            }),
        )
        result = design_corrections.finalize_fold("feature", self.tmp, report)
        self.assertTrue(result["valid"])
        self.assertEqual(Path(source).read_text(encoding="utf-8"), original)
        self.assertFalse(design_corrections.prepare_fold("feature", self.tmp)["pending"])


if __name__ == "__main__":
    unittest.main()
