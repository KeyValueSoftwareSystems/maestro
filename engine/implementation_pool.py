#!/usr/bin/env python3
"""Deterministic repo implementation queue and QA handoff manifest.

Design chooses repos in lld-repos.json. `init` selects the repos to implement: the golden workflow
takes every designed repo afresh (`--choice all --fresh`); `--choice pick` keeps the batching a
team workflow may want, leaving unselected repos as deferred work. Fixed workflow slots claim the
selected repos, run the generic implementation subworkflow, then record the exact checked-out
branch, worktree and commit. `finalize` fails unless every selected repo has a verified entry,
and attaches each repo's engine verification receipt to the QA/release manifest.

When QA finds a product bug, `bugfix-init` queues the implemented repos it names and
`bugfix-claim` hands each one out with its recorded branch, worktree and commit; the fix commits
on that same branch, `record` stores the new commit, and `finalize` rebuilds the manifest.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402
import stack_skills  # noqa: E402
import state as statemod  # noqa: E402


def _run_dir(slug, root):
    return statemod.feature_dir(slug, root)


def _queue_path(slug, root):
    return os.path.join(_run_dir(slug, root), "implementation-repos.json")


def _manifest_path(slug, root):
    return os.path.join(_run_dir(slug, root), "implementation-manifest.json")


def _receipt_path(slug, repo, root):
    """The engine verify step's receipt for one repository (repo_checks.py --out)."""
    return os.path.join(_run_dir(slug, root), repo, "verify.json")


def _verification(slug, entry, root):
    """What the engine actually verified for this repository's shipped commit.

    `verified` only when the receipt passed AND names the exact commit being released; a
    receipt for an earlier commit is `stale`. A receipt that passed only because the tests also
    fail on the base commit (`pre-existing`) is `baseline-failing`: the engine cannot show the
    feature's tests pass, so autopilot leaves the release to a person. Never blocks: a human may
    have accepted an unverified batch at the implementation gate, and the release gate shows
    this verdict. `review` says whether that commit was code-reviewed (`_review`); autopilot needs
    both.
    """
    if os.environ.get("MAESTRO_SIMULATION") == "1":
        return {"status": "simulated", "receipt": None, "test_changes": [], "review": "simulated"}
    review = _review(slug, entry, root)
    path = _receipt_path(slug, entry["repo"], root)
    try:
        receipt = _read(path)
    except (OSError, ValueError):
        return {"status": "missing", "receipt": None, "test_changes": [], "review": review}
    passed = receipt.get("passed") is True
    matches = receipt.get("commit") == entry.get("commit")
    pre_existing = [c["name"] for c in receipt.get("checks") or []
                    if c.get("status") == "pre-existing"]
    status = "verified" if passed and matches else ("stale" if passed else "failed")
    if status == "verified" and "test" in pre_existing:
        status = "baseline-failing"
    return {
        "status": status,
        "receipt": os.path.relpath(path, root),
        "receipt_sha256": _sha256(path),
        "verified_commit": receipt.get("commit"),
        "failed_checks": [c["name"] for c in receipt.get("checks") or []
                          if c.get("status") not in ("passed", "pre-existing")],
        "pre_existing": pre_existing,
        "test_changes": receipt.get("test_changes") or [],
        "review": review,
    }


def _review(slug, entry, root):
    """Whether the shipped commit was code-reviewed: `reviewed`, `blocking` (findings left open),
    or `not-reviewed` — no review verdict names this commit, e.g. the stack was accepted at the
    escalation gate before review ran, or a later fix was never re-reviewed."""
    path = os.path.join(_run_dir(slug, root), entry["repo"], "reviews", "reviewed.json")
    try:
        record = _read(path)
    except (OSError, ValueError):
        return "not-reviewed"
    if record.get("commit") != entry.get("commit"):
        return "not-reviewed"
    return "blocking" if record.get("blocking") else "reviewed"


def _verification_summary(entries):
    parts = []
    for entry in entries:
        check = entry["verification"]
        text = f"{entry['repo']} {check['status']}"
        if check.get("failed_checks"):
            text += f" ({', '.join(check['failed_checks'])})"
        if check.get("pre_existing"):
            text += f", pre-existing failures on the base commit: {', '.join(check['pre_existing'])}"
        if check.get("test_changes"):
            text += f", {len(check['test_changes'])} existing test file(s) changed"
        if check.get("review") == "not-reviewed":
            text += ", code review not run on this commit"
        elif check.get("review") == "blocking":
            text += ", code review left blocking findings"
        parts.append(text)
    return "; ".join(parts) or "no repositories"


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(cwd, *args):
    try:
        proc = subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                              text=True, timeout=60)
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _fail(message):
    print(f"FAIL: {message}", file=sys.stderr)
    return 1


