"""Deterministic HLD structure, readability, and deferred-question checks."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import validate_hld  # noqa: E402


class HldValidationTest(unittest.TestCase):
    def write(self, text, suffix=".md"):
        handle = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False)
        handle.write(text)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def ledger(self, questions=None):
        return self.write(json.dumps({
            "schema_version": 1,
            "feature_slug": "demo",
            "questions": questions or [],
        }), suffix=".json")

    def valid_text(self, open_body="None"):
        sections = {
            "Decision summary": "\n".join(
                f"- Confirmed architectural decision {index}." for index in range(1, 6)
            ),
            "Context and scope": "The approved feature spans one backend and one client.",
            "Proposed design": "The backend owns decisions. The client renders server state.",
            "Key decisions and trade-offs": "Use one source of truth to avoid divergent rules.",
            "Delivery and risks": "Ship the backend contract before connecting the client.",
            "Open questions": open_body,
        }
        return (
            "# Demo feature — HLD\n\n"
            "**Feature slug:** `demo`\n"
            "**Status:** Ready for review\n\n"
            + "\n\n".join(f"## {heading}\n\n{body}" for heading, body in sections.items())
            + "\n"
        )

    def test_complete_hld_with_empty_ledger_passes(self):
        errors, warnings = validate_hld.validate(
            self.write(self.valid_text()), open_questions_path=self.ledger(),
        )
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_missing_order_and_summary_shape_fail(self):
        text = self.valid_text().replace(
            "## Context and scope", "## Extra section\n\nExtra.\n\n## Context and scope",
        ).replace("- Confirmed architectural decision 5.\n", "")
        errors, _ = validate_hld.validate(self.write(text), open_questions_path=self.ledger())
        self.assertTrue(any("exact required order" in error for error in errors))
        self.assertTrue(any("unexpected" in error for error in errors))
        self.assertTrue(any("5-8 bullets" in error for error in errors))

    def test_deferred_ledger_must_match_open_questions_section(self):
        question = {
            "id": "cache-choice",
            "question": "Which cache implementation should the LLD select?",
            "why": "The choice does not change system ownership.",
            "options": ["Existing cache", "No cache"],
            "status": "deferred",
            "resolution": {"kind": "skip", "answer": "Deferred to LLD"},
        }
        errors, _ = validate_hld.validate(
            self.write(self.valid_text()), open_questions_path=self.ledger([question]),
        )
        self.assertTrue(any("says None" in error for error in errors))

        errors, _ = validate_hld.validate(
            self.write(self.valid_text("- Select the cache implementation during LLD.")),
            open_questions_path=self.ledger([question]),
        )
        self.assertEqual(errors, [])

    def test_final_ledger_rejects_unresolved_entries(self):
        question = {
            "id": "owner",
            "question": "Which service owns the record?",
            "why": "Ownership changes the architecture.",
            "options": ["Service A", "Service B"],
            "status": "open",
            "resolution": None,
        }
        errors, _ = validate_hld.validate(
            self.write(self.valid_text("- Service ownership remains unresolved.")),
            open_questions_path=self.ledger([question]),
        )
        self.assertTrue(any("only deferred" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
