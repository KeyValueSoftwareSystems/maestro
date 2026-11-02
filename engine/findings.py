#!/usr/bin/env python3
"""Review findings the author fixes, contests or escalates — decided by the engine, not by prose.

A reviewer writes its findings as JSON next to its report:
  {"schema_version": 1, "findings": [{"id": "F1", "severity": "blocking" | "major" | "minor",
    "area": "...", "finding": "...", "evidence": "...",
    "status": "open" | "upheld" | "withdrawn" | "resolved"}]}
New findings are `open`. On a re-review the reviewer marks a fixed finding `resolved`, accepts a
contest by marking it `withdrawn`, or keeps it `upheld`.

The author answers every blocking finding still open or upheld:
  {"schema_version": 1, "resolutions": [{"id": "F1", "resolution": "fixed" | "contested" |
    "escalated", "note": "what changed, or why the finding is wrong, or what a person must decide"}]}

  findings.py verdict --findings F
      {valid, blocking, blocking_count, summary} — blocking means a blocking finding is open or
      upheld. An unreadable or malformed file is not valid (the workflow re-runs the reviewer).
  findings.py resolve --findings F --resolutions R
      {state, fixed_csv, contested_csv, escalated_csv, missing_csv, summary}:
        proceed     every blocking finding is fixed or contested (re-review next), or none is open
        escalate    the author escalated one, or contested a finding the reviewer already upheld
                    (a finding is contested at most once)
        incomplete  a blocking finding has no resolution (back to the author)
Both always exit 0; workflows route on the fields.
"""
import argparse
import json
import os
import sys

SEVERITIES = ("blocking", "major", "minor")
STATUSES = ("open", "upheld", "withdrawn", "resolved")
RESOLUTIONS = ("fixed", "contested", "escalated")
ACTIVE = ("open", "upheld")


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except FileNotFoundError:
        return None, f"{path} is missing"
    except (OSError, ValueError) as exc:
        return None, f"{path} is not readable JSON: {exc}"


def load_findings(path):
    """-> (findings, problems)."""
    doc, error = _read(path)
    if error:
        return [], [error]
    items = doc.get("findings") if isinstance(doc, dict) else None
    if not isinstance(items, list):
        return [], ["findings must be an array"]
    problems, seen, findings = [], set(), []
    for index, item in enumerate(items, 1):
        where = f"findings[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{where} must be an object")
            continue
        fid = item.get("id")
        if not isinstance(fid, str) or not fid.strip():
            problems.append(f"{where}.id is required")
            continue
        if fid in seen:
            problems.append(f"duplicate finding id {fid}")
        seen.add(fid)
        if item.get("severity") not in SEVERITIES:
            problems.append(f"{fid}: severity must be one of {', '.join(SEVERITIES)}")
        if item.get("status", "open") not in STATUSES:
            problems.append(f"{fid}: status must be one of {', '.join(STATUSES)}")
        for field in ("finding", "evidence"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                problems.append(f"{fid}: {field} is required")
        findings.append({**item, "status": item.get("status", "open")})
    return findings, problems


def blocking(findings):
    return [f for f in findings if f.get("severity") == "blocking" and f["status"] in ACTIVE]


def cmd_verdict(args):
    findings, problems = load_findings(args.findings)
    active = blocking(findings)
    if problems:
        summary = "Review findings are malformed: " + "; ".join(problems[:4])
    elif active:
        summary = f"{len(active)} blocking finding(s): " + ", ".join(
            f"{f['id']} ({f.get('area', 'general')})" for f in active[:6])
    else:
        summary = f"No blocking findings ({len(findings)} finding(s) in total)"
    print(json.dumps({"valid": not problems, "blocking": bool(active) or bool(problems),
                      "blocking_count": len(active), "summary": summary}))
    return 0


def cmd_resolve(args):
    findings, problems = load_findings(args.findings)
    active = {f["id"]: f for f in blocking(findings)}
    if problems or not active:
        print(json.dumps({"state": "proceed", "fixed_csv": "", "contested_csv": "",
                          "escalated_csv": "", "missing_csv": "",
                          "summary": "No blocking findings to resolve"}))
        return 0
    doc, error = _read(args.resolutions) if os.path.exists(args.resolutions) else (None, None)
    items = doc.get("resolutions") if isinstance(doc, dict) else None
    answers = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("id") in active \
                and item.get("resolution") in RESOLUTIONS:
            answers[item["id"]] = item
    missing = [fid for fid in active if fid not in answers]
    by = {kind: [fid for fid, a in answers.items() if a["resolution"] == kind]
          for kind in RESOLUTIONS}
    recontested = [fid for fid in by["contested"] if active[fid]["status"] == "upheld"]
    escalated = by["escalated"] + recontested
    if escalated:
        state = "escalate"
        summary = "Needs a person: " + "; ".join(
            f"{fid} — {answers[fid].get('note', '').strip() or active[fid]['finding']}"
            + (" (contest already rejected by the reviewer)" if fid in recontested else "")
            for fid in escalated[:4])
    elif missing:
        state = "incomplete"
        summary = "No resolution yet for " + ", ".join(missing)
    else:
        state = "proceed"
        summary = (f"{len(by['fixed'])} fixed, {len(by['contested'])} contested — "
                   "the reviewer checks them next")
    print(json.dumps({"state": state, "fixed_csv": ",".join(by["fixed"]),
                      "contested_csv": ",".join(fid for fid in by["contested"]
                                                if fid not in recontested),
                      "escalated_csv": ",".join(escalated), "missing_csv": ",".join(missing),
                      "summary": summary}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("verdict")
    p.add_argument("--findings", required=True)
    p.set_defaults(fn=cmd_verdict)
    p = sub.add_parser("resolve")
    p.add_argument("--findings", required=True)
    p.add_argument("--resolutions", required=True)
    p.set_defaults(fn=cmd_resolve)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
