#!/usr/bin/env python3
"""Per-repo codebase-map commit tracking — the deterministic half of the living
codebase map.

The skill (build-knowledge / retrospect) supplies the PROSE of a repo's
`docs/codebase-map.md`; this engine script owns the load-bearing determinism —
WHICH repos exist, WHAT changed since the map was last written, and the recorded
commit — so swapping that skill can never change how the incremental refresh works
(the same reason memory consolidation lives in the engine, not a skill).

Commands
--------
  plan   [--root .] [--map-rel docs/codebase-map.md]
      Detect the repo(s) — each git repo directly under <root>/codebase/*, or <root>
      itself for a single-repo workspace — and for each, read the commit recorded in
      its map file's marker and classify:
        * full        — no map/marker yet: author the whole map.
        * incremental — map exists: emit the files changed since the recorded commit
                        so the skill re-explores only those.
        * current     — HEAD == recorded commit: nothing changed, skip.
      Also emits top-level `stale` (bool — any repo not `current`) and `stale_repos`
      (names of those repos), so a workflow `script` node can route on a plain scalar
      without inspecting the per-repo array (used by design.yaml's pre-HLD freshness gate).
      Read-only (git reads + file reads). Prints a JSON plan on stdout.

  record [--root .] [--map-rel docs/codebase-map.md]
      Stamp each repo's current HEAD into its map file's marker, AFTER the skill has
      (re)written the map. Skips repos with no map file. This is the step that makes
      the NEXT run incremental — kept in the engine, invoked from a workflow script
      node, so it can't be skipped by swapping the skill.

Marker line (an HTML comment — invisible in rendered markdown):
  <!-- maestro-codebase-map commit=<sha> updated=<iso8601> -->
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

DEFAULT_MAP_REL = "docs/codebase-map.md"
MARKER_RE = re.compile(r"<!--\s*maestro-codebase-map\s+commit=([0-9a-fA-F]+).*?-->")
MAX_CHANGED = 500  # cap the emitted file list so a huge diff can't bloat the prompt


def _git(repo, *args):
    """Run `git -C repo <args>`; return (returncode, stdout stripped)."""
    try:
        proc = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True, text=True, timeout=60,
        )
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _is_git_repo(path):
    rc, _ = _git(path, "rev-parse", "--git-dir")
    return rc == 0


def _head(repo):
    rc, out = _git(repo, "rev-parse", "HEAD")
    return out if rc == 0 and out else None


def discover_repos(root):
    """The repos this workspace maps, as [(name, abspath)] sorted by name.

    Umbrella layout: every immediate child of <root>/codebase/ that is a git repo.
    Single-repo layout: <root> itself. If codebase/ exists but holds no git repos,
    fall back to <root> when it is a git repo."""
    root = os.path.abspath(root)
    codebase = os.path.join(root, "codebase")
    repos = []
    if os.path.isdir(codebase):
        for name in sorted(os.listdir(codebase)):
            path = os.path.join(codebase, name)
            if os.path.isdir(path) and _is_git_repo(path):
                repos.append((name, path))
    if not repos and _is_git_repo(root):
        repos.append((os.path.basename(root) or "repo", root))
    return repos


def read_marker(map_path):
    """The commit recorded in a map file's marker, or None."""
    try:
        with open(map_path, encoding="utf-8") as fh:
            m = MARKER_RE.search(fh.read())
        return m.group(1) if m else None
    except OSError:
        return None


def write_marker(map_path, commit):
    """Insert/replace the marker line in an existing map file."""
    with open(map_path, encoding="utf-8") as fh:
        text = fh.read()
    stamp = (f"<!-- maestro-codebase-map commit={commit} "
             f"updated={datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()} -->")
    if MARKER_RE.search(text):
        text = MARKER_RE.sub(stamp, text, count=1)
    else:
        text = text.rstrip("\n") + "\n\n" + stamp + "\n"
    with open(map_path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _rel(path, root):
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return path


def cmd_plan(root, map_rel):
    root = os.path.abspath(root)
    repos_out = []
    for name, repo in discover_repos(root):
        map_abs = os.path.join(repo, map_rel)
        head = _head(repo)
        prev = read_marker(map_abs) if os.path.exists(map_abs) else None
        changed = []
        if head is None:
            mode = "full"
        elif prev is None:
            mode = "full"
        elif prev == head:
            mode = "current"
        else:
            rc, out = _git(repo, "diff", "--name-only", prev, head)
            if rc != 0:  # recorded commit gone (history rewritten) — rebuild whole map
                mode = "full"
            else:
                changed = [line for line in out.splitlines() if line.strip()]
                mode = "incremental"
        entry = {
            "name": name,
            "path": _rel(repo, root),
            "map_path": _rel(map_abs, root),
            "mode": mode,
            "prev_commit": prev,
            "head_commit": head,
            "changed_count": len(changed),
            "changed_files": changed[:MAX_CHANGED],
        }
        if len(changed) > MAX_CHANGED:
            entry["changed_truncated"] = True
        repos_out.append(entry)
    stale_repos = [r["name"] for r in repos_out if r["mode"] != "current"]
    # Single-line, un-indented: a workflow script node's `complete --stdout` only parses
    # the LAST line of stdout as JSON and keeps only scalar fields (resolver._complete_script)
    # — a pretty-printed multi-line object's last line is just "}", so `stale`/`stale_repos`
    # would silently never reach the workflow. stale_repos (list) is dropped by that same
    # scalar-only filter, so also emit stale_repos_csv for route/prompt placeholders to use.
    print(json.dumps({
        "root": root,
        "map_rel": map_rel,
        "repos": repos_out,
        "stale": bool(stale_repos),
        "stale_repos": stale_repos,
        "stale_repos_csv": ",".join(stale_repos),
    }))
    return 0


def cmd_record(root, map_rel):
    root = os.path.abspath(root)
    recorded, skipped = [], []
    for name, repo in discover_repos(root):
        map_abs = os.path.join(repo, map_rel)
        head = _head(repo)
        if not os.path.exists(map_abs):
            skipped.append({"name": name, "reason": "no map file"})
            continue
        if head is None:
            skipped.append({"name": name, "reason": "no HEAD commit"})
            continue
        write_marker(map_abs, head)
        recorded.append({"name": name, "map_path": _rel(map_abs, root), "commit": head})
    # Single-line for the same reason as cmd_plan — a workflow script node's last stdout
    # line must itself be the whole JSON object.
    print(json.dumps({"recorded": recorded, "skipped": skipped}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Per-repo codebase-map commit tracking.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for cmd in ("plan", "record"):
        p = sub.add_parser(cmd)
        p.add_argument("--root", default=".")
        p.add_argument("--map-rel", default=DEFAULT_MAP_REL)
    args = parser.parse_args(argv)
    if args.cmd == "plan":
        return cmd_plan(args.root, args.map_rel)
    return cmd_record(args.root, args.map_rel)


if __name__ == "__main__":
    sys.exit(main())
