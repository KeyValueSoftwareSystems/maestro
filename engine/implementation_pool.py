#!/usr/bin/env python3
"""Deterministic repo implementation queue and QA handoff manifest.

Design chooses repos in lld-repos.json. Fixed workflow slots claim those repos here,
run the generic implementation subworkflow, then record the exact checked-out branch,
worktree and commit. `finalize` fails unless every selected repo has a verified entry.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402
import state as statemod  # noqa: E402


def _run_dir(slug, root):
    return statemod.feature_dir(slug, root)


def _queue_path(slug, root):
    return os.path.join(_run_dir(slug, root), "implementation-repos.json")


def _manifest_path(slug, root):
    return os.path.join(_run_dir(slug, root), "implementation-manifest.json")


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


def cmd_init(args):
    selection_path = os.path.join(_run_dir(args.slug, args.root), "lld-repos.json")
    try:
        selection = _read(selection_path)
    except (OSError, ValueError) as exc:
        return _fail(f"cannot read design repo selection {selection_path}: {exc}")
    selected = selection.get("selected")
    if not isinstance(selected, list) or not selected:
        return _fail("design repo selection is empty or invalid")
    discovered = dict(codebase_scan.discover_repos(args.root))
    missing = [name for name in selected if name not in discovered]
    if missing:
        return _fail(f"selected repo(s) are no longer discoverable: {missing}")
    doc = {"schema_version": 1, "selected": selected, "remaining": list(selected),
           "implementations": {}}
    with statemod.locked(args.slug, args.root):
        _write(_queue_path(args.slug, args.root), doc)
    print(json.dumps({"selected_csv": ",".join(selected), "count": len(selected)}))
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
    print(json.dumps({"repo": repo, "repo_path": os.path.relpath(path, args.root),
                      "done": False}))
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
            return _fail(f"repo {args.repo!r} was not selected by design")
        repo_path = dict(codebase_scan.discover_repos(args.root)).get(args.repo)
        if not repo_path:
            return _fail(f"repo {args.repo!r} is no longer discoverable")
        simulated = os.environ.get("MAESTRO_SIMULATION") == "1"
        if simulated:
            worktree = "[simulated: no code was checked out]"
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
        entries = [implementations[name] for name in selected]
        if os.environ.get("MAESTRO_SIMULATION") != "1":
            discovered = dict(codebase_scan.discover_repos(args.root))
            failures = []
            for entry in entries:
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
        manifest = {"schema_version": 1, "feature_slug": args.slug,
                    "repositories": entries}
        path = _manifest_path(args.slug, args.root)
        _write(path, manifest)
    print(json.dumps({"manifest_path": os.path.relpath(path, args.root),
                      "manifest_sha256": _sha256(path),
                      "repo_count": len(entries),
                      "branches_csv": ",".join(e["branch"] for e in entries)}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for command in ("init", "claim", "finalize"):
        p = sub.add_parser(command)
        p.add_argument("--root", default=".")
        p.add_argument("--slug", required=True)
        p.set_defaults(fn=globals()[f"cmd_{command}"])
    p = sub.add_parser("record")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--worktree", required=True)
    p.add_argument("--commit", required=True)
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
