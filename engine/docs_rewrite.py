#!/usr/bin/env python3
"""Does a knowledge refresh rewrite docs a person has verified? (a route-only `script` node)

  docs_rewrite.py check [--root .] [--plan <workspace_sync plan json>]

Reads the living docs under docs/ (architecture and one doc per domain) and, optionally, the
freshness plan that says why a refresh is due. A rewrite resets every doc it changes to
`status: draft`, so when any doc is `reviewed` (`verified` before format 4) the person approves
first.

stdout: {"needs_approval": bool, "doc_count": n, "verified_count": n, "summary": "<3 lines>"}
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import living_docs  # noqa: E402


def _why(plan):
    k = (plan or {}).get("knowledge") or {}
    parts = []
    if k.get("stale_repos"):
        parts.append("code changed since the docs were written: " + ", ".join(k["stale_repos"]))
    if k.get("removed_repos"):
        parts.append("repos removed: " + ", ".join(k["removed_repos"]))
    if k.get("format_stale"):
        parts.append(f"docs predate format {living_docs.FORMAT_VERSION}")
    if k.get("docs_hash_stale"):
        parts.append("docs were edited since the last index")
    if (plan or {}).get("map_stale_repos"):
        parts.append("codebase maps are stale: " + ", ".join(plan["map_stale_repos"]))
    return "; ".join(parts) or "the freshness check found them out of date"


def check(root, plan_path=None):
    docs = living_docs.load_docs(os.path.abspath(root))
    verified = sum(1 for d in docs if d.fm.get("status") in living_docs.REVIEWED)
    plan = None
    if plan_path and os.path.isfile(plan_path):
        with open(plan_path, encoding="utf-8") as fh:
            plan = json.load(fh)
    kinds = {k: sum(1 for d in docs if d.kind == k) for k in ("architecture", "domain")}
    summary = "\n".join([
        f"- docs/ holds {len(docs)} living docs ({kinds['architecture']} architecture, "
        f"{kinds['domain']} domain); {verified} reviewed by a person.",
        f"- A refresh will update them in place because {_why(plan)}.",
        "- Rewritten docs go back to `draft` for re-verification; the team's invariants and change "
        "scenarios are restored untouched, and the generated blocks are regenerated.",
    ])
    return {"needs_approval": verified > 0, "doc_count": len(docs),
            "verified_count": verified, "summary": summary}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check"])
    ap.add_argument("--root", default=".")
    ap.add_argument("--plan")
    a = ap.parse_args(argv[1:])
    print(json.dumps(check(a.root, a.plan)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
