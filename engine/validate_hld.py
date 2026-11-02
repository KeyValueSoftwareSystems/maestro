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
    "interfaces",
    "key decisions and trade offs",
    "delivery and risks",
    "open questions",
)
SECTION_ORDER = list(REQUIRED_SECTIONS)
# Required when the workspace defines infrastructure (infra_scan level containers or iac), allowed
# otherwise; always placed right after Interfaces.
INFRA_SECTION = "infrastructure and operations"
INFRA_LEVELS = ("none", "containers", "iac")
MERMAID_RE = re.compile(r"^\s*```\s*mermaid\b", re.M)
# Greenfield (the workspace has no code yet): the HLD decides the repositories to create, right
# after Context and scope, one bullet each: `name` (stack): purpose.
REPOS_SECTION = "repositories"
NEW_REPO_RE = re.compile(r"^\s*[-*]\s+`([a-z0-9][a-z0-9._-]*)`\s*\(([^)]+)\)\s*:\s*\S")
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


def interfaces_changed(sections):
    """True when the HLD names cross-repository interfaces; the contract step runs only then.

    The `Interfaces` section lists each call or event between repositories (one bullet or table
    row each), or says `None` when the feature changes no interface between repositories.
    """
    body = sections.get("interfaces", "").strip()
    return bool(body) and body.lower().rstrip(".") != "none"


def infra_changed(sections):
    """True when the HLD's Infrastructure and operations section lists changes (not None)."""
    body = sections.get(INFRA_SECTION, "").strip()
    return bool(body) and not re.match(r"^none\b", body, re.I)


def infra_owners(sections, repos):
    """Repositories the Infrastructure and operations bullets name as owners (`repo` in backticks)."""
    owners = []
    for line in sections.get(INFRA_SECTION, "").splitlines():
        for name in re.findall(r"`([^`]+)`", line):
            if name in repos and name not in owners:
                owners.append(name)
    return owners


def new_repositories(sections):
    """[(name, stack)] the Repositories section creates, in order."""
    found = []
    for line in sections.get(REPOS_SECTION, "").splitlines():
        match = NEW_REPO_RE.match(line)
        if match and match.group(1) not in [n for n, _s in found]:
            found.append((match.group(1), match.group(2).strip()))
    return found


def _expected_order(order, infra_level, greenfield=False):
    expected = list(SECTION_ORDER)
    if greenfield or REPOS_SECTION in order:
        expected.insert(expected.index("context and scope") + 1, REPOS_SECTION)
    if infra_level in ("containers", "iac") or INFRA_SECTION in order:
        expected.insert(expected.index("interfaces") + 1, INFRA_SECTION)
    return expected


def validate(path, open_questions_path=None, infra_level="none", repos=(), greenfield=False):
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

    expected = _expected_order(order, infra_level, greenfield)
    if greenfield:
        new = new_repositories(sections)
        if REPOS_SECTION not in sections:
            errors.append("missing section: repositories (the workspace has no code yet: list each "
                          "repository to create as `name` (stack): purpose)")
        elif not new:
            errors.append("repositories must list each repository to create as a bullet: "
                          "`name` (stack): purpose")
        repos = tuple(repos) + tuple(n for n, _s in new)
    if infra_level in ("containers", "iac") and INFRA_SECTION not in sections:
        errors.append(f"missing section: {INFRA_SECTION} (the workspace defines infrastructure: "
                      "list what this feature changes, or say None)")
    if order != expected:
        errors.append("sections must use the exact required order")
    unknown = [name for name in order if name not in expected]
    if unknown:
        errors.append("unexpected level-2 section(s): " + ", ".join(unknown))

    for name in [n for n in expected if n not in (INFRA_SECTION, REPOS_SECTION) or n in sections]:
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

    interfaces = sections.get("interfaces", "")
    if interfaces_changed(sections) and not re.search(r"^\s*(?:[-*]\s+\S|\|)", interfaces, re.M):
        errors.append("interfaces must list each cross-repository call or event as a bullet or "
                      "table row, or say None")

    infra = sections.get(INFRA_SECTION, "")
    if infra_changed(sections) and not re.search(r"^\s*(?:[-*]\s+\S|\|)", infra, re.M):
        errors.append("infrastructure and operations must list each change as a bullet or table "
                      "row, or say None")
    if infra_changed(sections) and repos:
        unowned = [line.strip() for line in infra.splitlines()
                   if re.match(r"^\s*(?:[-*]\s+\S|\|)", line) and not re.match(r"^\s*\|\s*-", line)
                   and not any(f"`{repo}`" in line for repo in repos)
                   and not re.match(r"^\s*\|\s*(?:repository|repo|owner)\b", line, re.I)]
        if unowned:
            errors.append("infrastructure and operations: name the repository that owns each "
                          f"change in backticks (one of: {', '.join(repos)}): {unowned[0][:80]}")
    if (interfaces_changed(sections) or infra_changed(sections)) and not MERMAID_RE.search(
            sections.get("proposed design", "")):
        errors.append("proposed design needs a ```mermaid architecture diagram when the feature "
                      "crosses repositories or changes infrastructure")

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
    parser.add_argument("--repos", default="",
                        help="workspace repositories, comma-separated: each infrastructure change "
                             "must name its owner")
    parser.add_argument("--greenfield", default="false",
                        help="true when the workspace has no code yet: the HLD must list the "
                             "repositories to create")
    parser.add_argument("--infra-level", choices=INFRA_LEVELS, default="none",
                        help="engine/infra_scan.py level: containers or iac require the "
                             "Infrastructure and operations section")
    parser.add_argument("--report", action="store_true", help="always exit 0 for workflow routing")
    args = parser.parse_args(argv)
    repos = [r.strip() for r in args.repos.split(",") if r.strip()]
    greenfield = str(args.greenfield).lower() == "true"
    errors, warnings = validate(args.path, open_questions_path=args.open_questions,
                                infra_level=args.infra_level, repos=repos, greenfield=greenfield)
    issues = errors + warnings
    try:
        sections, _order = _sections(Path(args.path).read_text(encoding="utf-8"))
    except OSError:
        sections = {}
    print(json.dumps({
        "valid": not errors,
        "interfaces_changed": interfaces_changed(sections),
        "infra_changed": infra_changed(sections),
        "infra_repos_csv": ",".join(infra_owners(sections, repos + [
            n for n, _s in new_repositories(sections)])),
        "new_repos_csv": ",".join(n for n, _s in new_repositories(sections)),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues_summary": " | ".join(issues[:8]) if issues else "HLD structure and readability checks passed",
    }))
    return 0 if args.report or not errors else 1


if __name__ == "__main__":
    sys.exit(main())
