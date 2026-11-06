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

  findings.py verdict --findings F [--previous P] [--round N] [--max-rounds M] [--commit C]
                      [--root .]
      {valid, blocking, blocking_count, late, late_count, late_csv, round, max_rounds,
       limit_reached, revise, summary} — blocking means a blocking finding is open or upheld. An unreadable or
      malformed file is not valid (the workflow re-runs the reviewer).
      Re-review rounds are bounded here, not in the reviewer's prose:
        late           with --previous (the findings file as it was before this review), a
                       blocking finding that is new in this round and not marked
                       `"introduced_by_revision": true` is late — it was there to find earlier. It
                       is reported to the person at the gate, never another revision round.
        limit_reached  --round (this review's visit count, `${steps.<review>.visits}`) has reached
                       the limit: --max-rounds, else `reviews.max_rounds` in maestro.config.yaml,
                       else 3. Remaining findings go to the person.
        revise         route on this: blocking, valid and the limit not reached.
      With --commit (the code commit reviewed), a valid verdict is also written beside the findings
      as reviewed.json {commit, blocking, summary}: the release reads it to show whether the
      shipped commit was code-reviewed.
  findings.py resolve --findings F --resolutions R
      {state, fixed_csv, contested_csv, escalated_csv, missing_csv, summary}:
        proceed     every blocking finding is fixed or contested (re-review next), or none is open
        escalate    the author escalated one, or contested a finding the reviewer already upheld
                    (a finding is contested at most once)
        incomplete  a blocking finding has no resolution (back to the author)
      A resolutions file older than the findings file answers an earlier review round and is
      ignored, so the author must answer the current round.
Both always exit 0; workflows route on the fields.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SEVERITIES = ("blocking", "major", "minor")
STATUSES = ("open", "upheld", "withdrawn", "resolved")
RESOLUTIONS = ("fixed", "contested", "escalated")
ACTIVE = ("open", "upheld")
DEFAULT_MAX_ROUNDS = 3


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except FileNotFoundError:
        return None, f"{path} is missing"
    except (OSError, ValueError) as exc:
        return None, f"{path} is not readable JSON: {exc}"


def _older(path, than):
    """True when `path` was last written before `than` (an earlier round's answers)."""
    return os.stat(path).st_mtime_ns < os.stat(than).st_mtime_ns


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
        if not isinstance(item.get("introduced_by_revision", False), bool):
            problems.append(f"{fid}: introduced_by_revision must be true or false")
        for field in ("finding", "evidence"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                problems.append(f"{fid}: {field} is required")
        findings.append({**item, "status": item.get("status", "open")})
    return findings, problems


def blocking(findings):
    return [f for f in findings if f.get("severity") == "blocking" and f["status"] in ACTIVE]


def previous_ids(path):
    """Finding ids an earlier round raised, or None when there was no earlier round."""
    if not path or not os.path.exists(path):
        return None
    doc, error = _read(path)
    items = doc.get("findings") if isinstance(doc, dict) and not error else None
    if not isinstance(items, list):
        return None
    return {item.get("id") for item in items if isinstance(item, dict)}


def max_rounds(root, requested=None):
    if requested:
        return requested
    try:
        import project_config
        config = project_config.load(root) or {}
    except Exception:  # an unreadable config is preflight's to report, not the review's
        config = {}
    value = (config.get("reviews") or {}).get("max_rounds") if isinstance(config, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 \
        else DEFAULT_MAX_ROUNDS


def _round(text):
    try:
        return max(0, int(str(text).strip() or 0))
    except ValueError:
        return 0


def cmd_verdict(args):
    findings, problems = load_findings(args.findings)
    round_no, limit = _round(args.round), max_rounds(args.root, args.max_rounds)
    # the first review of a stage entry is never late, whatever an earlier pass left behind
    earlier = previous_ids(args.previous) if round_no != 1 else None
    active, late = [], []
    for finding in blocking(findings):
        if (earlier is not None and finding["id"] not in earlier
                and finding.get("introduced_by_revision") is not True):
            late.append(finding)
        else:
            active.append(finding)
    limit_reached = bool(round_no) and round_no >= limit
    is_blocking = bool(active) or bool(problems)
    if problems:
        summary = "Review findings are malformed: " + "; ".join(problems[:4])
    elif active:
        summary = f"{len(active)} blocking finding(s): " + ", ".join(
            f"{f['id']} ({f.get('area', 'general')})" for f in active[:6])
        if limit_reached:
            summary += f" — review round limit reached ({round_no}/{limit}): a person decides"
    else:
        summary = f"No blocking findings ({len(findings)} finding(s) in total)"
    if late:
        summary += (f"; {len(late)} late blocking finding(s) raised only on re-review, for the "
                    f"person: " + ", ".join(f["id"] for f in late[:6]))
    print(json.dumps({"valid": not problems, "blocking": is_blocking,
                      "blocking_count": len(active), "late": bool(late), "late_count": len(late),
                      "late_csv": ",".join(f["id"] for f in late), "round": round_no,
                      "max_rounds": limit, "limit_reached": limit_reached,
                      "revise": is_blocking and not problems and not limit_reached,
                      "summary": summary}))
    if args.commit and not problems:
        path = os.path.join(os.path.dirname(os.path.abspath(args.findings)), "reviewed.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "commit": args.commit,
                       "blocking": bool(active or late), "summary": summary}, fh, indent=2)
            fh.write("\n")
    return 0


def cmd_resolve(args):
    findings, problems = load_findings(args.findings)
    active = {f["id"]: f for f in blocking(findings)}
    if problems or not active:
        print(json.dumps({"state": "proceed", "fixed_csv": "", "contested_csv": "",
                          "escalated_csv": "", "missing_csv": "",
                          "summary": "No blocking findings to resolve"}))
        return 0
    doc = None
    if os.path.exists(args.resolutions) and not _older(args.resolutions, args.findings):
        doc, _error = _read(args.resolutions)
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
    p.add_argument("--previous", help="the findings file as it was before this review round")
    p.add_argument("--round", default="", help="this review's visit count")
    p.add_argument("--max-rounds", type=int)
    p.add_argument("--commit", help="the code commit reviewed: record it in reviewed.json")
    p.add_argument("--root", default=".")
    p.set_defaults(fn=cmd_verdict)
    p = sub.add_parser("resolve")
    p.add_argument("--findings", required=True)
    p.add_argument("--resolutions", required=True)
    p.set_defaults(fn=cmd_resolve)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
