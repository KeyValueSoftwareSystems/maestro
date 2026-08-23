"""Deterministic PRD structure and readability checks."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import validate_prd  # noqa: E402


class PrdValidationTest(unittest.TestCase):
    def write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        handle.write(text)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def valid_text(self):
        header = "# Demo feature — PRD\n\n**Feature slug:** `demo`\n**Status:** Ready for review"
        return header + "\n\n" + "\n\n".join(
            f"## {heading.title().replace('Non Goals', 'Non-goals')}\n\n"
            + ("- AC-01: The confirmed behavior is observable."
               if heading == "acceptance criteria"
               else f"A concise confirmed product decision for {heading}.")
            for heading in validate_prd.SECTION_BUDGETS
        ) + "\n"

    def test_complete_concise_prd_passes(self):
        errors, warnings = validate_prd.validate(self.write(self.valid_text()))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_missing_and_empty_sections_fail(self):
        text = self.valid_text().replace(
            "## Non-goals\n\nA concise confirmed product decision for non goals.\n\n", ""
        ).replace(
            "## References\n\nA concise confirmed product decision for references.", "## References\n"
        )
        errors, _ = validate_prd.validate(self.write(text))
        self.assertIn("missing section: non goals", errors)
        self.assertIn("empty section: references", errors)

    def test_section_budget_and_repetition_fail(self):
        repeated = "This exact product sentence contains enough words to trigger repetition."
        text = self.valid_text().replace(
            "A concise confirmed product decision for summary.",
            " ".join(["word"] * 121) + f". {repeated} {repeated}",
            1,
        )
        errors, _ = validate_prd.validate(self.write(text))
        self.assertTrue(any("summary:" in error and "exceeds" in error for error in errors))
        self.assertTrue(any(error.startswith("repeated sentence:") for error in errors))

    def test_missing_file_fails_cleanly(self):
        errors, warnings = validate_prd.validate("/definitely/missing/prd.md")
        self.assertTrue(errors[0].startswith("cannot read PRD:"))
        self.assertEqual(warnings, [])

    def test_existing_prd_aliases_pass_only_in_compatible_mode(self):
        text = self.valid_text().replace("## Summary", "## Executive summary").replace(
            "## Functional Scope", "## Requirements"
        ).replace("## Non-goals", "## Out of scope")
        path = self.write(text)
        strict_errors, _ = validate_prd.validate(path)
        compatible_errors, _ = validate_prd.validate(path, compatible=True)
        self.assertTrue(strict_errors)
        self.assertEqual(compatible_errors, [])

    def test_acceptance_ids_are_required_and_sequential(self):
        text = self.valid_text().replace(
            "- AC-01: The confirmed behavior is observable.",
            "- The confirmed behavior is observable.\n- AC-03: A later result is visible.",
        )
        errors, _ = validate_prd.validate(self.write(text))
        self.assertTrue(any("each non-empty line" in error for error in errors))
        self.assertTrue(any("unique and sequential" in error for error in errors))

    def test_codes_outside_acceptance_criteria_fail(self):
        text = self.valid_text().replace(
            "A concise confirmed product decision for functional scope.",
            "FR-01 adds the confirmed behavior.",
        )
        errors, _ = validate_prd.validate(self.write(text))
        self.assertTrue(any("allowed only in acceptance criteria" in error for error in errors))

    def test_compatible_mode_does_not_require_acceptance_ids(self):
        text = self.valid_text().replace(
            "- AC-01: The confirmed behavior is observable.",
            "The confirmed behavior is observable.",
        )
        errors, _ = validate_prd.validate(self.write(text), compatible=True)
        self.assertEqual(errors, [])

    def test_strict_mode_requires_compact_document_header(self):
        text = self.valid_text().replace(
            "# Demo feature — PRD\n\n**Feature slug:** `demo`\n**Status:** Ready for review\n\n",
            "",
        )
        errors, _ = validate_prd.validate(self.write(text))
        self.assertTrue(any("level-1 PRD title" in error for error in errors))
        self.assertTrue(any("Feature slug" in error for error in errors))
        self.assertTrue(any("Status" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
