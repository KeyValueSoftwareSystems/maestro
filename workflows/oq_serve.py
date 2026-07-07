#!/usr/bin/env python3
"""Serve the next state of the HLD open-question loop (Conductor design.yaml).

Reads open-questions.json and prints a JSON object to stdout describing what the
workflow should do next:

  {"state": "ask", "qid", "question", "why", "options_md"}  -> a question is open
  {"state": "refine"}                                        -> answers await folding
  {"state": "approve"}                                       -> nothing left to do

The `state` field is routed on in design.yaml. Exit 0 on success; exit 1 (with a
reason on stderr) if the file is missing or unparseable, which routes to abort.

Usage: python3 workflows/oq_serve.py <path-to-open-questions.json>
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
    if not path.is_file():
        fail(f"not found: {path}")
    try:
        doc = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        fail(f"invalid JSON: {e}")

    questions = doc.get("questions", [])

    # 1. Any open question -> ask the first one.
    for q in questions:
        if q.get("status") == "open":
            options_md = "\n".join(
                f"{i}. {opt}" for i, opt in enumerate(q["options"], start=1)
            )
            print(json.dumps({
                "state": "ask",
                "qid": q["id"],
                "question": q["question"],
                "why": q["why"],
                "options_md": options_md,
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
