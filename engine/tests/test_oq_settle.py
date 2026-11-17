"""oq_settle.py: the engine recognises a clear question queue that still stands, and never settles
anything new: it writes nothing, and anything doubtful goes to the lead."""
import datetime
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import oq_settle  # noqa: E402

CONFIRMED = "2026-11-13T10:32:31Z"
CONFIRMED_EPOCH = datetime.datetime(2026, 11, 13, 10, 32, 31,
                                    tzinfo=datetime.timezone.utc).timestamp()


def decision(did, kind="decision", source="accepted-proposal"):
    return {"id": did, "title": did, "kind": kind, "question": "q", "why": "w", "proposal": "p",
            "must_resolve": [], "answer": "a", "source": source, "confirmed_at": CONFIRMED}


class SettleTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="oq-settle-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.queue = os.path.join(self.root, ".engine", "queues", "hld.json")
        self.decisions = os.path.join(self.root, "decisions", "hld.json")
        os.makedirs(os.path.dirname(self.decisions))
        os.makedirs(os.path.dirname(self.queue))
        self.prd = os.path.join(self.root, "prd.md")
        with open(self.prd, "w") as fh:
            fh.write("prd\n")
        self.touch(self.prd, -7200)  # the PRD is older than the audit
        self.write_decisions([decision("d1"), decision("hld-direction", "direction")])
        self.write_queue([])
        self.touch(self.queue, 3600)  # audited an hour after the last confirmed round

    def touch(self, path, offset):
        stamp = CONFIRMED_EPOCH + offset
        os.utime(path, (stamp, stamp))

    def write_decisions(self, items):
        with open(self.decisions, "w") as fh:
            json.dump({"schema_version": 1, "decisions": items, "rounds": [
                {"confirmed_at": CONFIRMED, "question_ids": [i["id"] for i in items]}]}, fh)

    def write_queue(self, questions, unresolved=()):
        with open(self.queue, "w") as fh:
            json.dump({"schema_version": 2, "questions": questions, "settled": [], "audit": {
                "unresolved": list(unresolved), "contradictions": []}}, fh)

    def settle(self, **kw):
        kw.setdefault("inputs", [self.prd])
        return oq_settle.settle(self.queue, self.decisions, root=self.root, **kw)

    def read_queue(self):
        if not os.path.exists(self.queue):
            return None
        with open(self.queue) as fh:
            return fh.read()

    def asks(self, why, **kw):
        before = self.read_queue()
        state, reason = self.settle(**kw)
        self.assertEqual(state, "ask", reason)
        self.assertIn(why, reason)
        self.assertEqual(before, self.read_queue())

    def test_a_clear_queue_audited_after_the_last_round_still_stands(self):
        before = self.read_queue()
        state, reason = self.settle()
        self.assertEqual(state, "clear", reason)
        self.assertEqual(self.read_queue(), before, "recognising a queue never rewrites it")

    def test_feedback_asks(self):
        self.asks("feedback", feedback="rethink the ownership")

    def test_no_queue_yet_asks(self):
        os.remove(self.queue)
        self.asks("no queue")

    def test_a_queue_with_questions_or_unresolved_facts_asks(self):
        self.write_queue([{"id": "q1", "title": "t", "question": "q", "why": "w", "proposal": "p",
                           "topic": "t1"}], unresolved=["x"])
        self.assertEqual(self.settle()[0], "ask")  # fails the check or still has something to ask

    def test_a_queue_that_fails_the_direction_check_asks(self):
        self.write_decisions([decision("d1")])  # answers, but the direction was never confirmed
        self.asks("does not pass the check")

    def test_answers_confirmed_after_the_queue_was_written_ask(self):
        self.touch(self.queue, -60)  # written before the person's last round
        self.asks("not audited")

    def test_an_input_newer_than_the_queue_asks(self):
        self.touch(self.prd, 7200)
        self.asks("prd.md changed after")
        # a document this stage does not have is simply not part of it
        self.assertEqual(self.settle(inputs=[os.path.join(self.root, "absent.json")])[0], "clear")

    def test_the_command_prints_one_json_line(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = oq_settle.main(["--queue", self.queue, "--decisions", self.decisions,
                                   "--inputs", self.prd, "--root", self.root])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue().strip().splitlines()[-1])["state"], "clear")
        out = io.StringIO()
        with redirect_stdout(out):
            oq_settle.main(["--queue", self.queue, "--decisions", self.decisions,
                            "--root", self.root, "--feedback", "change it"])
        self.assertEqual(json.loads(out.getvalue().strip().splitlines()[-1])["state"], "ask")


if __name__ == "__main__":
    unittest.main()
