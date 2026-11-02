#!/usr/bin/env python3
"""Acceptance-criteria trace: every PRD criterion -> the test cases that cover it -> their QA results.

  ac_trace.py design --prd P --test-cases T
      every AC-xx in the PRD is traced by at least one test case, and no case traces a criterion
      the PRD does not have. Prints {valid, ac_count, case_count, uncovered_csv, unknown_csv,
      issues_summary}; always exits 0 (the workflow routes on `valid`).

  ac_trace.py qa --prd P --test-cases T --results R --out O
      joins the trace with QA's per-case results and writes the trace table to O. Prints
      {all_passed, passing, failing, not_run, ac_count, path, summary}; exits 0.

Formats (the contract the test-case and QA steps write to):
  - PRD: `- AC-01: ...` bullets under `## Acceptance criteria` (validate_prd's strict contract).
  - Test cases: each case starts with a heading whose first token is its ID (`### TC-demo-001 —
    title`); every `AC-xx` in the case's body is a criterion it traces. Text before the first case
    (a coverage matrix, the header) is not counted, so only real cases prove coverage.
  - QA results: {"schema_version": 1, "cases": [{"id": "TC-...", "status": "passed" | "failed" |
    "skipped", "note": "..."}]}.

A criterion passes only when at least one of its cases ran and every case that ran passed.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_prd  # noqa: E402

AC_RE = re.compile(r"\bAC-(\d{2,})\b")
CASE_HEADING_RE = re.compile(r"^#{2,4}\s+\**(TC-[A-Za-z0-9_.-]+)")
STATUSES = ("passed", "failed", "skipped")


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def prd_criteria(path):
    """The PRD's acceptance-criterion IDs in order, e.g. ['AC-01', 'AC-02']."""
    text = _read(path)
    if text is None:
        return []
    body = validate_prd._sections(text).get("acceptance criteria", "")
    ids = []
    for line in body.splitlines():
        match = validate_prd.AC_LINE_RE.match(line)
        if match:
            ac = f"AC-{match.group(1)}"
            if ac not in ids:
                ids.append(ac)
    return ids


def test_cases(path):
    """{case_id: [criterion ids it traces]} in catalog order."""
    text = _read(path)
    cases, current, level = {}, None, 0
    for line in (text or "").splitlines():
        match = CASE_HEADING_RE.match(line)
        if match:
            current = match.group(1).rstrip(".")
            level = len(line) - len(line.lstrip("#"))
            cases.setdefault(current, [])
            continue
        heading = re.match(r"^(#+)\s", line)
        if current is not None and heading and len(heading.group(1)) <= level:
            current = None  # a journey or closing section ends the case; deeper headings don't
            continue
        if current is not None:
            for number in AC_RE.findall(line):
                ac = f"AC-{number}"
                if ac not in cases[current]:
                    cases[current].append(ac)
    return cases


def coverage(prd_path, cases_path):
    criteria = prd_criteria(prd_path)
    cases = test_cases(cases_path)
    covered = {ac: [case for case, traced in cases.items() if ac in traced] for ac in criteria}
    unknown = sorted({ac for traced in cases.values() for ac in traced} - set(criteria))
    issues = []
    if not criteria:
        issues.append("the PRD has no AC-xx acceptance criteria")
    if not cases:
        issues.append("the test-case catalog has no cases (headings starting with a TC- id)")
    uncovered = [ac for ac, ids in covered.items() if not ids]
    if uncovered and cases:
        issues.append("no test case traces " + ", ".join(uncovered))
    if unknown:
        issues.append("test cases trace criteria the PRD does not have: " + ", ".join(unknown))
    return criteria, cases, covered, uncovered, unknown, issues


def cmd_design(args):
    criteria, cases, _covered, uncovered, unknown, issues = coverage(args.prd, args.test_cases)
    print(json.dumps({
        "valid": not issues,
        "ac_count": len(criteria),
        "case_count": len(cases),
        "uncovered_csv": ",".join(uncovered),
        "unknown_csv": ",".join(unknown),
        "issues_summary": " | ".join(issues) if issues
        else f"All {len(criteria)} acceptance criteria are traced by test cases",
    }))
    return 0


def qa_results(path):
    """{case_id: (status, note)} from QA's results file; unreadable or malformed -> {}."""
    text = _read(path)
    try:
        document = json.loads(text) if text else {}
    except ValueError:
        return {}
    items = document.get("cases") if isinstance(document, dict) else None
    results = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            status = str(item.get("status", "")).strip().lower()
            results[item["id"].strip()] = (status if status in STATUSES else "skipped",
                                           str(item.get("note") or "").strip())
    return results


def verdict(case_ids, results):
    ran = [results[c][0] for c in case_ids if c in results and results[c][0] != "skipped"]
    if any(status == "failed" for status in ran):
        return "failing"
    return "passing" if ran else "not run"


def cmd_qa(args):
    criteria, _cases, covered, _uncovered, _unknown, _issues = coverage(args.prd, args.test_cases)
    results = qa_results(args.results)
    rows = [(ac, covered[ac], verdict(covered[ac], results)) for ac in criteria]
    counts = {name: sum(1 for row in rows if row[2] == name)
              for name in ("passing", "failing", "not run")}
    all_passed = bool(rows) and counts["passing"] == len(rows)
    summary = f"{counts['passing']}/{len(rows)} acceptance criteria passing"
    problems = [f"{ac} {state}" for ac, _ids, state in rows if state != "passing"]
    if problems:
        summary += " — " + ", ".join(problems[:6]) + (" …" if len(problems) > 6 else "")
    lines = ["# Acceptance-criteria trace", "", summary + ".", "",
             "| Criterion | Test cases | Result |", "|---|---|---|"]
    for ac, ids, state in rows:
        detail = ", ".join(f"{c} ({results[c][0]})" if c in results else f"{c} (no result)"
                           for c in ids) or "none"
        lines.append(f"| {ac} | {detail} | {state} |")
    failed_notes = [f"- {c}: {note}" for c, (status, note) in results.items()
                    if status == "failed" and note]
    if failed_notes:
        lines += ["", "## Failures", ""] + failed_notes
    out = args.out
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(json.dumps({
        "all_passed": all_passed,
        "passing": counts["passing"],
        "failing": counts["failing"],
        "not_run": counts["not run"],
        "ac_count": len(rows),
        "path": out,
        "summary": summary,
    }))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("design")
    p.add_argument("--prd", required=True)
    p.add_argument("--test-cases", required=True)
    p.set_defaults(fn=cmd_design)
    p = sub.add_parser("qa")
    p.add_argument("--prd", required=True)
    p.add_argument("--test-cases", required=True)
    p.add_argument("--results", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_qa)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
