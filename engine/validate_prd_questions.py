#!/usr/bin/env python3
"""Validate a feature-specific PRD clarification queue without using a model."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


MAX_QUESTIONS = 12
MAX_RESOLUTION_FACTS = 4
MAX_ALTERNATIVES = 2
QUESTION_KINDS = {"decision", "direction"}
# Sources that confirm a decision. A parked (`deferred`) answer never confirms a direction.
CONFIRMING_SOURCES = {
    "accepted-proposal", "chosen-alternative", "user-answer", "assumption", "legacy-confirmed",
}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
PRD_SECTION_TITLES = {
    "summary", "problem and context", "users and jobs", "goals and success signals",
    "non-goals", "functional scope", "constraints and assumptions", "acceptance criteria",
    "dependencies and risks", "priorities and phasing", "references",
    "decision summary", "context and scope", "proposed design",
    "key decisions and trade-offs", "delivery and risks", "open questions",
    "change summary", "existing seam", "proposed changes", "data model and migrations",
    "api and client contract", "state and flows", "failure and operational behavior",
    "implementation sequence", "verification",
}


def _words(value):
    return re.findall(r"\b[\w'-]+\b", value, flags=re.UNICODE)


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, str(exc)


def _decisions_doc(path):
    if not path or not Path(path).exists():
        return {}
    doc, error = _read(path)
    if error or not isinstance(doc, dict):
        return {}
    return doc


def _decided_ids(doc):
    items = doc.get("decisions") or doc.get("sections") or []
    return {
        item.get("id") for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _direction_error(doc):
    """Why an empty queue may not close yet, or None when the direction is confirmed.

    The human must confirm the overall design direction after every other decision, so the
    document is never written from answers the human has not seen assembled together."""
    decisions = [item for item in doc.get("decisions") or [] if isinstance(item, dict)]
    rounds = [item for item in doc.get("rounds") or [] if isinstance(item, dict)]
    round_of = {}
    for index, round_ in enumerate(rounds):
        for qid in round_.get("question_ids") or []:
            round_of[qid] = index
    confirmed = [
        round_of.get(item.get("id"), -1) for item in decisions
        if item.get("kind") == "direction" and item.get("source") in CONFIRMING_SOURCES
    ]
    if not confirmed:
        return ("empty queue requires a confirmed design direction: ask one question with "
                "kind \"direction\" summarising the intended design")
    latest_other = max(
        (round_of.get(item.get("id"), -1) for item in decisions
         if item.get("kind") != "direction"),
        default=-1,
    )
    if max(confirmed) < latest_other:
        return ("design direction predates later decisions: ask a new kind \"direction\" "
                "question that reflects them")
    return None


def _validate_alternatives(where, alternatives, proposal, errors):
    if not isinstance(alternatives, list):
        errors.append(f"{where}.alternatives must be an array")
        return
    if len(alternatives) > MAX_ALTERNATIVES:
        errors.append(
            f"{where}.alternatives has {len(alternatives)} entries; maximum is {MAX_ALTERNATIVES}"
        )
    labels = set()
    if isinstance(proposal, str) and proposal.strip():
        labels.add(proposal.strip().lower())
    for index, alternative in enumerate(alternatives, 1):
        at = f"{where}.alternatives[{index}]"
        if not isinstance(alternative, dict):
            errors.append(f"{at} must be an object")
            continue
        unknown = set(alternative) - {"label", "tradeoff"}
        if unknown:
            errors.append(f"{at} has unknown field(s): {', '.join(sorted(unknown))}")
        label = alternative.get("label")
        tradeoff = alternative.get("tradeoff")
        if not isinstance(label, str) or not label.strip():
            errors.append(f"{at}.label must be a non-empty string")
        else:
            if len(_words(label)) > 12:
                errors.append(f"{at}.label exceeds 12 words")
            if label.strip().lower() in labels:
                errors.append(f"{at}.label repeats the proposal or another alternative")
            labels.add(label.strip().lower())
        if not isinstance(tradeoff, str) or not tradeoff.strip():
            errors.append(f"{at}.tradeoff must be a non-empty string")
        elif len(_words(tradeoff)) > 30:
            errors.append(f"{at}.tradeoff exceeds 30 words")


def validate(path, decisions_path=None, require_version=None, require_direction=False):
    errors, warnings = [], []
    doc, error = _read(path)
    if error:
        return [f"cannot read question queue: {error}"], [], None
    if not isinstance(doc, dict):
        return ["question queue must be a JSON object"], [], None
    schema_version = doc.get("schema_version")
    if schema_version not in (1, 2):
        errors.append("schema_version must be 1 or 2")
    if require_version is not None and schema_version != require_version:
        errors.append(f"schema_version must be {require_version} for this workflow")
    questions = doc.get("questions")
    if not isinstance(questions, list):
        errors.append("questions must be an array")
        questions = []
    if len(questions) > MAX_QUESTIONS:
        errors.append(f"questions: {len(questions)} exceeds {MAX_QUESTIONS}")

    seen = set()
    decisions_doc = _decisions_doc(decisions_path)
    decided = _decided_ids(decisions_doc)
    for index, question in enumerate(questions, 1):
        where = f"questions[{index}]"
        if not isinstance(question, dict):
            errors.append(f"{where} must be an object")
            continue
        allowed = {"id", "title", "question", "why", "proposal"}
        if schema_version == 2:
            allowed.update({"must_resolve", "alternatives", "kind"})
        unknown = set(question) - allowed
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
        kind = question.get("kind", "decision")
        if kind not in QUESTION_KINDS:
            errors.append(f"{where}.kind must be one of {sorted(QUESTION_KINDS)}")
        proposal = question.get("proposal", "")
        proposal_limit = 150 if kind == "direction" else 90
        if not isinstance(proposal, str):
            errors.append(f"{where}.proposal must be a string")
        elif len(_words(proposal)) > proposal_limit:
            errors.append(f"{where}.proposal exceeds {proposal_limit} words")
        elif not proposal.strip():
            if kind == "direction":
                errors.append(f"{where}.proposal must summarise the intended design direction")
            else:
                warnings.append(f"{where} has no grounded recommendation")
        if "alternatives" in question:
            _validate_alternatives(where, question["alternatives"], proposal, errors)

        if schema_version == 2:
            must_resolve = question.get("must_resolve")
            if not isinstance(must_resolve, list) or not must_resolve:
                errors.append(f"{where}.must_resolve must be a non-empty array")
            elif len(must_resolve) > MAX_RESOLUTION_FACTS:
                errors.append(
                    f"{where}.must_resolve has {len(must_resolve)} facts; "
                    f"maximum is {MAX_RESOLUTION_FACTS}"
                )
            else:
                for fact_index, fact in enumerate(must_resolve, 1):
                    if not isinstance(fact, str) or not fact.strip():
                        errors.append(
                            f"{where}.must_resolve[{fact_index}] must be a non-empty string"
                        )
                    elif len(_words(fact)) > 16:
                        errors.append(
                            f"{where}.must_resolve[{fact_index}] exceeds 16 words"
                        )

    if schema_version == 2:
        audit = doc.get("audit")
        if not isinstance(audit, dict):
            errors.append("audit must be an object for schema_version 2")
        else:
            unknown = set(audit) - {"unresolved", "contradictions"}
            if unknown:
                errors.append(f"audit has unknown field(s): {', '.join(sorted(unknown))}")
            for field in ("unresolved", "contradictions"):
                values = audit.get(field)
                if not isinstance(values, list):
                    errors.append(f"audit.{field} must be an array")
                elif any(not isinstance(value, str) or not value.strip() for value in values):
                    errors.append(f"audit.{field} must contain only non-empty strings")
            if questions and not audit.get("unresolved") and not audit.get("contradictions"):
                errors.append("non-empty queue must name an unresolved fact or contradiction")
            if not questions:
                unresolved = audit.get("unresolved")
                contradictions = audit.get("contradictions")
                if unresolved:
                    errors.append("empty queue cannot declare unresolved decision facts")
                if contradictions:
                    errors.append("empty queue cannot declare decision contradictions")
    if require_direction and not questions:
        direction_error = _direction_error(decisions_doc)
        if direction_error:
            errors.append(direction_error)
    return errors, warnings, doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--decisions", help="cumulative decision artifact from prior rounds")
    parser.add_argument("--require-version", type=int, choices=(1, 2))
    parser.add_argument(
        "--require-direction", action="store_true",
        help="an empty queue also needs a confirmed kind=direction decision newer than the rest",
    )
    parser.add_argument("--report", action="store_true", help="always exit 0 for workflow routing")
    args = parser.parse_args(argv)
    errors, warnings, doc = validate(
        args.path, decisions_path=args.decisions, require_version=args.require_version,
        require_direction=args.require_direction,
    )
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
