#!/usr/bin/env python3
"""The feature's implementation worktrees, created and removed by the engine.

  worktrees.py prepare --root . --slug S    once per feature, before implementation
  worktrees.py remove  --root . --slug S    after delivery; removes only what Maestro created

Where each repository's worktree comes from is the project's choice, in maestro.config.yaml:

    worktree:
      create: ./scripts/sandbox create {slug} -y      # once per feature, from the workspace root
      path: sandbox/{slug}/codebase/{repo}            # where `create` leaves each repository
      branch: sandbox/{slug}                          # optional: the branch `create` checks out
      remove: ./scripts/sandbox rm {slug} -y          # optional: run by `remove`

Without a `worktree` section the engine adds one itself per selected repository:
`git worktree add -b feature/<slug>-<repo> .maestro/worktrees/<slug>/<repo> <pinned commit>`.
Commands run through the shell from the workspace root; `{slug}` and `{root}` are replaced
(shell-quoted), and MAESTRO_SLUG / MAESTRO_ROOT are exported. `path` and `branch` take `{slug}`
and `{repo}`.

Maestro uses only worktrees it created. `prepare` refuses a path that already exists and is not in
this run's record, `.maestro/runs/<slug>/worktrees.json` (a resumed run or a later delivery pass
reuses its own). A new worktree must be clean and at the commit the feature's workspace lock
pinned, or `prepare` fails before any agent writes code. `implementation_pool.py claim` hands each
repository its recorded worktree and branch.

`remove` never fails the run and keeps anything it cannot remove safely: a worktree with
uncommitted changes, or (for a configured `remove`, which may delete the branch too) branches the
delivery did not push. The engine's own worktrees are removed with `git worktree remove`, which
keeps the branch.

Prints one JSON line. `prepare` exits 1 with the reason on stderr when it cannot hand out a
worktree; `remove` always exits 0.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402
import project_config  # noqa: E402
import repo_checks  # noqa: E402
import state as statemod  # noqa: E402

SCHEMA_VERSION = 1
DEFAULT_DIR = os.path.join(".maestro", "worktrees")
DEFAULT_BRANCH = "feature/{slug}-{repo}"


class WorktreeError(RuntimeError):
    pass


def _simulated():
    return os.environ.get("MAESTRO_SIMULATION") == "1"


def record_path(root, slug):
    return os.path.join(statemod.feature_dir(slug, root), "worktrees.json")


def load_record(root, slug):
    try:
        with open(record_path(root, slug), encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _save_record(root, slug, doc):
    path = record_path(root, slug)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _git(cwd, *args):
    try:
        proc = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True,
                              timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout.strip() or proc.stderr.strip())


def _registered(repo_path):
    rc, out = _git(repo_path, "worktree", "list", "--porcelain")
    if rc:
        return set()
    return {os.path.realpath(line[9:]) for line in out.splitlines() if line.startswith("worktree ")}


def _fill(template, **values):
    """Replace {name} placeholders (never shell ${NAME}) with the given values."""
    return re.sub(r"(?<!\$)\{(\w+)\}",
                  lambda m: values.get(m.group(1), m.group(0)), template)


def _command(template, root, slug):
    return _fill(template, slug=shlex.quote(slug), root=shlex.quote(root))


def _settings(root):
    config = project_config.load(root) or {}
    section = config.get("worktree")
    return section if isinstance(section, dict) and section.get("create") else None


def _selected(root, slug):
    path = os.path.join(statemod.feature_dir(slug, root), "implementation-repos.json")
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        raise WorktreeError(f"implementation queue is unavailable: {exc}") from None
    return list(doc.get("selected") or [])


def _pinned(root, slug):
    """{repo: commit} from the feature's workspace lock, or {} when the run has none."""
    path = os.path.join(statemod.feature_dir(slug, root), "workspace-lock.json")
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {e["name"]: e.get("commit", "") for e in doc.get("repos") or []
            if isinstance(e, dict) and e.get("name")}


def _abs(root, path):
    return os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))


