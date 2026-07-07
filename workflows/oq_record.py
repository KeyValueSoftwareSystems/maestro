#!/usr/bin/env python3
"""Record a gate answer into open-questions.json (Conductor design.yaml loop).

Given the question id, the gate choice, and the free-text answer, updates the
matching question's `status` and `resolution` in place, then re-validates the
file against the schema.

Choice mapping (the gate option values in design.yaml):
  answer      -> status resolved; a bare integer N picks options[N-1] (kind
                 'picked'), anything else is stored verbatim (kind 'other')
  you-decide  -> status resolved; kind 'you-decide' (refine_hld chooses a default)
  skip        -> status deferred; kind 'skip'

Usage: python3 workflows/oq_record.py <path> <qid> <choice> [answer]
Exit 0 = OK; exit 1 = FAIL (reason on stderr).
"""
import json
import sys
from pathlib import Path
from typing import NoReturn


def fail(msg: str) -> NoReturn:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) not in (4, 5):
        fail("usage: oq_record.py <path> <qid> <choice> [answer]")
    path = Path(sys.argv[1])
    qid, choice = sys.argv[2], sys.argv[3]
    answer_text = sys.argv[4] if len(sys.argv) == 5 else ""
    if not path.is_file():
        fail(f"not found: {path}")

    doc = json.loads(path.read_text())
    q = next((q for q in doc.get("questions", []) if q.get("id") == qid), None)
    if q is None:
        fail(f"unknown question id: {qid}")

    if choice == "answer":
        text = answer_text.strip()
        if not text:
            fail(f"question {qid}: 'answer' choice needs non-empty text")
        opts = q["options"]
        if text.isdigit() and 1 <= int(text) <= len(opts):
            resolution = {"kind": "picked", "answer": opts[int(text) - 1]}
        else:
            resolution = {"kind": "other", "answer": text}
        q["status"] = "resolved"
        q["resolution"] = resolution
    elif choice == "you-decide":
        q["status"] = "resolved"
        q["resolution"] = {"kind": "you-decide", "answer": "(plan's discretion — refine picks a default)"}
    elif choice == "skip":
        q["status"] = "deferred"
        q["resolution"] = {"kind": "skip", "answer": "Deferred to LLD"}
    else:
        fail(f"unknown choice: {choice}")

    path.write_text(json.dumps(doc, indent=2) + "\n")

    # Re-validate so a bad write fails the step (routes to abort).
    validator = Path(__file__).with_name("validate_open_questions.py")
    import subprocess
    r = subprocess.run([sys.executable, str(validator), str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"post-write validation failed: {r.stderr.strip()}")

    print(f"OK: recorded {qid} ({q['resolution']['kind']})")


if __name__ == "__main__":
    main()
