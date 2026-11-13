#!/usr/bin/env python3
"""Size a feature after PRD approval: the full design path, or the light path for a small change.

  sizing.py [--root .] --prd <prd.md> [--impact <impact.json>] [--path auto|full|light]

The light path skips the HLD and the contract: the PRD goes straight to the repository LLD,
readiness check and approval (the test cases are written from the PRD alongside, on either path). `auto` (the default) takes it when the impact
assessment (impact.py) classifies the feature `minor`, and the full path for `major`. Without a
valid assessment (a new product skips it, or it never validated) it falls back to the rules, all
of which must hold —
  - at most `design.light_max_criteria` acceptance criteria (maestro.config.yaml, default 5),
  - Non-functional requirements says None (no targets to design for),
  - the workspace holds exactly one repository,
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
import impact as impactmod  # noqa: E402
import validate_prd  # noqa: E402

MAX_CRITERIA = 5
PATHS = ("auto", "full", "light")


def max_criteria(root):
    try:
        import project_config
        config = project_config.load(root) or {}
    except Exception:  # an unreadable config is preflight's to report
        config = {}
    value = (config.get("design") or {}).get("light_max_criteria") \
        if isinstance(config, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 \
        else MAX_CRITERIA


def _scope_blockers(root):
    repos = codebase_scan.discover_repos(root)
    if len(repos) != 1:
        return [f"{len(repos)} repositories in the workspace (light needs exactly one)"]
    return []


def size(root, prd_path, requested="auto", impact_path=None):
    full = prd_path if os.path.isabs(prd_path) else os.path.join(root, prd_path)
    try:
        with open(full, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = ""
    if requested in ("full", "light"):
        return requested, [f"path {requested} requested at run start"]
    if impact_path:
        impact = impactmod.load(root, impact_path)[0]
        if impact:
            note = impact["summary"] or ", ".join(impact["repos"])
            return ("light" if impact["size"] == "minor" else "full",
                    [f"impact assessment classifies it as {impact['size']}: {note}"])
    criteria = ac_trace.prd_criteria(full)
    nfr = validate_prd._sections(text).get("non functional requirements", "").strip()
    limit = max_criteria(root)
    blockers = []
    if len(criteria) > limit:
        blockers.append(f"{len(criteria)} acceptance criteria (light allows {limit})")
    if not re.match(r"^none\b", nfr, re.IGNORECASE):
        blockers.append("non-functional targets to design for")
    blockers += _scope_blockers(root)
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
    parser.add_argument("--impact", default="",
                        help="the impact assessment; empty: size by the workspace's repositories")
    parser.add_argument("--path", default="auto")
    args = parser.parse_args(argv)
    requested = args.path if args.path in PATHS else "auto"
    path, reasons = size(args.root, args.prd, requested, args.impact or None)
    summary = ("Light path: PRD → LLD (no HLD or contract) — " if path == "light"
               else "Full design path — ") + "; ".join(reasons)
    print(json.dumps({"path": path, "reasons": "; ".join(reasons), "summary": summary}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