def _check_new(repo, repo_path, worktree, branch, pinned):
    """A worktree just created for this feature: registered, on its branch, clean, at the pin."""
    if worktree not in _registered(repo_path):
        raise WorktreeError(f"{repo}: {worktree} is not a git worktree of {repo_path}")
    rc, current = _git(worktree, "branch", "--show-current")
    if rc or not current:
        raise WorktreeError(f"{repo}: the worktree at {worktree} is not on a branch")
    if branch and current != branch:
        raise WorktreeError(f"{repo}: the worktree is on {current}, not the configured {branch}")
    rc, dirty = _git(worktree, "status", "--porcelain")
    if rc or dirty:
        raise WorktreeError(f"{repo}: the new worktree at {worktree} has uncommitted changes")
    rc, head = _git(worktree, "rev-parse", "HEAD")
    if pinned and head != pinned:
        raise WorktreeError(
            f"{repo}: the new worktree starts at {head[:12]}, but this feature is pinned at "
            f"{pinned[:12]} (workspace-lock.json). Make the sandbox start from the pinned commit "
            f"(sync the clone first) or remove it and run the workspace sync again")
    return current, head


def _reusable(entry, repo_path):
    worktree = os.path.realpath(entry.get("path") or "")
    return bool(entry.get("path")) and os.path.isdir(worktree) and worktree in _registered(repo_path)


