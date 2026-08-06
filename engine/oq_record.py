#!/usr/bin/env python3
"""Record answers for a BATCH of open questions into open-questions.json (the design
workflow's OQ loop) in ONE call.

oq_serve.py's "ask" state now serves EVERY open question in a single turn (qids_csv +
questions_md) instead of one question per round-trip, so this recorder applies the
human's one combined reply back onto all of them at once — collapsing what used to be
N serial gate turns (serve/ask/record per question) into a single serve/ask/record.

Choices (the ask gate options in workflows/design.yaml):
  answer-all  -> parse `blob`, ONE LINE PER QID, in the SAME ORDER as qids_csv. Each
                 line is itself one of: a bare integer (picks that option), "skip",
                 "you decide"/"default" (case-insensitive), or free text (stored
                 verbatim). Fail-soft: a missing line (fewer lines than qids) resolves
                 that question as you-decide rather than erroring — a Q&A formatting
                 slip should never abort the whole design run.
  decide-all  -> every qid resolved as you-decide; no blob needed.
  skip-all    -> every qid deferred; no blob needed.

Usage: python3 engine/oq_record.py <path> <qids_csv> <choice> [blob]
Exit 0 = OK; exit 1 = FAIL (reason on stderr) — only for structural problems (bad path,
unknown qid, unknown choice), never for a line-count mismatch in `blob`.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_open_questions import validate  # noqa: E402


def fail(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def apply_choice(q, choice, answer_text=""):
    """Apply one answer to a question dict IN PLACE. Raises ValueError on a bad
    choice or an empty 'answer'."""
    if choice == "answer":
        text = (answer_text or "").strip()
        if not text:
            raise ValueError(f"question {q.get('id')}: 'answer' choice needs non-empty text")
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
        raise ValueError(f"unknown choice: {choice}")


def _parse_line(line):
    """One blob line -> (choice, answer_text) for apply_choice."""
    text = line.strip()
    if not text or text.lower() == "skip":
        return "skip", ""
    if text.lower() in ("you decide", "you-decide", "default"):
        return "you-decide", ""
    return "answer", text


def main():
    if len(sys.argv) not in (4, 5):
        fail("usage: oq_record.py <path> <qids_csv> <choice> [blob]")
    path = Path(sys.argv[1])
    qids = [q for q in sys.argv[2].split(",") if q]
    choice = sys.argv[3]
    blob = sys.argv[4] if len(sys.argv) == 5 else ""
    if not path.is_file():
        fail(f"not found: {path}")
    if not qids:
        fail("empty qids_csv")

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        fail(f"{path} is not readable JSON: {exc}")
    by_id = {q.get("id"): q for q in doc.get("questions", [])}
    missing = [qid for qid in qids if qid not in by_id]
    if missing:
        fail(f"unknown question id(s): {', '.join(missing)}")

    recorded = []
    if choice == "decide-all":
        for qid in qids:
            apply_choice(by_id[qid], "you-decide")
            recorded.append(qid)
    elif choice == "skip-all":
        for qid in qids:
            apply_choice(by_id[qid], "skip")
            recorded.append(qid)
    elif choice == "answer-all":
        lines = blob.splitlines()
        for i, qid in enumerate(qids):
            if i < len(lines):
                line_choice, text = _parse_line(lines[i])
            else:
                # fewer lines than questions -> fail-soft default, never abort the run
                line_choice, text = "you-decide", ""
            try:
                apply_choice(by_id[qid], line_choice, text)
            except ValueError:
                # an "answer" line that was empty after strip -> same fail-soft default
                apply_choice(by_id[qid], "you-decide")
            recorded.append(qid)
    else:
        fail(f"unknown choice: {choice}")

    # Validate BEFORE writing so a bad transition never lands on disk.
    error = validate(doc)
    if error:
        fail(f"would produce an invalid file: {error}")
    path.write_text(json.dumps(doc, indent=2) + "\n")

    print(json.dumps({"recorded_count": len(recorded), "recorded_csv": ",".join(recorded)}))


if __name__ == "__main__":
    main()
