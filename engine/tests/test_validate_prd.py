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
               else "- Responds within 300 ms at p95 for 50 requests per second."
               if heading == "non functional requirements"
               else f"A concise confirmed product decision for {heading}.")
            for heading in validate_prd.REQUIRED_SECTIONS
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

    def test_long_section_does_not_fail(self):
        detail = " ".join(
            f"Confirmed product detail {index} remains necessary."
            for index in range(1, 801)
        )
        text = self.valid_text().replace(
            "A concise confirmed product decision for summary.", detail, 1,
        )
        errors, warnings = validate_prd.validate(self.write(text))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_repetition_fails(self):
        repeated = "This exact product sentence contains enough words to trigger repetition."
        text = self.valid_text().replace(
            "A concise confirmed product decision for summary.",
            f"{repeated} {repeated}",
            1,
        )
        errors, _ = validate_prd.validate(self.write(text))
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

    def test_non_functional_requirements_need_targets_or_an_explicit_none(self):
        target = "- Responds within 300 ms at p95 for 50 requests per second."
        text = self.valid_text()
        errors, warnings = validate_prd.validate(self.write(text.replace(
            target, "None beyond the existing service standards.")))
        self.assertEqual((errors, warnings), ([], []))
        errors, _ = validate_prd.validate(self.write(text.replace(
            target, "It should be fast and reliable.")))
        self.assertTrue(any(e.startswith("non functional requirements: list each") for e in errors))
        errors, warnings = validate_prd.validate(self.write(text.replace(
            target, "- Exports stay fast.")))
        self.assertEqual(errors, [])
        self.assertTrue(any("no measurable target" in w for w in warnings))
        missing = text.replace("## Non Functional Requirements\n\n" + target + "\n\n", "")
        errors, _ = validate_prd.validate(self.write(missing))
        self.assertIn("missing section: non functional requirements", errors)
        # common headings in an existing PRD count on the fast path
        errors, _ = validate_prd.validate(self.write(
            missing.replace("## Constraints", "## NFRs\n\n- 99.9% monthly uptime.\n\n## Constraints")),
            compatible=True)
        self.assertEqual(errors, [])

    def test_unresolved_to_confirm_marks_fail_strict_mode_only(self):
        text = self.valid_text().replace(
            "A concise confirmed product decision for non goals.",
            "Bulk export is out of scope (to confirm).",
        )
        errors, _ = validate_prd.validate(self.write(text))
        self.assertTrue(any(e.startswith('non goals: unresolved "(to confirm)"') for e in errors))
        errors, _ = validate_prd.validate(self.write(text), compatible=True)
        self.assertEqual(errors, [])

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

    def test_mechanical_fix_joins_wrapped_criteria_and_renumbers(self):
        text = self.valid_text().replace(
            "- AC-01: The confirmed behavior is observable.",
            "- AC-04: The confirmed behavior is observable and preserves\n"
            "  the user's entered values.\n"
            "- AC-09: A second observable result is shown.",
        )
        path = self.write(text)
        fixes = validate_prd.apply_mechanical_fixes(path)
        self.assertIn("joined wrapped acceptance-criteria lines", fixes)
        self.assertIn("renumbered acceptance criteria sequentially", fixes)
        with open(path) as fh:
            updated = fh.read()
        self.assertIn(
            "- AC-01: The confirmed behavior is observable and preserves the user's entered values.",
            updated,
        )
        self.assertIn("- AC-02: A second observable result is shown.", updated)
        errors, _ = validate_prd.validate(path)
        self.assertEqual(errors, [])

    def test_headings_inside_code_fences_are_not_headings(self):
        for fence in ("```", "~~~"):
            block = f"{fence}bash\n# install the tool\n## not a section\n{fence}"
            text = self.valid_text().replace(
                "A concise confirmed product decision for summary.",
                f"A concise confirmed product decision for summary.\n\n{block}")
            errors, _ = validate_prd.validate(self.write(text))
            self.assertEqual(errors, [], fence)
            sections = validate_prd._sections(text)
            self.assertIn("## not a section", sections["summary"])
            self.assertNotIn("not a section", sections)
        # an unclosed fence is reported and does not hide the sections after it
        text = self.valid_text().replace("decision for summary.", "decision for summary.\n\n```bash\nls")
        errors, _ = validate_prd.validate(self.write(text))
        self.assertEqual([e for e in errors if "never closed" not in e], [])
        self.assertTrue(any("never closed" in e for e in errors), errors)

    def test_mechanical_fix_keeps_the_ac_label_form(self):
        text = self.valid_text().replace(
            "- AC-01: The confirmed behavior is observable.",
            "- **AC-01:** The confirmed behavior is observable.\n"
            "- **AC-02**: A second result is shown.\n- AC-3: A third result.")
        path = self.write(text)
        validate_prd.apply_mechanical_fixes(path)
        with open(path) as fh:
            updated = fh.read()
        for line in ("- AC-01: The confirmed behavior is observable.", "- AC-02: A second result is shown.",
                     "- AC-03: A third result."):
            self.assertIn(line, updated)
        self.assertNotIn("**AC", updated)
        self.assertNotIn(":**", updated.split("## Acceptance")[1])
        self.assertEqual(validate_prd.validate(path)[0], [])


class MinorPrdTest(unittest.TestCase):
    """The mini PRD of a minor change: Problem, Acceptance criteria and Out of scope only."""
    MINI = ("# Export button — PRD\n\n**Feature slug:** `export`\n**Status:** Ready for review\n\n"
            "## Problem\n\nPeople copy the table by hand to share it.\n\n"
            "## Acceptance criteria\n\n- AC-01: The table page shows an Export button.\n"
            "- AC-02: Export downloads the visible rows as CSV.\n\n"
            "## Out of scope\n\nOther formats.\n")

    def write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        handle.write(text)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def test_mini_prd_passes_minor_and_fails_major(self):
        path = self.write(self.MINI)
        self.assertEqual(validate_prd.validate(path, prd_type="minor"), ([], []))
        errors, _ = validate_prd.validate(path)
        self.assertIn("missing section: users and jobs", errors)

    def test_minor_needs_its_three_sections_and_ac_format(self):
        text = self.MINI.replace("## Out of scope\n\nOther formats.\n", "")
        errors, _ = validate_prd.validate(self.write(text), prd_type="minor")
        self.assertIn("missing section: out of scope", errors)
        text = self.MINI.replace("- AC-02: Export", "- Export")
        errors, _ = validate_prd.validate(self.write(text), prd_type="minor")
        self.assertTrue(any("beginning AC-01" in e for e in errors), errors)
        self.assertTrue(any("header" in e for e in validate_prd.validate(
            self.write(self.MINI.replace("**Status:** Ready for review\n", "")), prd_type="minor")[0]))

    def test_minor_accepts_equivalent_headings_and_a_full_prd(self):
        text = self.MINI.replace("## Problem", "## Summary").replace("## Out of scope", "## Non-goals")
        self.assertEqual(validate_prd.validate(self.write(text), prd_type="minor")[0], [])
        full = PrdValidationTest("test_complete_concise_prd_passes").valid_text()
        self.assertEqual(validate_prd.validate(self.write(full), prd_type="minor")[0], [])

    def test_cli_type_flag(self):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            code = validate_prd.main([self.write(self.MINI), "--type", "minor", "--report"])
        self.assertEqual(code, 0)
        self.assertIn('"valid": true', out.getvalue())


if __name__ == "__main__":
    unittest.main()
