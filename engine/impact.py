#!/usr/bin/env python3
"""The feature's impact assessment: which repositories it changes, checked by the engine.

An agent reads the approved PRD and the codebase maps and writes impact.json:
  {"schema_version": 1,
   "repos": [{"name": "backend", "change": "what changes there, in one line"}],
   "interfaces_change": true,     # a call or event between repositories is added or changed
   "data_migration": false,       # stored data changes shape
   "infrastructure_change": false,
   "summary": "one line"}
Every repository must be one the workspace has (codebase/* or the root itself). Sizing decides
full or light design from it, and the LLD scope defaults to these repositories.

  impact.py validate --root . --impact <impact.json>
Prints one JSON line {valid, repos_csv, count, interfaces_change, data_migration,
infrastructure_change, issues_summary, summary}; always exits 0.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402

FLAGS = ("interfaces_change", "data_migration", "infrastructure_change")


def load(root, path):
    """-> (impact, issues). impact is None when the file is unusable."""
    full = path if os.path.isabs(path) else os.path.join(root, path)
    try:
        with open(full, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return None, [f"{path} is missing"]
    except (OSError, ValueError) as exc:
        return None, [f"{path} is not readable JSON: {exc}"]
    if not isinstance(doc, dict):
        return None, ["the impact assessment must be a JSON object"]
    issues = []
    discovered = {name.lower(): name for name, _path in codebase_scan.discover_repos(root)}
    repos = []
    items = doc.get("repos")
    if not isinstance(items, list) or not items:
        issues.append("repos must list at least one repository the feature changes")
        items = []
    for index, item in enumerate(items, 1):
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name.strip():
            issues.append(f"repos[{index}].name is required")
        elif name.strip().lower() not in discovered:
            issues.append(f"repos[{index}]: {name!r} is not a repository in this workspace "
                          f"({', '.join(sorted(discovered.values())) or 'none found'})")
        elif not isinstance(item.get("change"), str) or not item["change"].strip():
            issues.append(f"repos[{index}].change must say what changes in {name}")
        else:
            canonical = discovered[name.strip().lower()]
            if canonical not in repos:
                repos.append(canonical)
    for flag in FLAGS:
        if not isinstance(doc.get(flag), bool):
            issues.append(f"{flag} must be true or false")
    if issues:
        return None, issues
    return {"repos": repos, **{flag: doc[flag] for flag in FLAGS},
            "summary": str(doc.get("summary") or "").strip()}, []


def validate(root, path):
    impact, issues = load(root, path)
    if impact is None:
        return {"valid": False, "repos_csv": "", "count": 0,
                **{flag: False for flag in FLAGS},
                "issues_summary": " | ".join(issues[:8]),
                "summary": "Impact assessment is not valid"}
    changes = [label for flag, label in (("interfaces_change", "interfaces between repositories"),
                                          ("data_migration", "a data migration"),
                                          ("infrastructure_change", "infrastructure"))
               if impact[flag]]
    summary = (f"Changes {len(impact['repos'])} repositor{'y' if len(impact['repos']) == 1 else 'ies'}"
               f" ({', '.join(impact['repos'])})"
               + (f"; also {', '.join(changes)}" if changes else ""))
    return {"valid": True, "repos_csv": ",".join(impact["repos"]), "count": len(impact["repos"]),
            **{flag: impact[flag] for flag in FLAGS},
            "issues_summary": "Impact assessment is valid", "summary": summary}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate")
    p.add_argument("--root", default=".")
    p.add_argument("--impact", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(validate(args.root, args.impact)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
