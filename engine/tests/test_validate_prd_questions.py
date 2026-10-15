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

    def v2(self, questions, unresolved=("open gap",)):
        return {
            "schema_version": 2,
            "questions": questions,
            "audit": {"unresolved": list(unresolved) if questions else [], "contradictions": []},
        }

    def test_alternatives_carry_tradeoffs(self):
        question = self.question(must_resolve=["what happens to the booking"], alternatives=[
            {"label": "Move the booking automatically", "tradeoff": "No admin work, but the "
             "customer may get a slot they cannot attend."},
            {"label": "Cancel and notify the customer", "tradeoff": "Simple, but loses the booking."},
        ])
        errors, _, _ = validate_prd_questions.validate(self.write(self.v2([question])))
        self.assertEqual(errors, [])

        question["alternatives"] = question["alternatives"] + [
            {"label": "Ask support", "tradeoff": "Slow."},
        ]
        errors, _, _ = validate_prd_questions.validate(self.write(self.v2([question])))
        self.assertTrue(any("maximum is 2" in error for error in errors))

        question["alternatives"] = [{"label": question["proposal"], "tradeoff": "Same."}]
        errors, _, _ = validate_prd_questions.validate(self.write(self.v2([question])))
        self.assertTrue(any("repeats the proposal" in error for error in errors))

        question["alternatives"] = [{"label": "Cancel it"}]
        errors, _, _ = validate_prd_questions.validate(self.write(self.v2([question])))
        self.assertTrue(any("tradeoff" in error for error in errors))

    def test_direction_question_needs_a_summary(self):
        question = self.question(kind="direction", proposal="", must_resolve=["overall shape"])
        errors, _, _ = validate_prd_questions.validate(self.write(self.v2([question])))
        self.assertTrue(any("design direction" in error for error in errors))
        question["kind"] = "sideways"
        errors, _, _ = validate_prd_questions.validate(self.write(self.v2([question])))
        self.assertTrue(any(".kind" in error for error in errors))

    def test_empty_queue_requires_latest_confirmed_direction(self):
        empty = self.write(self.v2([]))

        def decisions(*rounds):
            doc = {"schema_version": 2, "decisions": [], "rounds": []}
            for items in rounds:
                doc["rounds"].append({"question_ids": [item["id"] for item in items]})
                doc["decisions"].extend(items)
            return self.write(doc)

        owner = {"id": "owner", "kind": "decision", "source": "user-answer", "answer": "API"}
        direction = {"id": "direction-1", "kind": "direction",
                     "source": "accepted-proposal", "answer": "One service owns it."}
        parked = dict(direction, id="direction-0", source="deferred")
        follow_up = dict(owner, id="owner-follow-up")

        # Without the flag an empty queue stays clear (PRD and post-checks).
        errors, _, _ = validate_prd_questions.validate(empty, decisions_path=decisions([owner]))
        self.assertEqual(errors, [])

        cases = [
            (decisions([owner]), "requires a confirmed design direction"),
            (decisions([owner, parked]), "requires a confirmed design direction"),
            (decisions([owner], [direction], [follow_up]), "predates later decisions"),
        ]
        for path, message in cases:
            errors, _, _ = validate_prd_questions.validate(
                empty, decisions_path=path, require_direction=True,
            )
            self.assertTrue(any(message in error for error in errors), errors)

        for path in (decisions([owner, direction]), decisions([owner], [direction])):
            errors, _, _ = validate_prd_questions.validate(
                empty, decisions_path=path, require_direction=True,
            )
            self.assertEqual(errors, [])
        # The flag only constrains closing the queue; asking questions is always allowed.
        errors, _, _ = validate_prd_questions.validate(
            self.write(self.v2([self.question(must_resolve=["fact"])])),
            decisions_path=decisions([owner]), require_direction=True,
        )
        self.assertEqual(errors, [])


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
