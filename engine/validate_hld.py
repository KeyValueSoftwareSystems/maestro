#!/usr/bin/env python3
"""Deterministically validate Maestro's concise, skimmable HLD contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from validate_open_questions import validate as validate_open_questions
except ImportError:  # imported as a package (tests)
    from .validate_open_questions import validate as validate_open_questions


REQUIRED_SECTIONS = (
    "decision summary",
    "context and scope",
    "proposed design",
    "key decisions and trade offs",
    "delivery and risks",
    "open questions",
)
SECTION_ORDER = list(REQUIRED_SECTIONS)
FEATURE_SLUG_RE = re.compile(r"^\*\*Feature slug:\*\*\s+`?[^`\s]+`?\s*$", re.IGNORECASE)
STATUS_RE = re.compile(r"^\*\*Status:\*\*\s+Ready for review\s*$", re.IGNORECASE)
DECORATIVE_WORDS = (
    "robust", "seamless", "scalable", "leverage", "facilitate", "best-in-class",
)


def _normalise_heading(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _words(text):
    return re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE)


def _sections(text):
    found, order, current = {}, [], None
    for line in text.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = _normalise_heading(match.group(1))
            order.append(current)
            found.setdefault(current, [])
        elif current is not None:
            found[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in found.items()}, order


def _validate_deferred_ledger(path, open_body):
    errors = []
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read deferred-question ledger: {exc}"]
    schema_error = validate_open_questions(document)
    if schema_error:
        return [f"invalid deferred-question ledger: {schema_error}"]
    questions = document.get("questions", [])
    invalid = [question.get("id", "?") for question in questions
               if question.get("status") != "deferred"]
    if invalid:
        errors.append(
            "final deferred-question ledger may contain only deferred entries: "
            + ", ".join(invalid[:8])
        )
    says_none = open_body.strip().lower().rstrip(".") == "none"
    if questions and says_none:
        errors.append("open questions says None but deferred-question ledger is not empty")
    if not questions and not says_none:
        errors.append("open questions must say None when deferred-question ledger is empty")
    return errors


def validate(path, open_questions_path=None):
    errors, warnings = [], []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read HLD: {exc}"], []

    sections, order = _sections(text)
    lines = text.splitlines()
    h1 = [(index, line[2:].strip()) for index, line in enumerate(lines)
          if re.match(r"^#\s+\S", line)]
    if len(h1) != 1:
        errors.append("document header: exactly one level-1 HLD title is required")
    elif not re.search(r"\b(?:hld|high level design)\b", h1[0][1], re.I):
        errors.append("document header: level-1 title must identify the document as an HLD")
    first_h2 = next((index for index, line in enumerate(lines) if line.startswith("## ")),
                    len(lines))
    preamble = lines[:first_h2]
    if not any(FEATURE_SLUG_RE.match(line) for line in preamble):
        errors.append("document header: missing Feature slug metadata")
    if not any(STATUS_RE.match(line) for line in preamble):
        errors.append("document header: missing Status: Ready for review metadata")

    if order != SECTION_ORDER:
        errors.append("sections must use the exact required order")
    unknown = [name for name in order if name not in REQUIRED_SECTIONS]
    if unknown:
        errors.append("unexpected level-2 section(s): " + ", ".join(unknown))

    for name in REQUIRED_SECTIONS:
        body = sections.get(name)
        if body is None:
            errors.append(f"missing section: {name}")
            continue
        count = len(_words(body))
        if count == 0:
            errors.append(f"empty section: {name}")

    summary = sections.get("decision summary", "")
    summary_bullets = [line for line in summary.splitlines()
                       if re.match(r"^\s*[-*]\s+\S", line)]
    if summary and not 5 <= len(summary_bullets) <= 8:
        errors.append("decision summary must contain 5-8 bullets")

    if open_questions_path:
        errors.extend(_validate_deferred_ledger(
            open_questions_path, sections.get("open questions", ""),
        ))

    seen = set()
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        normal = re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()
        count = len(normal.split())
        if count >= 8 and normal in seen:
            errors.append(f"repeated sentence: {sentence.strip()[:100]}")
        if count >= 8:
            seen.add(normal)
        if count > 38:
            warnings.append(f"long sentence ({count} words): {sentence.strip()[:100]}")
    lower = text.lower()
    for word in DECORATIVE_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lower):
            warnings.append(f"decorative language: {word}")
    return errors, warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--open-questions")
    parser.add_argument("--report", action="store_true", help="always exit 0 for workflow routing")
    args = parser.parse_args(argv)
    errors, warnings = validate(args.path, open_questions_path=args.open_questions)
    issues = errors + warnings
    print(json.dumps({
        "valid": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues_summary": " | ".join(issues[:8]) if issues else "HLD structure and readability checks passed",
    }))
    return 0 if args.report or not errors else 1


if __name__ == "__main__":
    sys.exit(main())
