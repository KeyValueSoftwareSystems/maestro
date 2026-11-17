#!/usr/bin/env python3
"""Recognise a clarification stage whose question queue is already clear, without waking the lead.

HLD and LLD stages build a question queue (`.engine/queues/<stage>.json`) with the lead agent
(`prepare_*_questions`): it audits the decisions on record and writes an empty queue once nothing
material is left to ask. When a stage is entered again (a design rerun, a resumed session, a
retried step) with that clear queue still on disk, the lead used to redo the whole audit, or,
worse, hand-write the empty queue over a stage that was not settled, which an auto-mode safety
check refused: the run then sat idle for an hour.

This engine step never writes a queue and never settles anything new. It only recognises that the
lead's own earlier result still stands, and prints `clear` (the workflow then goes straight on to
write the document) when ALL of these hold; otherwise it prints `ask` and the lead builds the
queue as before:

  * no revision feedback is waiting;
  * the stage's queue file exists and is clear: no questions, no unresolved fact, no contradiction;
  * it passes the same check the lead's would (validate_prd_questions.py with --require-direction:
    a confirmed direction no earlier than the last answer, every topic accounted for);
  * it is newer than the person's last confirmed round, so the lead audited those answers;
  * none of the stage's input documents (the PRD, impact assessment, approved HLD, contract,
    docs) is newer than the queue: what the lead audited is still what is true.

  oq_settle.py --queue Q --decisions D [--log DIR] [--inputs a,b,c] [--feedback TEXT] [--root .]
      {"state": "clear" | "ask", "reason": "..."}   last stdout line, always exit 0
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_prd_questions as vq  # noqa: E402


def _ts(text):
    try:
        return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _last_confirmed(doc):
    stamps = [_ts(r.get("confirmed_at")) for r in doc.get("rounds") or [] if isinstance(r, dict)]
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None


def _split(value):
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def settle(queue, decisions, log=None, inputs=(), feedback="", root="."):
    """-> (state, reason): `clear` when the queue on disk is a clear one that still stands."""
    if (feedback or "").strip():
        return "ask", "revision feedback is waiting"
    if not os.path.isfile(queue):
        return "ask", "this stage has no queue yet"
    errors, _warnings, doc = vq.validate(
        queue, decisions_path=decisions, require_version=2, require_direction=True,
        log_path=log, require_topics=True, root=root)
    if errors or not isinstance(doc, dict):
        return "ask", "the queue on disk does not pass the check: " + (errors[0] if errors else "unreadable")
    audit = doc.get("audit") or {}
    if doc.get("questions") or audit.get("unresolved") or audit.get("contradictions"):
        return "ask", "the queue on disk still has something to ask"
    queued_at = os.stat(queue).st_mtime
    confirmed_at = _last_confirmed(vq._decisions_doc(decisions))
    if confirmed_at is not None and queued_at < confirmed_at:
        return "ask", "the person confirmed answers after this queue was written; they are not audited"
    for path in inputs:
        full = path if os.path.isabs(path) else os.path.join(root, path)
        try:
            if os.stat(full).st_mtime > queued_at:
                return "ask", f"{path} changed after the queue was audited"
        except OSError:
            continue  # an input this stage does not have
    return "clear", "the queue is clear, passes the check, and nothing it was audited against changed"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queue", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--log")
    parser.add_argument("--inputs", default="", help="comma-separated documents the stage reads")
    parser.add_argument("--feedback", default="")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    state, reason = settle(args.queue, args.decisions, log=args.log, inputs=_split(args.inputs),
                           feedback=args.feedback, root=args.root)
    print(json.dumps({"state": state, "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
