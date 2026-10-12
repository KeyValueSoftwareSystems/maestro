"""oq_serve.py / oq_record.py — the batched open-questions loop (workflows/design.yaml's
rq_*/oq_* cycles share these scripts on two different files).

Proves the batch contract: ALL open questions are served in one turn, malformed ledgers
fail closed, and omitted answers remain open rather than becoming implicit decisions."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import oq_serve  # noqa: E402
import oq_record  # noqa: E402


def run(fn, argv):
    """Run a script's main() with sys.argv patched; return (exit_code, parsed_stdout)."""
    buf = io.StringIO()
    old_argv = sys.argv
    sys.argv = ["prog"] + argv
    try:
        with redirect_stdout(buf):
            try:
                fn.main()
                code = 0
            except SystemExit as e:
                code = e.code or 0
    finally:
        sys.argv = old_argv
    out = buf.getvalue().strip()
    return code, (json.loads(out) if code == 0 and out else out)


def write_doc(path, questions):
    with open(path, "w") as fh:
        json.dump({"schema_version": 1, "feature_slug": "demo", "questions": questions}, fh)


def question(qid, status="open", options=("A", "B", "C")):
    resolution = None
    if status in ("resolved", "folded"):
        resolution = {"kind": "picked", "answer": options[0]}
    elif status == "deferred":
        resolution = {"kind": "skip", "answer": "Deferred to LLD"}
    return {"id": qid, "question": f"Q for {qid}?", "why": "because",
            "options": list(options), "status": status, "resolution": resolution}


class OqServeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="oq-serve-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, "open-questions.json")

    def test_missing_file_fails_closed(self):
        code, out = run(oq_serve, [os.path.join(self.tmp, "nope.json")])
        self.assertEqual(code, 1)

    def test_malformed_file_fails_closed(self):
        with open(self.path, "w") as fh:
            fh.write("not-json")
        code, _ = run(oq_serve, [self.path])
        self.assertEqual(code, 1)

    def test_schema_invalid_file_fails_closed(self):
        with open(self.path, "w") as fh:
            json.dump({"questions": []}, fh)
        code, _ = run(oq_serve, [self.path])
        self.assertEqual(code, 1)

    def test_no_open_questions_approves(self):
        write_doc(self.path, [question("q1", status="folded")])
        _, out = run(oq_serve, [self.path])
        self.assertEqual(out["state"], "approve")

    def test_resolved_unfolded_refines(self):
        write_doc(self.path, [question("q1", status="resolved")])
        _, out = run(oq_serve, [self.path])
        self.assertEqual(out["state"], "refine")

    def test_all_open_questions_served_in_one_batch(self):
        write_doc(self.path, [question("q1"), question("q2"), question("q3")])
        _, out = run(oq_serve, [self.path])
        self.assertEqual(out["state"], "ask")
        self.assertEqual(out["count"], 3)
        self.assertEqual(out["qids_csv"], "q1,q2,q3")
        # all three questions' text must appear in the ONE rendered block
        for qid in ("q1", "q2", "q3"):
            self.assertIn(f"Q for {qid}?", out["questions_md"])
            self.assertIn(f"(id: {qid})", out["questions_md"])

    def test_output_fields_are_scalars(self):
        # resolver._complete_script only parses the LAST stdout line and keeps only
        # scalar (str/int/float/bool) fields -- a list/dict output would silently vanish.
        write_doc(self.path, [question("q1"), question("q2")])
        _, out = run(oq_serve, [self.path])
        for v in out.values():
            self.assertIsInstance(v, (str, int, float, bool))


class OqRecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="oq-record-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, "open-questions.json")

    def _questions(self):
        with open(self.path) as fh:
            return json.load(fh)["questions"]

    def test_answer_all_positional(self):
        write_doc(self.path, [question("q1"), question("q2"), question("q3")])
        blob = "2\nyou decide\ncustom text for q3"
        code, out = run(oq_record, [self.path, "q1,q2,q3", "answer-all", blob])
        self.assertEqual(code, 0)
        self.assertEqual(out["recorded_count"], 3)
        qs = {q["id"]: q for q in self._questions()}
        self.assertEqual(qs["q1"]["resolution"], {"kind": "picked", "answer": "B"})
        self.assertEqual(qs["q1"]["status"], "resolved")
        self.assertEqual(qs["q2"]["resolution"]["kind"], "you-decide")
        self.assertEqual(qs["q3"]["resolution"], {"kind": "other", "answer": "custom text for q3"})

    def test_answer_all_skip_line(self):
        write_doc(self.path, [question("q1")])
        run(oq_record, [self.path, "q1", "answer-all", "skip"])
        q = self._questions()[0]
        self.assertEqual(q["status"], "deferred")
        self.assertEqual(q["resolution"]["kind"], "skip")

    def test_fewer_lines_than_questions_keeps_omitted_open(self):
        write_doc(self.path, [question("q1"), question("q2"), question("q3")])
        code, out = run(oq_record, [self.path, "q1,q2,q3", "answer-all", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(out["recorded_count"], 1)
        self.assertEqual(out["remaining_open"], 2)
        qs = {q["id"]: q for q in self._questions()}
        self.assertEqual(qs["q1"]["resolution"], {"kind": "picked", "answer": "A"})
        self.assertEqual(qs["q2"]["status"], "open")
        self.assertIsNone(qs["q2"]["resolution"])
        self.assertEqual(qs["q3"]["status"], "open")

    def test_blank_line_keeps_question_open(self):
        write_doc(self.path, [question("q1"), question("q2")])
        code, out = run(oq_record, [self.path, "q1,q2", "answer-all", "\n2"])
        self.assertEqual(code, 0)
        qs = {q["id"]: q for q in self._questions()}
        self.assertEqual(qs["q1"]["status"], "open")
        self.assertEqual(qs["q2"]["resolution"], {"kind": "picked", "answer": "B"})

    def test_decide_all(self):
        write_doc(self.path, [question("q1"), question("q2")])
        run(oq_record, [self.path, "q1,q2", "decide-all"])
        for q in self._questions():
            self.assertEqual(q["resolution"]["kind"], "you-decide")
            self.assertEqual(q["status"], "resolved")

    def test_skip_all(self):
        write_doc(self.path, [question("q1"), question("q2")])
        run(oq_record, [self.path, "q1,q2", "skip-all"])
        for q in self._questions():
            self.assertEqual(q["status"], "deferred")

    def test_unknown_qid_fails(self):
        write_doc(self.path, [question("q1")])
        code, out = run(oq_record, [self.path, "q1,ghost", "decide-all"])
        self.assertEqual(code, 1)

    def test_unknown_choice_fails(self):
        write_doc(self.path, [question("q1")])
        code, out = run(oq_record, [self.path, "q1", "bogus"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
