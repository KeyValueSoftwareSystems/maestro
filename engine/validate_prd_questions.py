#!/usr/bin/env python3
"""Validate a feature-specific PRD clarification queue without using a model."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


MAX_QUESTIONS = 12
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
PRD_SECTION_TITLES = {
    "summary", "problem and context", "users and jobs", "goals and success signals",
    "non-goals", "functional scope", "constraints and assumptions", "acceptance criteria",
    "dependencies and risks", "priorities and phasing", "references",
}


def _words(value):
    return re.findall(r"\b[\w'-]+\b", value, flags=re.UNICODE)


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, str(exc)


def _decided_ids(path):
    if not path or not Path(path).exists():
        return set()
    doc, error = _read(path)
    if error or not isinstance(doc, dict):
        return set()
    items = doc.get("decisions") or doc.get("sections") or []
    return {
        item.get("id") for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def validate(path, decisions_path=None):
    errors, warnings = [], []
    doc, error = _read(path)
    if error:
        return [f"cannot read question queue: {error}"], [], None
    if not isinstance(doc, dict):
        return ["question queue must be a JSON object"], [], None
    if doc.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    questions = doc.get("questions")
    if not isinstance(questions, list):
        errors.append("questions must be an array")
        questions = []
    if len(questions) > MAX_QUESTIONS:
        errors.append(f"questions: {len(questions)} exceeds {MAX_QUESTIONS}")

    seen = set()
    decided = _decided_ids(decisions_path)
    for index, question in enumerate(questions, 1):
        where = f"questions[{index}]"
        if not isinstance(question, dict):
            errors.append(f"{where} must be an object")
            continue
        unknown = set(question) - {"id", "title", "question", "why", "proposal"}
        if unknown:
            errors.append(f"{where} has unknown field(s): {', '.join(sorted(unknown))}")
        for field in ("id", "title", "question", "why"):
            if not isinstance(question.get(field), str) or not question[field].strip():
                errors.append(f"{where}.{field} must be a non-empty string")
        qid = question.get("id")
        if isinstance(qid, str):
            if not ID_RE.match(qid):
                errors.append(f"{where}.id is invalid: {qid!r}")
            if qid in seen:
                errors.append(f"duplicate question id: {qid}")
            if qid in decided:
                errors.append(f"question already answered in an earlier round: {qid}")
            seen.add(qid)
        title = question.get("title")
        if isinstance(title, str) and title.strip().lower() in PRD_SECTION_TITLES:
            errors.append(f"{where}.title is a PRD section, not a product decision")
        prompt = question.get("question")
        if isinstance(prompt, str) and prompt.strip():
            if prompt.count("?") != 1 or not prompt.rstrip().endswith("?"):
                errors.append(f"{where}.question must ask exactly one decision")
            if len(_words(prompt)) > 45:
                errors.append(f"{where}.question exceeds 45 words")
            low = prompt.lower()
            if "is this section correct" in low or "what should the prd say" in low:
                errors.append(f"{where}.question is generic instead of feature-specific")
        why = question.get("why")
        if isinstance(why, str) and len(_words(why)) > 35:
            errors.append(f"{where}.why exceeds 35 words")
        proposal = question.get("proposal", "")
        if not isinstance(proposal, str):
            errors.append(f"{where}.proposal must be a string")
        elif len(_words(proposal)) > 90:
            errors.append(f"{where}.proposal exceeds 90 words")
        elif not proposal.strip():
            warnings.append(f"{where} has no grounded recommendation")
    return errors, warnings, doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--decisions", help="cumulative decision artifact from prior rounds")
    parser.add_argument("--report", action="store_true", help="always exit 0 for workflow routing")
    args = parser.parse_args(argv)
    errors, warnings, doc = validate(args.path, decisions_path=args.decisions)
    questions = doc.get("questions") if isinstance(doc, dict) else []
    count = len(questions) if isinstance(questions, list) else 0
    issues = errors + warnings
    print(json.dumps({
        "valid": not errors,
        "state": "clear" if not errors and count == 0 else "ask",
        "question_count": count,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues_summary": " | ".join(issues[:8]) if issues else "Question queue is valid",
    }))
    return 0 if args.report or not errors else 1


if __name__ == "__main__":
    sys.exit(main())
