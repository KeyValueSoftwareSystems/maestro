"""One decision log per feature: no stage re-asks a decided topic, a question gets at most one
follow-up, and points the evidence already settles are recorded with their source."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import decision_log  # noqa: E402
import validate_prd_questions as vq  # noqa: E402


def question(qid, topic, **extra):
    return {"id": qid, "topic": topic, "title": f"Decide {topic}",
            "question": f"How should {topic} work?", "why": "It changes the design.",
            "proposal": "Use the existing behaviour.", "must_resolve": ["the behaviour"], **extra}


class DecisionLogTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="decision-log-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_dir = os.path.join(self.root, ".maestro", "runs", "demo")
        os.makedirs(os.path.join(self.run_dir, "requirement"))
        self.write("requirement/prd.md", "# Demo — PRD\n")
        self.write("prd-context.json", {"decisions": [
            {"id": "retention", "topic": "export-retention", "title": "Retention",
             "answer": "Keep exports 30 days", "source": "accepted-proposal"},
            {"id": "owner", "topic": "data-owner", "title": "Owner",
             "answer": "Billing owns exports", "source": "assumption", "by": "autopilot"}]})
        self.write("prd-questions.json", {"schema_version": 2, "questions": [],
                                          "audit": {"unresolved": [], "contradictions": []},
                                          "settled": [{"topic": "export-format", "title": "Format",
                                                       "decision": "CSV only",
                                                       "source": ".maestro/runs/demo/requirement/prd.md#Functional scope"}]})

    def write(self, rel, doc):
        path = os.path.join(self.run_dir, rel)
        with open(path, "w") as fh:
            fh.write(doc if isinstance(doc, str) else json.dumps(doc))
        return path

    def sync(self):
        out = io.StringIO()
        with redirect_stdout(out):
            decision_log.main(["sync", "--root", self.root, "--log",
                               ".maestro/runs/demo/decision-log.json", "--stage",
                               "PRD=.maestro/runs/demo/prd-context.json,"
                               ".maestro/runs/demo/prd-questions.json", "--stage",
                               "HLD=.maestro/runs/demo/hld-context.json"])
        return json.loads(out.getvalue())

    def validate(self, doc, decisions=None):
        queue = self.write("hld-questions.json", {"schema_version": 2, "audit": {
            "unresolved": ["gap"], "contradictions": []}, **doc})
        errors, _, out = vq.validate(queue, decisions_path=decisions,
                                     log_path=os.path.join(self.run_dir, "decision-log.json"),
                                     require_topics=True, root=self.root)
        return errors, out

    def test_log_merges_stages_and_settled_points(self):
        result = self.sync()
        self.assertEqual((result["count"], result["assumed"], result["settled"]), (3, 1, 1))
        self.assertEqual(result["summary"],
                         "3 decision(s): 1 settled by evidence, 1 assumed, 0 left open")
        with open(os.path.join(self.root, result["md_path"])) as fh:
            md = fh.read()
        self.assertIn("## PRD", md)
        self.assertIn("**Owner** [ASSUMED — unconfirmed (autopilot)]: Billing owns exports", md)
        self.assertIn("[settled by evidence]: CSV only — source: "
                      "`.maestro/runs/demo/requirement/prd.md#Functional scope`", md)

    def test_a_later_stage_cannot_reask_a_decided_topic(self):
        self.sync()
        errors, _ = self.validate({"questions": [question("keep-days", "export-retention")]})
        self.assertTrue(any("already decided (PRD: retention)" in e for e in errors), errors)
        errors, _ = self.validate({"questions": [question("queue-type", "export-queue")]})
        self.assertEqual(errors, [])
        errors, _ = self.validate({"questions": [question("q1", "export-queue"),
                                                 question("q2", "export-queue")]})
        self.assertTrue(any("already asked by q1" in e for e in errors))
        errors, _ = self.validate({"questions": [question("untagged", "x")
                                                 | {"topic": None}]})
        self.assertTrue(any("topic is required" in e for e in errors))

    def test_one_follow_up_per_question(self):
        self.sync()
        follow = question("retention-legal", "export-retention", follow_up_of="retention")
        errors, _ = self.validate({"questions": [follow]})
        self.assertEqual(errors, [])
        # once the follow-up is recorded, a second one is refused
        hld = self.write("hld-context.json", {"decisions": [
            {"id": "retention-legal", "topic": "export-retention", "follow_up_of": "retention",
             "answer": "30 days unless legal hold", "source": "user-answer"}]})
        again = question("retention-again", "export-retention", follow_up_of="retention")
        errors, _ = self.validate({"questions": [again]}, decisions=hld)
        self.assertTrue(any("already had its one follow-up" in e for e in errors), errors)
        wrong = question("x", "export-format", follow_up_of="retention")
        errors, _ = self.validate({"questions": [wrong]})
        self.assertTrue(any("decided topic 'export-retention'" in e for e in errors))

    def test_settled_points_need_an_existing_source(self):
        self.sync()
        errors, out = self.validate({"questions": [], "audit": {"unresolved": [], "contradictions": []},
                                     "settled": [{"topic": "auth", "title": "Auth",
                                                  "decision": "Reuse SSO",
                                                  "source": "docs/missing.md#auth"}]})
        self.assertTrue(any("does not exist" in e for e in errors), errors)
        errors, out = self.validate({"questions": [], "audit": {"unresolved": [], "contradictions": []},
                                     "settled": [{"topic": "auth", "title": "Auth",
                                                  "decision": "Reuse SSO",
                                                  "source": ".maestro/runs/demo/requirement/prd.md:3"}]})
        self.assertEqual(errors, [])
        self.assertEqual(out["_settled_count"], 1)


if __name__ == "__main__":
    unittest.main()
