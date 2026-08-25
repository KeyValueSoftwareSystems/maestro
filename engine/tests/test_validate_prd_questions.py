"""Validation for feature-specific Grill question queues."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import validate_prd_questions  # noqa: E402


class QuestionQueueValidationTest(unittest.TestCase):
    def write(self, doc):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(doc, handle)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def question(self, **updates):
        value = {
            "id": "booked-slot-change",
            "title": "Changing a booked slot",
            "question": "What should happen when an admin changes a slot that is already booked?",
            "why": "The answer changes the customer journey and failure behavior.",
            "proposal": "Block the change until the booking is moved or cancelled.",
        }
        value.update(updates)
        return value

    def test_feature_specific_queue_passes(self):
        errors, warnings, _ = validate_prd_questions.validate(self.write({
            "schema_version": 1, "questions": [self.question()],
        }))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_empty_queue_means_clarity(self):
        errors, warnings, doc = validate_prd_questions.validate(self.write({
            "schema_version": 2,
            "questions": [],
            "audit": {"unresolved": [], "contradictions": []},
        }))
        self.assertEqual((errors, warnings, doc["questions"]), ([], [], []))

    def test_v2_question_requires_resolution_facts(self):
        question = self.question(must_resolve=[
            "who may change a booked slot",
            "what happens to the existing booking",
        ])
        errors, warnings, _ = validate_prd_questions.validate(self.write({
            "schema_version": 2,
            "questions": [question],
            "audit": {
                "unresolved": ["booked-slot-change lacks an owner and outcome"],
                "contradictions": [],
            },
        }))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

        question.pop("must_resolve")
        errors, _, _ = validate_prd_questions.validate(self.write({
            "schema_version": 2,
            "questions": [question],
            "audit": {"unresolved": ["booked-slot-change"], "contradictions": []},
        }))
        self.assertTrue(any("must_resolve" in error for error in errors))

    def test_v2_empty_queue_rejects_claimed_gaps(self):
        errors, _, _ = validate_prd_questions.validate(self.write({
            "schema_version": 2,
            "questions": [],
            "audit": {
                "unresolved": ["timezone has no concrete value"],
                "contradictions": ["past bookings are both editable and immutable"],
            },
        }))
        self.assertTrue(any("empty queue" in error for error in errors))

    def test_rejects_section_question_and_multiple_decisions(self):
        errors, _, _ = validate_prd_questions.validate(self.write({
            "schema_version": 1,
            "questions": [self.question(
                title="Acceptance criteria",
                question="Can admins change booked slots? Should mothers be notified?",
            )],
        }))
        self.assertTrue(any("PRD section" in error for error in errors))
        self.assertTrue(any("exactly one decision" in error for error in errors))

    def test_rejects_question_answered_in_prior_round(self):
        decisions = self.write({
            "schema_version": 2,
            "decisions": [{"id": "booked-slot-change", "answer": "Block it"}],
        })
        errors, _, _ = validate_prd_questions.validate(self.write({
            "schema_version": 1, "questions": [self.question()],
        }), decisions_path=decisions)
        self.assertTrue(any("earlier round" in error for error in errors))

    def test_schema_v1_remains_compatible_with_existing_runs(self):
        errors, warnings, _ = validate_prd_questions.validate(self.write({
            "schema_version": 1, "questions": [self.question()],
        }))
        self.assertEqual((errors, warnings), ([], []))
        errors, _, _ = validate_prd_questions.validate(self.write({
            "schema_version": 1, "questions": [self.question()],
        }), require_version=2)
        self.assertTrue(any("this workflow" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