def _design_selection(slug, root):
    selection_path = os.path.join(_run_dir(slug, root), "lld-repos.json")
    try:
        selection = _read(selection_path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read design repo selection {selection_path}: {exc}") from None
    selected = selection.get("selected")
    if not isinstance(selected, list) or not selected:
        raise ValueError("design repo selection is empty or invalid")
    return selected


def _parse_repos_text(text, available):
    by_lower = {name.lower(): name for name in available}
    requested = [part.strip() for part in (text or "").replace(",", " ").split()
                 if part.strip()]
    selected, unknown = [], []
    for candidate in requested:
        repo = by_lower.get(candidate.lower())
        if repo is None:
            unknown.append(candidate)
        elif repo not in selected:
            selected.append(repo)
    return selected, unknown


def _pool_state(slug, root):
    try:
        return _read(_queue_path(slug, root))
    except (OSError, ValueError):
        return None


def cmd_list(args):
    try:
        designed = _design_selection(args.slug, args.root)
    except ValueError as exc:
        return _fail(str(exc))
    existing = _pool_state(args.slug, args.root) or {}
    implemented = existing.get("implementations") or {}
    available = [repo for repo in designed if repo not in implemented]
    print(json.dumps({
        "designed_csv": ",".join(designed),
        "available_csv": ",".join(available),
        "implemented_csv": ",".join(repo for repo in designed if repo in implemented),
        "available_count": len(available),
    }))
    return 0


def cmd_init(args):
    try:
        designed = _design_selection(args.slug, args.root)
    except ValueError as exc:
        return _fail(str(exc))
    discovered = dict(codebase_scan.discover_repos(args.root))
    missing = [name for name in designed if name not in discovered]
    if missing:
        return _fail(f"selected repo(s) are no longer discoverable: {missing}")
    with statemod.locked(args.slug, args.root):
        existing = _pool_state(args.slug, args.root) or {}
        implementations = existing.get("implementations") or {}
        # Ignore stale entries for repositories no longer present in the approved design scope.
        # --fresh starts a new pass over the whole design (e.g. after a redesign): earlier
        # handoffs were built against an older design, so none of them carry over.
        implementations = {} if args.fresh else {
            repo: entry for repo, entry in implementations.items() if repo in designed
        }
        available = [repo for repo in designed if repo not in implementations]
        if not available:
            return _fail("all designed repositories are already implemented")
        if args.choice == "all":
            selected = available
        else:
            selected, unknown = _parse_repos_text(args.repos_text, available)
            if unknown:
                return _fail(
                    f"unknown or unavailable repo name(s) {unknown}; available repos are {available}"
                )
            if not selected:
                return _fail("--choice pick requires at least one available repository")
        deferred = [repo for repo in available if repo not in selected]
        doc = {
            "schema_version": 2,
            "designed": designed,
            "selected": selected,
            "remaining": list(selected),
            "deferred": deferred,
            "implementations": implementations,
        }
        _write(_queue_path(args.slug, args.root), doc)
    print(json.dumps({
        "selected_csv": ",".join(selected),
        "deferred_csv": ",".join(deferred),
        "count": len(selected),
    }))
    return 0


def cmd_claim(args):
    with statemod.locked(args.slug, args.root):
        try:
            doc = _read(_queue_path(args.slug, args.root))
        except (OSError, ValueError) as exc:
            return _fail(f"implementation queue is unavailable: {exc}")
        remaining = doc.get("remaining") or []
        if not remaining:
            print(json.dumps({"repo": "", "repo_path": "", "done": True}))
            return 0
        repo = remaining.pop(0)
        doc["remaining"] = remaining
        _write(_queue_path(args.slug, args.root), doc)
    discovered = dict(codebase_scan.discover_repos(args.root))
    path = discovered.get(repo)
    if not path:
        return _fail(f"claimed repo {repo!r} is no longer discoverable")
    stacks, skills = stack_skills.for_repo(args.root, repo)
    print(json.dumps({"repo": repo, "repo_path": os.path.relpath(path, args.root),
                      "done": False, "stacks_csv": ",".join(stacks),
                      "stack_skills_csv": ",".join(skills)}))
    return 0


def _registered_worktrees(repo_path):
    rc, out = _git(repo_path, "worktree", "list", "--porcelain")
    if rc:
        return set()
    return {os.path.realpath(line[9:]) for line in out.splitlines()
            if line.startswith("worktree ")}


def _verify_entry(args, repo_path):
    worktree = args.worktree
    if not os.path.isabs(worktree):
        worktree = os.path.join(args.root, worktree)
    worktree = os.path.realpath(worktree)
    if worktree == os.path.realpath(repo_path):
        raise ValueError(f"reported worktree is the main checkout for repo {args.repo}")
    if worktree not in _registered_worktrees(repo_path):
        raise ValueError(f"worktree is not registered to repo {args.repo}: {worktree}")
    rc, actual_commit = _git(worktree, "rev-parse", "HEAD")
    if rc or actual_commit != args.commit:
        raise ValueError(f"worktree HEAD {actual_commit or '<missing>'} != reported {args.commit}")
    rc, branch_commit = _git(repo_path, "rev-parse", f"refs/heads/{args.branch}")
    if rc or branch_commit != args.commit:
        raise ValueError(f"branch {args.branch!r} does not resolve to reported commit")
    rc, actual_branch = _git(worktree, "branch", "--show-current")
    if rc or actual_branch != args.branch:
        raise ValueError(f"worktree is on {actual_branch or '<detached>'}, not {args.branch}")
    return worktree


def cmd_record(args):
    with statemod.locked(args.slug, args.root):
        try:
            doc = _read(_queue_path(args.slug, args.root))
        except (OSError, ValueError) as exc:
            return _fail(f"implementation queue is unavailable: {exc}")
        if args.repo not in (doc.get("selected") or []):
            return _fail(f"repo {args.repo!r} is not selected in the active implementation batch")
        repo_path = dict(codebase_scan.discover_repos(args.root)).get(args.repo)
        if not repo_path:
            return _fail(f"repo {args.repo!r} is no longer discoverable")
        simulated = os.environ.get("MAESTRO_SIMULATION") == "1"
        if args.from_worktree and not simulated:
            # a QA bug fix commits on the branch it was given: record whatever HEAD it left
            worktree = args.worktree if os.path.isabs(args.worktree) else os.path.join(
                args.root, args.worktree)
            rc, args.commit = _git(worktree, "rev-parse", "HEAD")
            if rc or not args.commit:
                return _fail(f"cannot resolve HEAD for worktree {worktree}")
        elif not args.commit:
            return _fail("record needs --commit or --from-worktree")
        if simulated:
            worktree = "[simulated: no code was checked out]"
            args.commit = args.commit or "[simulated commit]"
        else:
            try:
                worktree = _verify_entry(args, repo_path)
            except ValueError as exc:
                return _fail(str(exc))
        doc.setdefault("implementations", {})[args.repo] = {
            "repo": args.repo,
            "source_path": os.path.relpath(repo_path, args.root),
            "branch": args.branch,
            "worktree": worktree,
            "commit": args.commit,
            "simulated": simulated,
        }
        _write(_queue_path(args.slug, args.root), doc)
    print(json.dumps({"recorded": args.repo, "commit": args.commit}))
    return 0


def cmd_inspect(args):
    """Resolve the live feature worktree identity after implementation or a fix."""
    if os.environ.get("MAESTRO_SIMULATION") == "1":
        print(json.dumps({"branch": args.branch, "worktree": args.worktree,
                          "commit": "[simulated commit]"}))
        return 0
    repo_path = dict(codebase_scan.discover_repos(args.root)).get(args.repo)
    if not repo_path:
        return _fail(f"repo {args.repo!r} is not discoverable")
    worktree = args.worktree
    if not os.path.isabs(worktree):
        worktree = os.path.join(args.root, worktree)
    rc, commit = _git(worktree, "rev-parse", "HEAD")
    if rc or not commit:
        return _fail(f"cannot resolve HEAD for worktree {worktree}")
    verify_args = argparse.Namespace(root=args.root, repo=args.repo, branch=args.branch,
                                     worktree=worktree, commit=commit)
    try:
        verified_worktree = _verify_entry(verify_args, repo_path)
    except ValueError as exc:
        return _fail(str(exc))
    print(json.dumps({"branch": args.branch, "worktree": verified_worktree,
                      "commit": commit}))
    return 0


def cmd_finalize(args):
    with statemod.locked(args.slug, args.root):
        try:
            doc = _read(_queue_path(args.slug, args.root))
        except (OSError, ValueError) as exc:
            return _fail(f"implementation queue is unavailable: {exc}")
        selected = doc.get("selected") or []
        implementations = doc.get("implementations") or {}
        missing = [name for name in selected if name not in implementations]
        if doc.get("remaining") or missing:
            return _fail(f"implementation pool incomplete; missing repo(s): {missing or doc['remaining']}")
        current_entries = [implementations[name] for name in selected]
        if os.environ.get("MAESTRO_SIMULATION") != "1":
            discovered = dict(codebase_scan.discover_repos(args.root))
            failures = []
            for entry in current_entries:
                repo_path = discovered.get(entry["repo"])
                if not repo_path:
                    failures.append(f"{entry['repo']}: repo is no longer discoverable")
                    continue
                verify_args = argparse.Namespace(
                    root=args.root, repo=entry["repo"], branch=entry["branch"],
                    worktree=entry["worktree"], commit=entry["commit"],
                )
                try:
                    _verify_entry(verify_args, repo_path)
                except ValueError as exc:
                    failures.append(f"{entry['repo']}: {exc}")
            if failures:
                return _fail("cannot finalize QA context: " + "; ".join(failures))
        designed = doc.get("designed") or selected
        entries = [dict(implementations[name]) for name in designed if name in implementations]
        for entry in entries:
            entry["verification"] = _verification(args.slug, entry, args.root)
        manifest = {"schema_version": 1, "feature_slug": args.slug,
                    "repositories": entries, "deferred_repositories": doc.get("deferred") or []}
        path = _manifest_path(args.slug, args.root)
        _write(path, manifest)
    print(json.dumps({"manifest_path": os.path.relpath(path, args.root),
                      "manifest_sha256": _sha256(path),
                      "repo_count": len(entries),
                      "branches_csv": ",".join(e["branch"] for e in entries),
                      "verified_ok": all(e["verification"]["status"] in ("verified", "simulated")
                                         and e["verification"]["review"] in ("reviewed",
                                                                             "simulated")
                                         for e in entries),
                      "verification_summary": _verification_summary(entries)}))
    return 0


def cmd_bugfix_init(args):
    """Queue the implemented repositories a QA product-bug diagnosis names."""
    with statemod.locked(args.slug, args.root):
        try:
            doc = _read(_queue_path(args.slug, args.root))
        except (OSError, ValueError) as exc:
            return _fail(f"implementation queue is unavailable: {exc}")
        implemented = list((doc.get("implementations") or {}).keys())
        selected, unknown = _parse_repos_text(args.repos_text, implemented)
        if unknown:
            return _fail(f"QA named repo(s) that were not implemented: {unknown}; "
                         f"implemented repos are {implemented}")
        if not selected:
            return _fail("QA reported a product bug without naming an implemented repository")
        doc["bugfix_remaining"] = selected
        _write(_queue_path(args.slug, args.root), doc)
    print(json.dumps({"repos_csv": ",".join(selected), "count": len(selected)}))
    return 0


def cmd_bugfix_claim(args):
    with statemod.locked(args.slug, args.root):
        try:
            doc = _read(_queue_path(args.slug, args.root))
        except (OSError, ValueError) as exc:
            return _fail(f"implementation queue is unavailable: {exc}")
        remaining = doc.get("bugfix_remaining") or []
        if not remaining:
            print(json.dumps({"done": True, "repo": "", "repo_path": "", "branch": "",
                              "worktree": "", "commit": "", "stack_skills_csv": ""}))
            return 0
        repo = remaining.pop(0)
        doc["bugfix_remaining"] = remaining
        _write(_queue_path(args.slug, args.root), doc)
        entry = (doc.get("implementations") or {})[repo]
    _stacks, skills = stack_skills.for_repo(args.root, repo)
    print(json.dumps({"done": False, "repo": repo, "repo_path": entry["source_path"],
                      "branch": entry["branch"], "worktree": entry["worktree"],
                      "commit": entry["commit"], "stack_skills_csv": ",".join(skills)}))
    return 0


def cmd_check(args):
    try:
        doc = _read(_queue_path(args.slug, args.root))
    except (OSError, ValueError) as exc:
        return _fail(f"implementation queue is unavailable: {exc}")
    deferred = doc.get("deferred") or []
    print(json.dumps({
        "has_deferred": bool(deferred),
        "deferred_csv": ",".join(deferred),
        "implemented_csv": ",".join((doc.get("implementations") or {}).keys()),
        "deferred_count": len(deferred),
    }))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for command in ("list", "claim", "finalize", "check", "bugfix-claim"):
        p = sub.add_parser(command)
        p.add_argument("--root", default=".")
        p.add_argument("--slug", required=True)
        p.set_defaults(fn=globals()[f"cmd_{command.replace('-', '_')}"])
    p = sub.add_parser("bugfix-init")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)
    p.add_argument("--repos-text", default="")
    p.set_defaults(fn=cmd_bugfix_init)
    p = sub.add_parser("init")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)
    p.add_argument("--choice", choices=("all", "pick"), default="all")
    p.add_argument("--repos-text", default="")
    p.add_argument("--fresh", action="store_true",
                   help="new pass over every designed repo; drop earlier implementation handoffs")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("record")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--worktree", required=True)
    p.add_argument("--commit", default="")
    p.add_argument("--from-worktree", action="store_true",
                   help="record the worktree's current HEAD (after a QA bug fix)")
    p.set_defaults(fn=cmd_record)
    p = sub.add_parser("inspect")
    p.add_argument("--root", default=".")
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--worktree", required=True)
    p.set_defaults(fn=cmd_inspect)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
