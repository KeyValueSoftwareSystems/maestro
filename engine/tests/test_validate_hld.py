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

    def valid_text(self, open_body="None", interfaces="- Client calls the backend to save a draft (sync)."):
        sections = {
            "Decision summary": "\n".join(
                f"- Confirmed architectural decision {index}." for index in range(1, 6)
            ),
            "Context and scope": "The approved feature spans one backend and one client.",
            "Proposed design": "The backend owns decisions. The client renders server state.\n\n```mermaid\nflowchart LR\n  client --> backend\n```",
            "Interfaces": interfaces,
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

    def test_long_section_does_not_fail(self):
        detail = " ".join(
            f"Architecture detail {index} preserves a necessary confirmed system decision."
            for index in range(1, 701)
        )
        text = self.valid_text().replace(
            "The approved feature spans one backend and one client.", detail, 1,
        )
        errors, warnings = validate_hld.validate(
            self.write(text), open_questions_path=self.ledger(),
        )
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def infra_text(self, infra_body, interfaces="- Client calls the backend to save a draft (sync)."):
        return self.valid_text(interfaces=interfaces).replace(
            "## Key decisions", f"## Infrastructure and operations\n\n{infra_body}\n\n## Key decisions")

    def test_infrastructure_section_follows_the_workspace_level(self):
        plain = self.write(self.valid_text())
        # no infrastructure in the workspace: the section is not required
        self.assertEqual(validate_hld.validate(plain, self.ledger())[0], [])
        for level in ("containers", "iac"):
            errors, _ = validate_hld.validate(plain, self.ledger(), infra_level=level)
            self.assertTrue(any(e.startswith("missing section: infrastructure and operations")
                                for e in errors), errors)
        none = self.write(self.infra_text("None — this feature changes no infrastructure."))
        self.assertEqual(validate_hld.validate(none, self.ledger(), infra_level="iac")[0], [])
        listed = self.write(self.infra_text(
            "- Add an autoscaled export worker (2-10 replicas on queue depth).\n"
            "- New SQS queue `exports` with a dead-letter queue."))
        self.assertEqual(validate_hld.validate(listed, self.ledger(), infra_level="iac")[0], [])
        prose = self.write(self.infra_text("Add a worker and a queue."))
        errors, _ = validate_hld.validate(prose, self.ledger(), infra_level="iac")
        self.assertTrue(any("must list each change" in e for e in errors))

    def test_diagram_required_when_crossing_repositories_or_changing_infrastructure(self):
        no_diagram = self.valid_text().replace(
            "\n\n```mermaid\nflowchart LR\n  client --> backend\n```", "")
        errors, _ = validate_hld.validate(self.write(no_diagram), self.ledger())
        self.assertTrue(any("mermaid architecture diagram" in e for e in errors))
        local = no_diagram.replace("- Client calls the backend to save a draft (sync).", "None")
        self.assertEqual(validate_hld.validate(self.write(local), self.ledger())[0], [])
        infra_only = self.infra_text("- New Redis cache for drafts (1 GB, 24 h TTL).",
                                     interfaces="None").replace(
            "\n\n```mermaid\nflowchart LR\n  client --> backend\n```", "")
        errors, _ = validate_hld.validate(self.write(infra_only), self.ledger(), infra_level="iac")
        self.assertTrue(any("mermaid architecture diagram" in e for e in errors))

    def test_report_names_infrastructure_changes(self):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            validate_hld.main([self.write(self.infra_text("- Add a 3-node Kafka topic.")),
                               "--infra-level", "iac", "--report"])
        report = json.loads(out.getvalue())
        self.assertTrue(report["infra_changed"])
        self.assertTrue(report["valid"], report)

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

    def report(self, text):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            validate_hld.main([self.write(text), "--open-questions", self.ledger(), "--report"])
        return json.loads(buf.getvalue())

    def test_interfaces_decide_whether_a_contract_is_needed(self):
        listed = self.report(self.valid_text())
        self.assertTrue(listed["valid"], listed)
        self.assertTrue(listed["interfaces_changed"])
        none = self.report(self.valid_text(interfaces="None."))
        self.assertTrue(none["valid"], none)
        self.assertFalse(none["interfaces_changed"])

    def test_interfaces_must_be_listed_not_described(self):
        errors, _ = validate_hld.validate(
            self.write(self.valid_text(interfaces="The client talks to the backend somehow.")),
            open_questions_path=self.ledger(),
        )
        self.assertTrue(any("interfaces must list" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
