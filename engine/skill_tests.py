#!/usr/bin/env python3
"""Skill behaviour tests: scripted prompts with expected and forbidden output.

Cheap regression tests for skill edits, before the full evaluation set. Each case is a YAML file
(the engine's YAML subset) under a cases directory, one folder per skill:

  skill: hld-interview                 # the installed skill the case exercises
  name: no-infra-questions-without-infra
  prompt: |                            # self-contained: everything the skill needs is inline
    ...
  must_include: ["regex", ...]         # each must match the output (case-insensitive)
  must_not_include: ["regex", ...]     # none may match

Running a case needs a model, so the lead runs them; checking them does not:

  skill_tests.py list   [--dir evals/skills] [--skill S]   cases as JSON: {id, skill, prompt}
  skill_tests.py check  [--dir evals/skills] --outputs D [--skill S]
        reads D/<id>.txt (the agent's full reply for case <id>) and reports every expectation
        that failed; a missing output counts as failed. Exit 0 only when every case passes.

Run each listed case in a fresh subagent told to "load and follow the `<skill>` skill", with the
case prompt as its whole task, and save its reply as <outputs>/<id>.txt.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wf  # noqa: E402

DEFAULT_DIR = os.path.join("evals", "skills")


def load_cases(directory, skill=None):
    cases = []
    for dirpath, _dirs, files in os.walk(directory):
        for name in sorted(files):
            if not name.endswith((".yaml", ".yml")):
                continue
            path = os.path.join(dirpath, name)
            doc = wf.load_file(path)
            case_id = f"{doc.get('skill')}--{doc.get('name')}"
            if skill and doc.get("skill") != skill:
                continue
            cases.append({"id": case_id, "path": path, **doc})
    return sorted(cases, key=lambda c: c["id"])


def problems(case):
    """Why a case file is malformed ([] = fine)."""
    issues = []
    for key in ("skill", "name", "prompt"):
        if not isinstance(case.get(key), str) or not case[key].strip():
            issues.append(f"{key} is required")
    for key in ("must_include", "must_not_include"):
        value = case.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            issues.append(f"{key} must be a list of regexes")
            continue
        for pattern in value:
            try:
                re.compile(pattern)
            except re.error as exc:
                issues.append(f"{key}: bad regex {pattern!r}: {exc}")
    if not case.get("must_include") and not case.get("must_not_include"):
        issues.append("a case needs at least one expectation")
    return issues


def check(case, output):
    failures = []
    for pattern in case.get("must_include") or []:
        if not re.search(pattern, output, re.IGNORECASE | re.MULTILINE):
            failures.append(f"missing expected: {pattern}")
    for pattern in case.get("must_not_include") or []:
        hit = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
        if hit:
            failures.append(f"forbidden output: {pattern} (matched {hit.group(0)[:60]!r})")
    return failures


def cmd_list(args):
    cases = load_cases(args.dir, args.skill)
    print(json.dumps([{"id": c["id"], "skill": c["skill"], "prompt": c["prompt"]} for c in cases],
                     indent=2))
    return 0


def cmd_check(args):
    results = []
    for case in load_cases(args.dir, args.skill):
        malformed = problems(case)
        out_path = os.path.join(args.outputs, f"{case['id']}.txt")
        if malformed:
            failures = [f"case file: {p}" for p in malformed]
        elif not os.path.isfile(out_path):
            failures = [f"no output recorded at {out_path}"]
        else:
            with open(out_path, encoding="utf-8", errors="replace") as fh:
                failures = check(case, fh.read())
        results.append({"id": case["id"], "passed": not failures, "failures": failures})
    passed = sum(1 for r in results if r["passed"])
    print(json.dumps({"passed": passed, "failed": len(results) - passed,
                      "summary": f"{passed}/{len(results)} skill behaviour tests passed",
                      "results": results}, indent=2))
    return 0 if results and passed == len(results) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn in (("list", cmd_list), ("check", cmd_check)):
        p = sub.add_parser(name)
        p.add_argument("--dir", default=DEFAULT_DIR)
        p.add_argument("--skill")
        if name == "check":
            p.add_argument("--outputs", required=True)
        p.set_defaults(fn=fn)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
