#!/usr/bin/env python3
"""Record a gate answer into open-questions.json (the design workflow's OQ loop).

Given the question id, the gate choice, and the free-text answer, updates the
matching question's `status` and `resolution` in place, then re-validates the file.

Choice mapping (the ask_question gate options in workflows/design.yaml):
  answer      -> status resolved; a bare integer N picks options[N-1] (kind
                 'picked'), anything else is stored verbatim (kind 'other')
  you-decide  -> status resolved; kind 'you-decide' (refine_hld chooses a default)
  skip        -> status deferred; kind 'skip'

Usage: python3 engine/oq_record.py <path> <qid> <choice> [answer]
Exit 0 = OK; exit 1 = FAIL (reason on stderr).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_open_questions import validate  # noqa: E402


def fail(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) not in (4, 5):
        fail("usage: oq_record.py <path> <qid> <choice> [answer]")
    path = Path(sys.argv[1])
    qid, choice = sys.argv[2], sys.argv[3]
    answer_text = sys.argv[4] if len(sys.argv) == 5 else ""
    if not path.is_file():
        fail(f"not found: {path}")

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        fail(f"{path} is not readable JSON: {exc}")
    q = next((q for q in doc.get("questions", []) if q.get("id") == qid), None)
    if q is None:
        fail(f"unknown question id: {qid}")

    if choice == "answer":
        text = answer_text.strip()
        if not text:
            fail(f"question {qid}: 'answer' choice needs non-empty text")
        opts = q.get("options") or []
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

    # Validate BEFORE writing so a bad transition never lands on disk.
    error = validate(doc)
    if error:
        fail(f"would produce an invalid file: {error}")
    path.write_text(json.dumps(doc, indent=2) + "\n")

    print(json.dumps({"recorded": qid, "kind": q["resolution"]["kind"]}))


if __name__ == "__main__":
    main()
