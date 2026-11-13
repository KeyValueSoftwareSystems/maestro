#!/usr/bin/env python3
"""The feature's repository LLDs: one file per selected repository, written and approved in one run.

Design writes `.maestro/runs/<slug>/design/lld/<repo>.md` for every repository in the feature's
scope (`.engine/lld-scope.json`). This helper owns the deterministic parts: which repositories are in scope, that
every LLD exists and passes the LLD validator, and a hash-bound approval record. The approval
binds each LLD to the exact HLD and contract it was written against, so a later change to either
(for example a frontend need that adds a contract field) makes the LLDs stale instead of silently
out of date. Implementation refuses to start on a stale design.

Commands
--------
  list     [--root .]                                  discovered repo names
  init     [--root .] --slug S --choice all|pick|impact [--repos-text "a, b"] [--require "a,b"]
           [--impact impact.json]
           write the selection to .engine/lld-scope.json; `pick` fails on an unknown name; `impact` takes
           the repositories the impact assessment names (every repository when it is missing or
           invalid) plus the --require ones
  validate [--root .] --slug S                         every selected LLD exists and validates
  approve  [--root .] --slug S [--light true]  record .engine/lld-approval.json (PRD, HLD, contract,
           LLD hashes; --light: the light path designs without an HLD)
  verify   [--root .] --slug S                         are the approved LLDs still current?

Every command prints one JSON line. `validate` and `verify` exit 0 so workflows route on fields.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402
import impact as impactmod  # noqa: E402
import run_layout  # noqa: E402
import state as statemod  # noqa: E402
import validate_lld  # noqa: E402


def selection_path(slug, root):
    return run_layout.path(slug, root, run_layout.LLD_SCOPE)


def lld_path(slug, repo, root):
    return run_layout.path(slug, root, run_layout.lld(repo))


def approval_path(slug, root):
    return run_layout.path(slug, root, run_layout.LLD_APPROVAL)


def _hld_path(slug, root):
    return run_layout.path(slug, root, run_layout.HLD)


def _contract_path(slug, root):
    return run_layout.path(slug, root, run_layout.CONTRACT)


def _write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _hash(path):
    return statemod.sha256_file(path) if os.path.isfile(path) else None


def selected(slug, root):
    try:
        with open(selection_path(slug, root), encoding="utf-8") as fh:
            repos = json.load(fh).get("selected")
    except (OSError, ValueError):
        return []
    return repos if isinstance(repos, list) else []


def _fail(message):
    print(f"FAIL: {message}", file=sys.stderr)
    return 1


def cmd_list(args):
    names = [name for name, _path in codebase_scan.discover_repos(args.root)]
    print(json.dumps({"names_csv": ",".join(names), "count": len(names)}))
    return 0


def cmd_init(args):
    discovered = [name for name, _path in codebase_scan.discover_repos(args.root)]
    if not discovered:
        return _fail(f"no repos discovered under {args.root!r} (codebase/* or the root itself)")
    required = [r.strip() for r in (args.require or "").split(",") if r.strip()]
    if args.choice == "all":
        repos = discovered
    elif args.choice == "impact":
        assessed = impactmod.load(args.root, args.impact)[0] if args.impact else None
        repos = list(assessed["repos"]) if assessed else list(discovered)
        repos += [r for r in required if r in discovered and r not in repos]
    else:
        by_lower = {name.lower(): name for name in discovered}
        wanted = [part for part in (args.repos_text or "").replace(",", " ").split() if part]
        unknown = [name for name in wanted if name.lower() not in by_lower]
        if unknown:
            return _fail(f"unknown repo name(s) {unknown} — discovered repos are {discovered}")
        repos = list(dict.fromkeys(by_lower[name.lower()] for name in wanted))
        if not repos:
            return _fail("--choice pick needs at least one repo name")
    dropped = [repo for repo in required if repo in discovered and repo not in repos]
    if dropped:
        # the approved HLD changes infrastructure these repositories own: they ship with the feature
        return _fail(f"{', '.join(dropped)} must be in scope: the HLD lists infrastructure changes "
                     "they own")
    _write_json(selection_path(args.slug, args.root), {"schema_version": 3, "selected": repos})
    paths = [os.path.relpath(lld_path(args.slug, repo, args.root), args.root) for repo in repos]
    print(json.dumps({"selected_csv": ",".join(repos), "count": len(repos),
                      "lld_paths_csv": ",".join(paths)}))
    return 0


def cmd_validate(args):
    repos = selected(args.slug, args.root)
    if not repos:
        return _fail(f"no repos selected for {args.slug!r} — run init first")
    issues = []
    for repo in repos:
        path = lld_path(args.slug, repo, args.root)
        if not os.path.isfile(path):
            issues.append(f"{repo}: LLD missing at {os.path.relpath(path, args.root)}")
            continue
        errors, _warnings = validate_lld.validate(path, parent_slug=args.slug, repo=repo)
        issues.extend(f"{repo}: {error}" for error in errors)
    print(json.dumps({
        "valid": not issues,
        "repos_csv": ",".join(repos),
        "issues_summary": " | ".join(issues[:10]) if issues else "every repository LLD is valid",
    }))
    return 0


def _prd_path(slug, root):
    return run_layout.path(slug, root, run_layout.PRD)


def _current_hashes(slug, root, repos):
    return {
        "prd_sha256": _hash(_prd_path(slug, root)),
        "hld_sha256": _hash(_hld_path(slug, root)),
        "contract_sha256": _hash(_contract_path(slug, root)),
        "llds": {repo: _hash(lld_path(slug, repo, root)) for repo in repos},
    }


def cmd_approve(args):
    repos = selected(args.slug, args.root)
    if not repos:
        return _fail(f"no repos selected for {args.slug!r} — run init first")
    hashes = _current_hashes(args.slug, args.root, repos)
    missing = [repo for repo, digest in hashes["llds"].items() if digest is None]
    if missing:
        return _fail(f"cannot approve: LLD missing for {', '.join(missing)}")
    light = str(args.light).lower() in ("true", "light")
    if hashes["hld_sha256"] is None and not light:
        return _fail("cannot approve LLDs without an HLD (only the light path designs without one)")
    path = approval_path(args.slug, args.root)
    _write_json(path, {"schema_version": 1, "approved_at": statemod.now_iso(),
                       "repos": repos, "light": light, **hashes})
    print(json.dumps({"approval_path": os.path.relpath(path, args.root),
                      "approval_sha256": statemod.sha256_file(path)}))
    return 0


def stale_reasons(slug, root):
    """Why the approved LLDs no longer match the HLD, contract or themselves ([] = current)."""
    try:
        with open(approval_path(slug, root), encoding="utf-8") as fh:
            approval = json.load(fh)
    except (OSError, ValueError):
        return ["the repository LLDs have no approval record"]
    repos = selected(slug, root)
    if sorted(repos) != sorted(approval.get("repos") or []):
        return ["the selected repositories changed after LLD approval"]
    now = _current_hashes(slug, root, repos)
    reasons = []
    if "prd_sha256" in approval and now["prd_sha256"] != approval["prd_sha256"]:
        reasons.append("the PRD changed after LLD approval")
    if now["hld_sha256"] != approval.get("hld_sha256"):
        reasons.append("the HLD changed after LLD approval")
    if now["contract_sha256"] != approval.get("contract_sha256"):
        reasons.append("the API contract changed after LLD approval")
    for repo in repos:
        if now["llds"].get(repo) != (approval.get("llds") or {}).get(repo):
            reasons.append(f"{repo}: LLD changed after approval")
    return reasons


def cmd_verify(args):
    if os.environ.get("MAESTRO_SIMULATION") == "1":
        print(json.dumps({"stale": False, "reasons": "[simulated] design current"}))
        return 0
    reasons = stale_reasons(args.slug, args.root)
    print(json.dumps({"stale": bool(reasons),
                      "reasons": "; ".join(reasons) or "approved LLDs match the HLD and contract"}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--root", default=".")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("init")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)
    p.add_argument("--choice", choices=("all", "pick", "impact"), default="all")
    p.add_argument("--repos-text", default="")
    p.add_argument("--impact", default="", help="the impact assessment, for --choice impact")
    p.add_argument("--require", default="",
                   help="repositories that must be in scope (the HLD's infrastructure owners)")
    p.set_defaults(fn=cmd_init)
    for name, fn in (("validate", cmd_validate), ("approve", cmd_approve), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        p.add_argument("--root", default=".")
        p.add_argument("--slug", required=True)
        if name == "approve":
            p.add_argument("--light", default="false")
        p.set_defaults(fn=fn)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
