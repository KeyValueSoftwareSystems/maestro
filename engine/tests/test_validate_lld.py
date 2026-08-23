"""Deterministic repository LLD structure and readability checks."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import validate_lld  # noqa: E402


class LldValidationTest(unittest.TestCase):
    def write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        handle.write(text)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def valid_text(self):
        sections = {
            "Change summary": "\n".join(
                f"- Deliver repository behavior {index}." for index in range(1, 5)
            ),
            "Existing seam": (
                "Requests enter through `src/routes.py` and follow the existing service boundary."
            ),
            "Proposed changes": (
                "Extend the current service with the approved behavior. Keep persistence ownership "
                "inside the repository's existing data layer."
            ),
            "Data model and migrations": (
                "| Entity and field | Type, nullability and default | Keys, constraints and indexes |\n"
                "|---|---|---|\n"
                "| `Widget.id` | UUID, required | Primary key |\n"
                "| `Widget.ownerId` | UUID, required | Foreign key; index supports owner reads |\n\n"
                "The additive migration creates the table. No extension or backfill is required; "
                "rollback drops it before release."
            ),
            "API and client contract": (
                "| Operation | Auth | Request | Response | Errors |\n"
                "|---|---|---|---|---|\n"
                "| POST `/api/v1/widgets` | Bearer token | `CreateWidgetRequest { name: string }` | "
                "201 `WidgetResponse { id: UUID, name: string }` | 400 `VALIDATION_FAILED` |\n\n"
                "### Frontend handoff\n\n"
                "Publish the owner-maintained types at `packages/api/widgets.ts`. Keep a canonical "
                "success fixture beside that contract so the client can mock the operation."
            ),
            "State and flows": (
                "The route validates input, invokes the service, and returns the documented result. "
                "The service owns ordering and writes state once validation succeeds."
            ),
            "Failure and operational behavior": (
                "Validation failures return the existing client error. Storage failures preserve "
                "the prior state and use current logging."
            ),
            "Implementation sequence": (
                "1. Extend the service boundary and cover its behavior.\n"
                "2. Connect the route and add an integration test."
            ),
            "Verification": (
                "Service tests cover validation and state changes. Route tests cover the public result."
            ),
        }
        return (
            "# Demo backend — LLD\n\n"
            "**Parent feature:** `demo`\n"
            "**Repository:** `backend`\n"
            "**Status:** Ready for review\n\n"
            + "\n\n".join(f"## {heading}\n\n{body}" for heading, body in sections.items())
            + "\n"
        )

    def test_complete_lld_passes(self):
        errors, warnings = validate_lld.validate(
            self.write(self.valid_text()), parent_slug="demo", repo="backend",
        )
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_missing_order_and_summary_shape_fail(self):
        text = self.valid_text().replace(
            "## Existing seam", "## Extra section\n\nExtra.\n\n## Existing seam",
        ).replace("- Deliver repository behavior 4.\n", "")
        errors, _ = validate_lld.validate(self.write(text))
        self.assertTrue(any("exact required order" in error for error in errors))
        self.assertTrue(any("unexpected" in error for error in errors))
        self.assertTrue(any("4-7 bullets" in error for error in errors))

    def test_metadata_must_match_workflow_inputs(self):
        errors, _ = validate_lld.validate(
            self.write(self.valid_text()), parent_slug="other", repo="mobile",
        )
        self.assertTrue(any("Parent feature does not match" in error for error in errors))
        self.assertTrue(any("Repository does not match" in error for error in errors))

    def test_seam_and_sequence_shape_are_enforced(self):
        text = self.valid_text().replace("`src/routes.py`", "the route").replace(
            "2. Connect the route and add an integration test.", "Connect the route later.",
        )
        errors, _ = validate_lld.validate(self.write(text))
        self.assertTrue(any("backticked" in error for error in errors))
        self.assertTrue(any("2-10 numbered" in error for error in errors))

    def test_unresolved_placeholders_fail(self):
        text = self.valid_text().replace(
            "Extend the current service", "TODO: Extend the current service",
        )
        errors, _ = validate_lld.validate(self.write(text))
        self.assertTrue(any("unresolved placeholder" in error for error in errors))

    def test_schema_and_frontend_contract_are_enforced(self):
        text = self.valid_text().replace(
            "| Entity and field | Type, nullability and default | Keys, constraints and indexes |\n"
            "|---|---|---|\n"
            "| `Widget.id` | UUID, required | Primary key |\n"
            "| `Widget.ownerId` | UUID, required | Foreign key; index supports owner reads |\n\n",
            "The service stores widgets.\n\n",
        ).replace("### Frontend handoff", "### Consumer notes")
        errors, _ = validate_lld.validate(self.write(text))
        self.assertTrue(any("schema table" in error for error in errors))
        self.assertTrue(any("Frontend handoff" in error for error in errors))

    def test_explicit_no_change_sentences_are_valid(self):
        text = self.valid_text()
        data_start = text.index("## Data model and migrations")
        api_start = text.index("## API and client contract")
        state_start = text.index("## State and flows")
        text = (
            text[:data_start]
            + "## Data model and migrations\n\nNo repository-owned persistence change.\n\n"
            + "## API and client contract\n\nNo externally consumed interface change.\n\n"
            + text[state_start:]
        )
        errors, _ = validate_lld.validate(self.write(text))
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
