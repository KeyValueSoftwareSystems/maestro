#!/usr/bin/env python3
"""Serve the next state of the HLD open-question loop (workflows/design.yaml).

Reads open-questions.json and prints a JSON object to stdout describing what the
workflow should do next:

  {"state": "ask", "count", "qids_csv", "questions_md"}  -> 1+ questions are open,
                                                             ALL served together
  {"state": "refine"}                                    -> answers await folding
  {"state": "approve"}                                   -> nothing left to do

ALL open questions are served in one batch (not one at a time) so the human answers
every open question in a SINGLE gate turn instead of one round-trip per question —
oq_record_batch.py applies the combined reply back. qids_csv/questions_md are strings
(not the per-repo list) on purpose: `complete --stdout` (resolver._complete_script)
only parses the LAST line of stdout as JSON and keeps only scalar output fields.

The design workflow's script node routes on the `state` output field — the canonical
example of the "script stdout JSON becomes routable outputs" pattern.

Usage: python3 engine/oq_serve.py <path-to-open-questions.json>
"""
import json
import sys
from pathlib import Path
from typing import NoReturn


def fail(msg: str) -> NoReturn:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: oq_serve.py <path-to-open-questions.json>")
    path = Path(sys.argv[1])
    # Fail-soft (matches the ledger's corrupt-file handling): a missing or
    # unparseable file means "no open questions" -> approve. This keeps resume
    # working when guard_hld routes a done HLD into serve, and stays safe for HLDs
    # authored before open-questions.json existed.
    if not path.is_file():
        print(f"[oq] no open-questions file at {path}; treating as resolved", file=sys.stderr)
        print(json.dumps({"state": "approve"}))
        return
    try:
        doc = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"[oq] WARNING: unparseable {path} ({e}); treating as resolved", file=sys.stderr)
        print(json.dumps({"state": "approve"}))
        return

    questions = doc.get("questions", [])

    # 1. Any open questions -> ask ALL of them in one batch, most-decisive-first
    # (the order the skill already writes them in) — one gate turn, not N.
    open_qs = [q for q in questions if q.get("status") == "open"]
    if open_qs:
        blocks = []
        for i, q in enumerate(open_qs, start=1):
            options_md = "\n".join(
                f"   {j}. {opt}" for j, opt in enumerate(q["options"], start=1)
            )
            blocks.append(
                f"{i}. **{q['question']}** (id: {q['id']})\n"
                f"   Why: {q['why']}\n{options_md}"
            )
        print(json.dumps({
            "state": "ask",
            "count": len(open_qs),
            "qids_csv": ",".join(q["id"] for q in open_qs),
            "questions_md": "\n\n".join(blocks),
        }))
        return

    # 2. Any resolved-but-unfolded answer -> refine the HLD.
    if any(q.get("status") == "resolved" for q in questions):
        print(json.dumps({"state": "refine"}))
        return

    # 3. Nothing open, nothing to fold -> proceed to approval.
    print(json.dumps({"state": "approve"}))


if __name__ == "__main__":
    main()
