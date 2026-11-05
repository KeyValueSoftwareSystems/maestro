#!/usr/bin/env python3
"""Size a feature after PRD approval: the full design path, or the light path for a small change.

  sizing.py [--root .] --prd <prd.md> [--path auto|full|light]

The light path skips the HLD and the contract: the PRD goes straight to the repository LLD,
readiness check, test cases and approval. `auto` (the default) takes it only when every rule holds —
  - at most MAX_CRITERIA acceptance criteria,
  - Non-functional requirements says None (no targets to design for),
  - the workspace has exactly one repository (nothing crosses repositories),
  - nothing in the PRD is still marked "(to confirm)".
`full` and `light` force a path (a person's choice at run start). Prints one JSON line
{path, reasons, summary}; always exits 0.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ac_trace  # noqa: E402
import codebase_scan  # noqa: E402
import validate_prd  # noqa: E402

MAX_CRITERIA = 5
PATHS = ("auto", "full", "light")


def size(root, prd_path, requested="auto"):
    full = prd_path if os.path.isabs(prd_path) else os.path.join(root, prd_path)
    try:
        with open(full, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = ""
    if requested in ("full", "light"):
        return requested, [f"path {requested} requested at run start"]
    criteria = ac_trace.prd_criteria(full)
    nfr = validate_prd._sections(text).get("non functional requirements", "").strip()
    repos = codebase_scan.discover_repos(root)
    blockers = []
    if len(criteria) > MAX_CRITERIA:
        blockers.append(f"{len(criteria)} acceptance criteria (light allows {MAX_CRITERIA})")
    if not re.match(r"^none\b", nfr, re.IGNORECASE):
        blockers.append("non-functional targets to design for")
    if len(repos) != 1:
        blockers.append(f"{len(repos)} repositories in the workspace (light needs exactly one)")
    if validate_prd.TO_CONFIRM_RE.search(text):
        blockers.append("PRD still has (to confirm) marks")
    if blockers:
        return "full", blockers
    return "light", [f"{len(criteria)} acceptance criteria, no non-functional targets, one repository"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".")
    parser.add_argument("--prd", required=True)
    parser.add_argument("--path", default="auto")
    args = parser.parse_args(argv)
    requested = args.path if args.path in PATHS else "auto"
    path, reasons = size(args.root, args.prd, requested)
    summary = ("Light path: PRD → LLD → test cases (no HLD or contract) — " if path == "light"
               else "Full design path — ") + "; ".join(reasons)
    print(json.dumps({"path": path, "reasons": "; ".join(reasons), "summary": summary}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
