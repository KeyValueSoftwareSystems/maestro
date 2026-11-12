#!/usr/bin/env python3
"""Confirm a repository's E2E suite before its command goes into maestro.config.yaml.

detect-stack proposes, per repository, the suite it found:

    {"command": "npm run test:e2e", "list": "npx playwright test --list",
     "framework": "playwright", "evidence": ["package.json", ".github/workflows/e2e.yml"]}

or that there is none: {"command": null, "reason": "no E2E framework or suite found"}.
This module decides; no person confirms it, so it leans toward "none":

1. `list` (the framework's list / collect / dry-run mode) is run in the repository, offline for
   npm (`npx` may not download). Exit 0 and at least one spec in its output (a known count line,
   test-file paths or Go test names) confirms the suite. An explicit count of zero ("Total: 0
   tests", "No tests found") means there is no suite, whatever the exit code or other evidence.
2. Otherwise (no list mode, or it could not run, e.g. dependencies not installed) the command
   must be wired up in a cited package.json, Makefile or CI file: a CI or Makefile line that runs
   it, or the script or target it invokes (`npm run X` / `pnpm X` / `yarn X` -> a package.json
   script `X`, `make X` -> a Makefile target `X`). Other files (framework configs, READMEs) and
   comments never confirm anything.

Anything else is recorded as `none` with the reason. -> verify(repo_path, proposal, log_path)

    e2e_check.py verify --repo <path> --proposal <json-file> [--log <path>]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repo_checks  # noqa: E402

LIST_TIMEOUT_S = 300
# "Total: 12 tests in 4 files" (Playwright), "7 tests collected" / "collected 7 items" (pytest),
# "Specs: 3" style summaries.
COUNT_PATTERNS = (
    re.compile(r"\bTotal:\s*(\d+)\s+tests?\b"),
    re.compile(r"\b(\d+)\s+tests?\s+collected\b"),
    re.compile(r"\bcollected\s+(\d+)\s+items?\b"),
    re.compile(r"\bno tests? (?:found|collected|ran)\b", re.I),
)
SPEC_FILE = re.compile(
    r"(\.(spec|test|e2e|cy)\.[cm]?[jt]sx?|\.feature|_test\.py|/test_\w+\.py|\.robot|"
    r"(Test|Tests|IT)\.(java|kt)|_spec\.rb)\s*$")
GO_TEST = re.compile(r"^(Test|Example|Benchmark|Fuzz)[A-Z0-9_]\w*\s*$")
SCRIPT_RUN = re.compile(r"^\s*(?:npm\s+run(?:-script)?|pnpm(?:\s+run)?|yarn(?:\s+run)?|bun\s+run)\s+"
                        r"([\w:.\-]+)")
MAKE_RUN = re.compile(r"^\s*make\s+(?:(?:-[CfI]|--directory|--file|--include-dir)\s+\S+\s+|-\S+\s+)*"
                      r"([\w.\-]+)")
# Files that can show a command is wired up: CI definitions, Makefiles, package.json.
CI_FILE = re.compile(r"(^|/)(\.github/workflows/[^/]+\.ya?ml|\.gitlab-ci\.ya?ml|Jenkinsfile|"
                     r"\.circleci/config\.ya?ml|azure-pipelines\.ya?ml|bitbucket-pipelines\.ya?ml|"
                     r"\.buildkite/[^/]+\.ya?ml|\.drone\.ya?ml)$")
MAKEFILES = ("makefile", "gnumakefile")
# npm / npx must not download packages while the engine probes a repository.
LIST_ENV = {"npm_config_yes": "false", "npm_config_offline": "true", "npm_config_audit": "false"}


def count_specs(output):
    """Specs the list output shows: an int, or None when the output says nothing recognizable."""
    for pattern in COUNT_PATTERNS:
        match = pattern.search(output)
        if match:
            return int(match.group(1)) if match.groups() else 0
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    files = [line for line in lines if SPEC_FILE.search(line)]
    if files:
        return len(files)
    tests = [line for line in lines if GO_TEST.match(line)]
    return len(tests) if tests else None


def _inside(repo_path, rel):
    full = os.path.realpath(os.path.join(repo_path, rel))
    root = os.path.realpath(repo_path)
    return full if full == root or full.startswith(root + os.sep) else None


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _runs(text, command):
    """True when a non-comment line runs `command` as a whole command, not a prefix of another."""
    pattern = re.compile(rf"(?<![\w\-./]){re.escape(command)}(?![\w\-./:])")
    for line in text.splitlines():
        body = line.strip()
        if body.startswith(("#", "//")):
            continue
        if pattern.search(body):
            return True
    return False


def wired_in(repo_path, command, evidence):
    """The cited CI file, Makefile or package.json that runs or defines `command`, or None."""
    command = command.strip()
    script = SCRIPT_RUN.match(command)
    target = MAKE_RUN.match(command)
    for rel in evidence or []:
        full = _inside(repo_path, str(rel))
        text = _read(full) if full and os.path.isfile(full) else None
        if text is None:
            continue
        rel_path = os.path.relpath(full, os.path.realpath(repo_path)).replace(os.sep, "/")
        name = os.path.basename(full)
        if (CI_FILE.search(rel_path) or name.lower() in MAKEFILES) and _runs(text, command):
            return str(rel)
        if script and name == "package.json":
            try:
                scripts = (json.loads(text) or {}).get("scripts") or {}
            except ValueError:
                scripts = {}
            if str(scripts.get(script.group(1)) or "").strip():
                return str(rel)
        if target and name.lower() in MAKEFILES:
            if re.search(rf"^{re.escape(target.group(1))}\s*:", text, re.M):
                return str(rel)
    return None


def _none(reason):
    return {"status": "none", "reason": reason}


def verify(repo_path, proposal, log_path):
    """-> {"status": "verified", "command", "framework", "method", "specs"?, "evidence"?}
    or {"status": "none", "reason"}."""
    if not isinstance(proposal, dict):
        return _none("no E2E suite reported")
    command = str(proposal.get("command") or "").strip()
    if not command or command.lower() == "none":
        return _none(str(proposal.get("reason") or "no E2E framework or suite found").strip())
    framework = str(proposal.get("framework") or "").strip()
    evidence = [str(item) for item in proposal.get("evidence") or [] if str(item).strip()]
    found = {"status": "verified", "command": command}
    if framework:
        found["framework"] = framework
    list_command = str(proposal.get("list") or "").strip()
    list_note = ""
    if list_command:
        result = repo_checks._run(list_command, repo_path, LIST_TIMEOUT_S, log_path, LIST_ENV)
        specs = count_specs(result["tail"])
        if specs == 0:
            return _none(f"`{list_command}` lists no specs")
        if specs and result["status"] == "passed":
            return {**found, "method": "list", "specs": specs}
        list_note = (f"`{list_command}` exited {result['exit_code']}" if result["status"] != "passed"
                     else f"`{list_command}` output shows no specs")
    source = wired_in(repo_path, command, evidence)
    if source:
        return {**found, "method": "evidence", "evidence": source}
    cited = ", ".join(evidence) or "nothing"
    reason = f"`{command}` is not run or defined in the cited files ({cited})"
    return _none(f"{list_note}; {reason}" if list_note else reason)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("verify")
    p.add_argument("--repo", required=True)
    p.add_argument("--proposal", required=True)
    p.add_argument("--log", default=None)
    args = parser.parse_args(argv)
    try:
        with open(args.proposal, encoding="utf-8") as fh:
            proposal = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"cannot read proposal: {exc}", file=sys.stderr)
        return 2
    log = args.log or os.path.join(tempfile.mkdtemp(prefix="maestro-e2e-"), "list.log")
    print(json.dumps(verify(args.repo, proposal, log)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
