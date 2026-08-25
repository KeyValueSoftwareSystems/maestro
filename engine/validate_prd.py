#!/usr/bin/env python3
"""Deterministically validate Maestro's concise, skimmable PRD contract."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = (
    "summary",
    "problem and context",
    "users and jobs",
    "goals and success signals",
    "non goals",
    "functional scope",
    "constraints and assumptions",
    "acceptance criteria",
    "dependencies and risks",
    "priorities and phasing",
    "references",
)
AC_LINE_RE = re.compile(r"^\s*[-*]\s+(?:\*\*)?AC-(\d{2,})(?:\*\*)?:\s+\S")
NON_AC_CODE_RE = re.compile(r"\b(?:AC-\d+|FR-?\d+|REQ-?\d+|B-?\d+)\b", re.IGNORECASE)
FEATURE_SLUG_RE = re.compile(r"^\*\*Feature slug:\*\*\s+`?[^`\s]+`?\s*$", re.IGNORECASE)
STATUS_RE = re.compile(r"^\*\*Status:\*\*\s+Ready for review\s*$", re.IGNORECASE)
AC_PREFIX_RE = re.compile(r"^(\s*[-*]\s+)(?:\*\*)?AC-\d{2,}(?:\*\*)?:\s*", re.IGNORECASE)

# Existing PRDs do not share a universal heading standard. The fast-path compatibility mode
# accepts common equivalents while generated Maestro PRDs still use the exact headings above.
HEADING_ALIASES = {
    "executive summary": "summary",
    "overview": "summary",
    "problem statement": "problem and context",
    "background": "problem and context",
    "target users": "users and jobs",
    "personas": "users and jobs",
    "jobs to be done": "users and jobs",
    "goals": "goals and success signals",
    "objectives": "goals and success signals",
    "goals and metrics": "goals and success signals",
    "success metrics": "goals and success signals",
    "out of scope": "non goals",
    "functional requirements": "functional scope",
    "requirements": "functional scope",
    "scope": "functional scope",
    "constraints": "constraints and assumptions",
    "assumptions": "constraints and assumptions",
    "assumptions and constraints": "constraints and assumptions",
    "definition of done": "acceptance criteria",
    "dependencies": "dependencies and risks",
    "risks": "dependencies and risks",
    "risks and dependencies": "dependencies and risks",
    "priorities": "priorities and phasing",
    "phasing": "priorities and phasing",
    "roadmap": "priorities and phasing",
    "milestones": "priorities and phasing",
    "links": "references",
}


def _normalise_heading(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _words(text):
    return re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE)


def _sections(text, compatible=False):
    found = {}
    current = None
    for line in text.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = _normalise_heading(match.group(1))
            if compatible:
                current = HEADING_ALIASES.get(current, current)
            found.setdefault(current, [])
        elif current is not None:
            found[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in found.items()}


def _normalize_acceptance_criteria(text):
    """Apply syntax-only AC fixes without changing any product words."""
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines)
                  if _normalise_heading(line[3:]) == "acceptance criteria"
                  and line.startswith("## ")), None)
    if start is None:
        return text, []
    end = next((index for index in range(start + 1, len(lines))
                if lines[index].startswith("## ")), len(lines))

    body = lines[start + 1:end]
    prefix_blanks = []
    suffix_blanks = []
    while body and not body[0].strip():
        prefix_blanks.append(body.pop(0))
    while body and not body[-1].strip():
        suffix_blanks.insert(0, body.pop())

    normalized, current = [], None
    joined = False
    for line in body:
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^[-*]\s+", stripped):
            if current is not None:
                normalized.append(current)
            current = stripped
        elif current is not None and line[:1].isspace():
            current += " " + stripped
            joined = True
        else:
            if current is not None:
                normalized.append(current)
                current = None
            normalized.append(stripped)
    if current is not None:
        normalized.append(current)

    renumbered = False
    ac_number = 0
    for index, line in enumerate(normalized):
        if AC_PREFIX_RE.match(line):
            ac_number += 1
            replacement = AC_PREFIX_RE.sub(
                lambda match: f"{match.group(1)}AC-{ac_number:02d}: ", line, count=1,
            )
            if replacement != line:
                renumbered = True
            normalized[index] = replacement

    new_lines = lines[:start + 1] + prefix_blanks + normalized + suffix_blanks + lines[end:]
    result = "\n".join(new_lines) + ("\n" if text.endswith("\n") else "")
    fixes = []
    if joined:
        fixes.append("joined wrapped acceptance-criteria lines")
    if renumbered:
        fixes.append("renumbered acceptance criteria sequentially")
    return result, fixes


def apply_mechanical_fixes(path):
    """Normalize safe Markdown syntax and atomically replace the file when changed."""
    target = Path(path)
    try:
        original = target.read_text(encoding="utf-8")
    except OSError:
        return []
    updated, fixes = _normalize_acceptance_criteria(original)
    if updated == original:
        return []
    tmp = target.with_name(f"{target.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(updated, encoding="utf-8")
        os.replace(tmp, target)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return fixes


def validate(path, compatible=False):
    errors, warnings = [], []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read PRD: {exc}"], []
    sections = _sections(text, compatible=compatible)
    if not compatible:
        lines = text.splitlines()
        h1 = [(index, line[2:].strip()) for index, line in enumerate(lines)
              if re.match(r"^#\s+\S", line)]
        if len(h1) != 1:
            errors.append("document header: exactly one level-1 PRD title is required")
        elif not re.search(r"\b(?:prd|product requirements document)\b", h1[0][1], re.I):
            errors.append("document header: level-1 title must identify the document as a PRD")
        first_h2 = next((index for index, line in enumerate(lines) if line.startswith("## ")),
                        len(lines))
        preamble = lines[:first_h2]
        if not any(FEATURE_SLUG_RE.match(line) for line in preamble):
            errors.append("document header: missing Feature slug metadata")
        if not any(STATUS_RE.match(line) for line in preamble):
            errors.append("document header: missing Status: Ready for review metadata")
    for name in REQUIRED_SECTIONS:
        body = sections.get(name)
        if body is None:
            errors.append(f"missing section: {name}")
            continue
        count = len(_words(body))
        if count == 0:
            errors.append(f"empty section: {name}")

    if not compatible:
        acceptance = sections.get("acceptance criteria", "")
        ac_ids = []
        for line in acceptance.splitlines():
            if not line.strip():
                continue
            match = AC_LINE_RE.match(line)
            if not match:
                errors.append(
                    "acceptance criteria: each non-empty line must be a bullet beginning AC-01:"
                )
                continue
            ac_ids.append(int(match.group(1)))
        if ac_ids and ac_ids != list(range(1, len(ac_ids) + 1)):
            errors.append("acceptance criteria: IDs must be unique and sequential from AC-01")
        for name, body in sections.items():
            if name == "acceptance criteria":
                continue
            codes = sorted(set(NON_AC_CODE_RE.findall(body)))
            if codes:
                errors.append(
                    f"{name}: traceability codes are allowed only in acceptance criteria: "
                    + ", ".join(codes[:5])
                )

    seen = {}
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        normal = re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()
        count = len(normal.split())
        if count >= 8:
            if normal in seen:
                errors.append(f"repeated sentence: {sentence.strip()[:100]}")
            seen[normal] = True
        if count > 35:
            warnings.append(f"long sentence ({count} words): {sentence.strip()[:100]}")
    return errors, warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument(
        "--report", action="store_true",
        help="always exit 0 so a workflow can route on the JSON `valid` field",
    )
    parser.add_argument(
        "--compatible", action="store_true",
        help="accept common equivalent headings when checking an existing third-party PRD",
    )
    parser.add_argument(
        "--fix-mechanical", action="store_true",
        help="atomically normalize safe Markdown syntax before validation",
    )
    args = parser.parse_args(argv)
    fixes = apply_mechanical_fixes(args.path) if args.fix_mechanical else []
    errors, warnings = validate(args.path, compatible=args.compatible)
    issues = errors + warnings
    print(json.dumps({
        "valid": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "changed": bool(fixes),
        "fixes": fixes,
        "issues_summary": " | ".join(issues[:8]) if issues else "PRD structure and clarity checks passed",
    }))
    return 0 if args.report or not errors else 1


if __name__ == "__main__":
    sys.exit(main())
