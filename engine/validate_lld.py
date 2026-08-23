#!/usr/bin/env python3
"""Deterministically validate Maestro's concise, buildable repository LLD contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SECTION_BUDGETS = {
    "change summary": 220,
    "existing seam": 420,
    "proposed changes": 700,
    "interfaces state and flows": 600,
    "failure and operational behavior": 420,
    "implementation sequence": 420,
    "verification": 420,
}
SECTION_ORDER = list(SECTION_BUDGETS)
TOTAL_BUDGET = 2600
PARENT_RE = re.compile(r"^\*\*Parent feature:\*\*\s+`?([^`\s]+)`?\s*$", re.I)
REPO_RE = re.compile(r"^\*\*Repository:\*\*\s+`?(.+?)`?\s*$", re.I)
STATUS_RE = re.compile(r"^\*\*Status:\*\*\s+Ready for review\s*$", re.I)
UNRESOLVED_RE = re.compile(r"\b(?:TBD|TODO|to be decided|decide later)\b", re.I)
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


def validate(path, parent_slug=None, repo=None):
    errors, warnings = [], []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read LLD: {exc}"], []

    sections, order = _sections(text)
    lines = text.splitlines()
    h1 = [line[2:].strip() for line in lines if re.match(r"^#\s+\S", line)]
    if len(h1) != 1:
        errors.append("document header: exactly one level-1 LLD title is required")
    elif not re.search(r"\b(?:lld|low level design)\b", h1[0], re.I):
        errors.append("document header: level-1 title must identify the document as an LLD")
    first_h2 = next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))
    preamble = lines[:first_h2]
    parent_matches = [PARENT_RE.match(line) for line in preamble if PARENT_RE.match(line)]
    repo_matches = [REPO_RE.match(line) for line in preamble if REPO_RE.match(line)]
    if not parent_matches:
        errors.append("document header: missing Parent feature metadata")
    elif parent_slug and parent_matches[0].group(1) != parent_slug:
        errors.append("document header: Parent feature does not match workflow input")
    if not repo_matches:
        errors.append("document header: missing Repository metadata")
    elif repo and repo_matches[0].group(1).strip("`") != repo:
        errors.append("document header: Repository does not match workflow input")
    if not any(STATUS_RE.match(line) for line in preamble):
        errors.append("document header: missing Status: Ready for review metadata")

    if order != SECTION_ORDER:
        errors.append("sections must use the exact required order")
    unknown = [name for name in order if name not in SECTION_BUDGETS]
    if unknown:
        errors.append("unexpected level-2 section(s): " + ", ".join(unknown))
    for name, budget in SECTION_BUDGETS.items():
        body = sections.get(name)
        if body is None:
            errors.append(f"missing section: {name}")
            continue
        count = len(_words(body))
        if count == 0:
            errors.append(f"empty section: {name}")
        elif count > budget:
            errors.append(f"{name}: {count} words exceeds {budget}")

    bullets = [line for line in sections.get("change summary", "").splitlines()
               if re.match(r"^\s*[-*]\s+\S", line)]
    if sections.get("change summary") and not 4 <= len(bullets) <= 7:
        errors.append("change summary must contain 4-7 bullets")
    seam = sections.get("existing seam", "")
    if seam and not re.search(r"`[^`]+`", seam):
        errors.append("existing seam must include at least one backticked code path or symbol")
    sequence = sections.get("implementation sequence", "")
    numbered = [line for line in sequence.splitlines() if re.match(r"^\s*\d+[.)]\s+\S", line)]
    if sequence and not 2 <= len(numbered) <= 10:
        errors.append("implementation sequence must contain 2-10 numbered increments")
    if UNRESOLVED_RE.search(text):
        errors.append("document contains an unresolved placeholder (TBD/TODO/decide later)")

    total = len(_words(text))
    if total > TOTAL_BUDGET:
        errors.append(f"document: {total} words exceeds {TOTAL_BUDGET}")
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
    parser.add_argument("--parent-slug")
    parser.add_argument("--repo")
    parser.add_argument("--report", action="store_true", help="always exit 0 for workflow routing")
    args = parser.parse_args(argv)
    errors, warnings = validate(args.path, parent_slug=args.parent_slug, repo=args.repo)
    issues = errors + warnings
    print(json.dumps({
        "valid": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues_summary": " | ".join(issues[:8]) if issues else "LLD structure and readability checks passed",
    }))
    return 0 if args.report or not errors else 1


if __name__ == "__main__":
    sys.exit(main())
