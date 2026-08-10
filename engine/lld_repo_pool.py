#!/usr/bin/env python3
"""Repo-scoped LLD dispatch — the deterministic half of "one LLD per repo, any repo count."

`parallel` workflow nodes have a FIXED branch count declared in the YAML — they cannot spin up
one branch per discovered repo. So design.yaml instead declares a small, fixed pool of
"slot" branches; each slot loops: claim the next unclaimed repo from this run's selection,
author its LLD, then claim again. This script owns the two pieces of state a swappable skill
must never control: WHICH repos exist (reuses codebase_scan.discover_repos) and the atomic
claim queue (so two slots can never claim the same repo — same fcntl lock the engine itself
uses for state.yaml, via state.locked, so a claim can never race a run-state write either).

Commands
--------
  list   [--root .]
      Discovered repo names (read-only). Prints {"names_csv", "count"}.

  init   [--root .] --slug <slug> --choice all|pick [--repos-text "..."]
      Validate the human's scope choice against the discovered repos and write the claim
      queue to .maestro/runs/<slug>/lld-repos.json. `pick` parses --repos-text as a
      comma/whitespace-separated list, case-insensitive, and fails on any name that doesn't
      match a discovered repo (never silently drops a typo). Prints {"selected_csv", "count"}.

  claim  [--root .] --slug <slug>
      Atomically pop the next unclaimed repo. Prints {"repo": "<name>", "done": false} or
      {"repo": "", "done": true} once the queue is empty.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402
import state as statemod  # noqa: E402


def _queue_path(slug, root):
    return os.path.join(statemod.feature_dir(slug, root), "lld-repos.json")


def _load_queue(slug, root):
    path = _queue_path(slug, root)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _save_queue(slug, root, doc):
    path = _queue_path(slug, root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")


def cmd_list(args):
    names = [name for name, _path in codebase_scan.discover_repos(args.root)]
    print(json.dumps({"names_csv": ",".join(names), "count": len(names)}))
    return 0


def _parse_repos_text(text, discovered):
    by_lower = {n.lower(): n for n in discovered}
    wanted = [t.strip() for t in text.replace(",", " ").split() if t.strip()]
    picked, unknown = [], []
    for w in wanted:
        match = by_lower.get(w.lower())
        (picked if match else unknown).append(match or w)
    return picked, unknown


def cmd_init(args):
    discovered = [name for name, _path in codebase_scan.discover_repos(args.root)]
    if not discovered:
        print(f"FAIL: no repos discovered under {args.root!r} (codebase/* or the root itself)",
              file=sys.stderr)
        return 1
    if args.choice == "all":
        selected = discovered
    else:
        if not args.repos_text:
            print("FAIL: --choice pick requires --repos-text", file=sys.stderr)
            return 1
        selected, unknown = _parse_repos_text(args.repos_text, discovered)
        if unknown:
            print(f"FAIL: unknown repo name(s) {unknown} — discovered repos are {discovered}",
                  file=sys.stderr)
            return 1
        if not selected:
            print("FAIL: no repos selected", file=sys.stderr)
            return 1
    with statemod.locked(args.slug, args.root):
        _save_queue(args.slug, args.root, {"selected": selected, "remaining": list(selected)})
    print(json.dumps({"selected_csv": ",".join(selected), "count": len(selected)}))
    return 0


def cmd_claim(args):
    with statemod.locked(args.slug, args.root):
        doc = _load_queue(args.slug, args.root)
        if doc is None:
            print(f"FAIL: no lld-repos.json for slug {args.slug!r} — run init first",
                  file=sys.stderr)
            return 1
        remaining = doc.get("remaining") or []
        if not remaining:
            print(json.dumps({"repo": "", "done": True}))
            return 0
        repo = remaining.pop(0)
        doc["remaining"] = remaining
        _save_queue(args.slug, args.root, doc)
    print(json.dumps({"repo": repo, "done": False}))
    return 0


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list")
    p.add_argument("--root", default=".")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("init")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)
    p.add_argument("--choice", required=True, choices=["all", "pick"])
    p.add_argument("--repos-text", default="")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("claim")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)
    p.set_defaults(fn=cmd_claim)

    args = parser.parse_args(argv[1:])
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