def prepare(root, slug):
    root = os.path.realpath(root)
    selected = _selected(root, slug)
    discovered = dict(codebase_scan.discover_repos(root))
    missing = [repo for repo in selected if repo not in discovered]
    if missing:
        raise WorktreeError(f"selected repo(s) are no longer discoverable: {missing}")
    settings = _settings(root)
    mode = "configured" if settings else "default"
    record = load_record(root, slug) or {}
    if record.get("mode") not in (None, mode):
        raise WorktreeError(
            f"this feature's worktrees were made with the {record['mode']} method, but "
            f"maestro.config.yaml now says {mode}; restore the setting or remove them first")
    record.update({"schema_version": SCHEMA_VERSION, "slug": slug, "mode": mode})
    entries = record.setdefault("repos", {})
    pinned = _pinned(root, slug)
    reused, created = [], []

    if mode == "default":
        template = DEFAULT_BRANCH
        for repo in selected:
            repo_path = discovered[repo]
            if repo in entries and _reusable(entries[repo], repo_path):
                reused.append(repo)
                continue
            worktree = os.path.join(root, DEFAULT_DIR, slug, repo)
            if repo in entries and not os.path.exists(worktree):
                # this run's own worktree was deleted by hand: check its branch out again
                _git(repo_path, "worktree", "prune")
                rc, out = _git(repo_path, "worktree", "add", "-q", worktree, entries[repo]["branch"])
                if rc:
                    raise WorktreeError(f"{repo}: cannot restore this run's worktree: {out[-400:]}")
                entries[repo]["path"] = os.path.realpath(worktree)
                reused.append(repo)
                _save_record(root, slug, record)
                continue
            if os.path.exists(worktree):
                raise WorktreeError(
                    f"{repo}: {os.path.relpath(worktree, root)} already exists and this run did not "
                    f"create it; Maestro uses only worktrees it creates — remove it, or start the "
                    f"feature under another slug")
            branch = _fill(template, slug=slug, repo=repo)
            rc, _ = _git(repo_path, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
            if rc == 0:
                raise WorktreeError(
                    f"{repo}: branch {branch} already exists and this run did not create it; "
                    f"delete it, or start the feature under another slug")
            base = pinned.get(repo) or "HEAD"
            _ignore_default_dir(root)
            os.makedirs(os.path.dirname(worktree), exist_ok=True)
            rc, out = _git(repo_path, "worktree", "add", "-q", "-b", branch, worktree, base)
            if rc:
                raise WorktreeError(f"{repo}: git worktree add failed: {out[-400:]}")
            worktree = os.path.realpath(worktree)
            _branch, head = _check_new(repo, repo_path, worktree, branch, pinned.get(repo))
            entries[repo] = {"path": worktree, "branch": branch, "base_commit": head,
                             "created_by_maestro": True}
            created.append(repo)
            _save_record(root, slug, record)
    else:
        path_template = settings.get("path") or ""
        branch_template = settings.get("branch") or ""
        paths = {repo: _abs(root, _fill(path_template, slug=slug, repo=repo)) for repo in selected}
        if record.get("create_started") and not record.get("create_ran") and all(
                os.path.isdir(p) for p in paths.values()):
            record["create_ran"] = True  # the command finished but the run stopped before saving
        if not record.get("create_ran"):
            existing = [os.path.relpath(p, root) for p in paths.values() if os.path.exists(p)]
            if existing and not record.get("create_started"):
                raise WorktreeError(
                    f"{', '.join(existing)} already exist(s) and this run did not create them; "
                    f"Maestro uses only worktrees it creates — remove them (the template's remove "
                    f"command), or start the feature under another slug")
            record["create_started"] = True
            _save_record(root, slug, record)
            command = _command(settings["create"], root, slug)
            log = os.path.join(statemod.feature_dir(slug, root), "worktrees", "create.log")
            result = repo_checks._run(command, root, project_config.DEFAULT_TIMEOUT_S, log,
                                      {"MAESTRO_SLUG": slug, "MAESTRO_ROOT": root})
            if result["status"] != "passed":
                raise WorktreeError(f"worktree.create failed (exit {result['exit_code']}, log "
                                    f"{os.path.relpath(log, root)}): {result['tail'][-600:]}")
            record["create_ran"] = True
            record["create_command"] = command
            _save_record(root, slug, record)
        for repo in selected:
            repo_path = discovered[repo]
            if repo in entries and _reusable(entries[repo], repo_path):
                reused.append(repo)
                continue
            worktree = paths[repo]
            if repo in entries:
                raise WorktreeError(
                    f"{repo}: this run's worktree at {os.path.relpath(worktree, root)} is gone; "
                    f"remove the rest of the sandbox and delete {os.path.relpath(record_path(root, slug), root)} "
                    f"to create it again")
            if not os.path.isdir(worktree):
                raise WorktreeError(
                    f"{repo}: worktree.create did not leave a worktree at "
                    f"{os.path.relpath(worktree, root)} (worktree.path in maestro.config.yaml)")
            branch = _fill(branch_template, slug=slug, repo=repo) if branch_template else ""
            branch, head = _check_new(repo, repo_path, worktree, branch, pinned.get(repo))
            entries[repo] = {"path": worktree, "branch": branch, "base_commit": head,
                             "created_by_maestro": True}
            created.append(repo)
        _save_record(root, slug, record)

    _save_record(root, slug, record)
    parts = []
    if created:
        parts.append(f"created {', '.join(created)}")
    if reused:
        parts.append(f"reused {', '.join(reused)}")
    return {"mode": mode, "repos_csv": ",".join(selected), "created_csv": ",".join(created),
            "reused_csv": ",".join(reused), "path": os.path.relpath(record_path(root, slug), root),
            "summary": f"Worktrees ({mode}): " + ("; ".join(parts) or "none needed")}


def _ignore_default_dir(root):
    folder = os.path.join(root, DEFAULT_DIR)
    os.makedirs(folder, exist_ok=True)
    ignore = os.path.join(folder, ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w", encoding="utf-8") as fh:
            fh.write("# engine-created feature worktrees; never committed\n*\n")


def for_repo(root, slug, repo):
    """(worktree, branch) recorded for one repository, or ("", default branch) without a record."""
    entry = ((load_record(root, slug) or {}).get("repos") or {}).get(repo) or {}
    branch = entry.get("branch") or _fill(DEFAULT_BRANCH, slug=slug, repo=repo)
    return entry.get("path") or "", branch


def _pushed(root, slug):
    path = os.path.join(statemod.feature_dir(slug, root), "delivery.json")
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return False
    repos = doc.get("repositories") or []
    return bool(repos) and all(r.get("pushed") is True for r in repos)


def remove(root, slug):
    root = os.path.realpath(root)
    record = load_record(root, slug)
    if not record or not record.get("repos"):
        return {"removed": False, "kept_csv": "", "summary": "No worktrees recorded for this feature"}
    if record.get("removed"):
        return {"removed": True, "kept_csv": "", "summary": "Worktrees already removed"}
    ours = {repo: e for repo, e in record["repos"].items() if e.get("created_by_maestro")}
    dirty = []
    for repo, entry in ours.items():
        path = entry.get("path", "")
        if os.path.isdir(path):
            rc, out = _git(path, "status", "--porcelain")
            if rc or out:
                dirty.append(repo)
    if dirty:
        return {"removed": False, "kept_csv": ",".join(ours),
                "summary": f"Kept the worktrees: uncommitted changes in {', '.join(dirty)}"}

    if record.get("mode") == "configured":
        settings = _settings(root) or {}
        if not record.get("create_ran"):
            return {"removed": False, "kept_csv": ",".join(ours),
                    "summary": "Kept the worktrees: Maestro did not create them"}
        if not settings.get("remove"):
            return {"removed": False, "kept_csv": ",".join(ours),
                    "summary": "Kept the sandbox: no worktree.remove in maestro.config.yaml"}
        if not _pushed(root, slug):
            return {"removed": False, "kept_csv": ",".join(ours),
                    "summary": "Kept the sandbox: its branches were not pushed (delivery.mode "
                               "branch); remove it after merging"}
        command = _command(settings["remove"], root, slug)
        log = os.path.join(statemod.feature_dir(slug, root), "worktrees", "remove.log")
        result = repo_checks._run(command, root, project_config.DEFAULT_TIMEOUT_S, log,
                                  {"MAESTRO_SLUG": slug, "MAESTRO_ROOT": root})
        if result["status"] != "passed":
            return {"removed": False, "kept_csv": ",".join(ours),
                    "summary": f"worktree.remove failed (exit {result['exit_code']}); remove the "
                               f"sandbox by hand"}
        removed = list(ours)
    else:
        discovered = dict(codebase_scan.discover_repos(root))
        removed, kept = [], []
        for repo, entry in ours.items():
            path = entry.get("path", "")
            repo_path = discovered.get(repo)
            if not os.path.isdir(path):
                removed.append(repo)
                continue
            rc, _ = _git(repo_path, "worktree", "remove", path) if repo_path else (1, "")
            (kept if rc else removed).append(repo)
        try:
            os.rmdir(os.path.join(root, DEFAULT_DIR, slug))
        except OSError:
            pass
        if kept:
            record["repos"] = {r: e for r, e in record["repos"].items() if r in kept}
            _save_record(root, slug, record)
            return {"removed": False, "kept_csv": ",".join(kept),
                    "summary": f"Removed {', '.join(removed) or 'none'}; could not remove "
                               f"{', '.join(kept)}"}
    record["removed"] = True
    record["removed_at"] = statemod.now_iso()
    _save_record(root, slug, record)
    branches = ", ".join(sorted({e.get("branch", "") for e in ours.values() if e.get("branch")}))
    note = "" if record.get("mode") == "configured" else f"; branches kept: {branches}"
    return {"removed": True, "kept_csv": "",
            "summary": f"Removed the worktrees for {', '.join(removed)}{note}"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["prepare", "remove"])
    parser.add_argument("--root", default=".")
    parser.add_argument("--slug", required=True)
    args = parser.parse_args(argv)
    if _simulated():
        print(json.dumps({"mode": "simulated", "repos_csv": "", "created_csv": "",
                          "reused_csv": "", "removed": False, "kept_csv": "",
                          "summary": "[simulated] no worktrees"}))
        return 0
    if args.command == "remove":
        print(json.dumps(remove(args.root, args.slug)))
        return 0
    try:
        print(json.dumps(prepare(args.root, args.slug)))
    except WorktreeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
