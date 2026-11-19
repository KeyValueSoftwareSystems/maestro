#!/usr/bin/env python3
"""The feature's implementation worktrees, created and removed by the engine.

  worktrees.py prepare --root . --slug S    once per feature, before implementation
  worktrees.py remove  --root . --slug S    after delivery; removes only what Maestro created
  worktrees.py check-base --root . --slug S --branch B --repos a,b
                                            does each repository have branch B (locally or on
                                            origin)? Fetches first; creates nothing
  worktrees.py prepare --root . --slug S --base-map M
                                            a bugfix sandbox: M ({repo: base ref}, a JSON file or
                                            inline JSON) gives each repository its own base; one
                                            worktree per repository on `fix/<slug>-<repo>`, all or
                                            nothing; writes .engine/sandbox.json (manifest-shaped,
                                            for `qa_env.py up --manifest`)
  worktrees.py bases --root . --slug S --branch B --repos a,b --choice as-is|default|named
                     [--named "web=release-2"]
                                            the base map a sandbox is built from: B where
                                            check-base finds it (no second fetch), and the
                                            person's answer for the repositories without B: their
                                            default branch, or the branch they named (`repo=b`
                                            pairs, or one name for all). Writes
                                            .engine/bug-bases.json when valid; always exits 0,
                                            route on `valid`

Where each repository's worktree comes from is the project's choice, in maestro.config.yaml:

    worktree:
      create: ./scripts/sandbox create {slug} -y      # once per feature, from the workspace root
      path: sandbox/{slug}/codebase/{repo}            # where `create` leaves each repository
      branch: sandbox/{slug}                          # optional: the branch `create` checks out
      remove: ./scripts/sandbox rm {slug} -y          # optional: run by `remove`

Without a `worktree` section the engine adds one itself per selected repository:
`git worktree add -b feature/<slug>-<repo> .maestro/worktrees/<slug>/<repo> <pinned commit>`.
Commands run through the shell from the workspace root; `{slug}`, `{root}` and `{branch}` (the
base branch: a bugfix sandbox's base, `HEAD` for a feature) are replaced (shell-quoted), and
MAESTRO_SLUG / MAESTRO_ROOT / MAESTRO_BASE_BRANCH are exported. `path` and `branch` take `{slug}`
and `{repo}`.

Maestro uses only worktrees it created. `prepare` refuses a path that already exists and is not in
this run's record, `.maestro/runs/<slug>/.engine/worktrees.json` (a resumed run or a later delivery pass
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
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402
import project_config  # noqa: E402
import repo_checks  # noqa: E402
import run_layout  # noqa: E402
import state as statemod  # noqa: E402

SCHEMA_VERSION = 1
DEFAULT_DIR = os.path.join(".maestro", "worktrees")
DEFAULT_BRANCH = "feature/{slug}-{repo}"
FIX_BRANCH = "fix/{slug}-{repo}"


class WorktreeError(RuntimeError):
    pass


def _simulated():
    return os.environ.get("MAESTRO_SIMULATION") == "1"


def record_path(root, slug):
    return run_layout.path(slug, root, run_layout.WORKTREES)


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
                              errors="replace", timeout=120)
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


def _command(template, root, slug, branch="HEAD"):
    return _fill(template, slug=shlex.quote(slug), root=shlex.quote(root),
                 branch=shlex.quote(branch))


def _settings(root):
    config = project_config.load(root) or {}
    section = config.get("worktree")
    return section if isinstance(section, dict) and section.get("create") else None


def _selected(root, slug):
    path = run_layout.path(slug, root, run_layout.POOL)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        raise WorktreeError(f"implementation queue is unavailable: {exc}") from None
    return list(doc.get("selected") or [])


def _pinned(root, slug):
    """{repo: commit} from the feature's workspace lock, or {} when the run has none."""
    path = run_layout.path(slug, root, run_layout.WORKSPACE_LOCK)
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


def _discard(repo_path, worktree, branch):
    """Remove a worktree and branch this run made and did not hand out. Never raises."""
    if os.path.lexists(worktree):
        _git(repo_path, "worktree", "remove", "--force", worktree)
        shutil.rmtree(worktree, ignore_errors=True)
    _git(repo_path, "worktree", "prune")
    if branch:
        _git(repo_path, "branch", "-D", branch)


def _reusable(entry, repo_path):
    worktree = os.path.realpath(entry.get("path") or "")
    return bool(entry.get("path")) and os.path.isdir(worktree) and worktree in _registered(repo_path)


def prepare(root, slug, base_branch="HEAD", selected=None, pins=True):
    root = os.path.realpath(root)
    selected = _selected(root, slug) if selected is None else selected
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
    pinned = _pinned(root, slug) if pins else {}
    reused, created = [], []

    if mode == "default":
        template = DEFAULT_BRANCH
        for repo in selected:
            repo_path = discovered[repo]
            worktree = os.path.join(root, DEFAULT_DIR, slug, repo)
            if (entries.get(repo) or {}).get("pending"):
                # an earlier attempt stopped between `git worktree add` and its checks: what is
                # there is this run's own, half-made — discard it and make it again
                _discard(repo_path, worktree, entries.pop(repo).get("branch"))
                _save_record(root, slug, record)
            if repo in entries and _reusable(entries[repo], repo_path):
                reused.append(repo)
                continue
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
            # recorded first: a run that stops before the checks below finish still knows the
            # worktree and branch are its own, so a retry removes them instead of refusing
            entries[repo] = {"path": os.path.realpath(worktree), "branch": branch,
                             "created_by_maestro": True, "pending": True}
            _save_record(root, slug, record)
            try:
                rc, out = _git(repo_path, "worktree", "add", "-q", "-b", branch, worktree, base)
                if rc:
                    raise WorktreeError(f"{repo}: git worktree add failed: {out[-400:]}")
                worktree = os.path.realpath(worktree)
                _branch, head = _check_new(repo, repo_path, worktree, branch, pinned.get(repo))
            except BaseException:
                _discard(repo_path, worktree, branch)
                entries.pop(repo, None)
                _save_record(root, slug, record)
                raise
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
            command = _command(settings["create"], root, slug, base_branch)
            log = run_layout.path(slug, root, f"{run_layout.LOGS_DIR}/worktrees/create.log")
            result = repo_checks._run(command, root, project_config.DEFAULT_TIMEOUT_S, log,
                                      {"MAESTRO_SLUG": slug, "MAESTRO_ROOT": root,
                                       "MAESTRO_BASE_BRANCH": base_branch})
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


# -- a bugfix sandbox: each repository on its own base ---------------------------------------
def _has_remote(repo_path):
    rc, out = _git(repo_path, "remote")
    return rc == 0 and bool(out.strip())


def _ref_exists(repo_path, ref):
    return _git(repo_path, "rev-parse", "--verify", "--quiet", ref)[0] == 0


def default_branch(repo_path):
    """The repository's default branch: origin/HEAD, else main or master, else the current one."""
    rc, out = _git(repo_path, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if rc == 0 and out.startswith("origin/"):
        return out[len("origin/"):]
    for name in ("main", "master"):
        if _ref_exists(repo_path, f"refs/heads/{name}") or \
                _ref_exists(repo_path, f"refs/remotes/origin/{name}"):
            return name
    rc, out = _git(repo_path, "branch", "--show-current")
    return out if rc == 0 else ""


def find_branch(repo_path, branch):
    """The ref naming `branch` in this repository: the local branch, else origin's, else ""."""
    if _ref_exists(repo_path, f"refs/heads/{branch}"):
        return branch
    if _ref_exists(repo_path, f"refs/remotes/origin/{branch}"):
        return f"origin/{branch}"
    return ""


def check_base(root, branch, repos, fetch=True):
    """Does each repository have `branch`, locally or on origin? Fetches first (a repository
    without a remote, or offline, is checked as it is). Creates nothing."""
    root = os.path.realpath(root)
    discovered = dict(codebase_scan.discover_repos(root))
    rows = []
    for repo in repos:
        repo_path = discovered.get(repo)
        if not repo_path:
            rows.append({"repo": repo, "present": False, "ref": "", "default_branch": "",
                         "problem": "not found in the workspace"})
            continue
        if fetch and _has_remote(repo_path):
            _git(repo_path, "fetch", "--quiet")
        ref = find_branch(repo_path, branch)
        rows.append({"repo": repo, "present": bool(ref), "ref": ref,
                     "default_branch": default_branch(repo_path)})
    missing = [row["repo"] for row in rows if not row["present"]]
    if missing:
        summary = f"{branch} is missing in {', '.join(missing)}"
    else:
        summary = f"{branch} exists in every repository"
    return {"branch": branch, "all_present": not missing, "missing_csv": ",".join(missing),
            "repos": rows, "summary": summary}


def load_base_map(value, root="."):
    """{repo: base ref} from a JSON file path (absolute, or relative to the cwd or the root) or
    inline JSON."""
    candidates = [value] if os.path.isabs(value) else [value, os.path.join(root, value)]
    found = next((path for path in candidates if os.path.isfile(path)), None)
    try:
        if found:
            with open(found, encoding="utf-8") as fh:
                doc = json.load(fh)
        else:
            doc = json.loads(value)
    except (OSError, ValueError) as exc:
        raise WorktreeError(f"cannot read the base map {value!r}: {exc}") from None
    if not isinstance(doc, dict) or not doc or not all(
            isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in doc.items()):
        raise WorktreeError("the base map must be a JSON object {repo: base branch}, not empty")
    return {repo: base.strip() for repo, base in doc.items()}


def _parse_named(text):
    """`web=release-2, api=hotfix` -> ({repo: branch}, one name for all or "")."""
    pairs, bare = {}, []
    for token in re.split(r"[\s,;]+", (text or "").strip()):
        if not token:
            continue
        if "=" in token:
            repo, _sep, branch = token.partition("=")
            if repo.strip() and branch.strip():
                pairs[repo.strip()] = branch.strip()
        else:
            bare.append(token)
    return pairs, (bare[0] if len(bare) == 1 else "")


def bug_bases(root, slug, branch, rows, choice="as-is", named=""):
    """Each repository's sandbox base: `branch` where check-base found it; for the others the
    person's answer — `default` (the repository's default branch) or `named` (`repo=b` pairs, or
    one branch for all of them). -> {valid, problem, bases, repos_csv, path, summary}; writes the
    base map (.engine/bug-bases.json) only when every repository has a base that exists."""
    rows = [row for row in rows or [] if isinstance(row, dict) and row.get("repo")]
    out = {"valid": False, "problem": "", "bases": {}, "repos_csv": "", "path": "",
           "summary": ""}
    if not rows:
        out["problem"] = "the branch check lists no repositories"
        out["summary"] = out["problem"]
        return out
    pairs, one = _parse_named(named) if choice == "named" else ({}, "")
    known = {row["repo"] for row in rows}
    problems = [f"{repo} is not one of the repositories this bug affects"
                for repo in pairs if repo not in known]
    bases = {}
    discovered = None if _simulated() else dict(codebase_scan.discover_repos(os.path.realpath(root)))
    for row in rows:
        repo = row["repo"]
        named_here = repo in pairs or (choice == "named" and not row.get("present") and one)
        if repo in pairs:
            base = pairs[repo]
        elif row.get("present"):
            base = branch
        elif choice == "default":
            base = row.get("default_branch") or ""
            if not base:
                problems.append(f"{repo} has no default branch to use")
                continue
        elif choice == "named" and one:
            base = one
        elif choice == "named":
            problems.append(f"no branch named for {repo}")
            continue
        else:
            problems.append(f"{repo} has no branch {branch} and no other base was chosen")
            continue
        if named_here and discovered is not None:
            # a branch the person typed: it must exist before anything is built on it
            repo_path = discovered.get(repo)
            if not repo_path or not (find_branch(repo_path, base) or _ref_exists(repo_path, base)):
                problems.append(f"{repo} has no branch {base}")
                continue
        bases[repo] = base
    if problems:
        out["problem"] = "; ".join(problems)
        out["summary"] = "Could not settle the base branches: " + out["problem"]
        return out
    path = run_layout.path(slug, root, run_layout.BUG_BASES)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(bases, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    out.update({"valid": True, "bases": bases, "repos_csv": ",".join(bases),
                "path": os.path.relpath(path, root),
                "summary": "Bases: " + ", ".join(f"{repo} on {base}"
                                                 for repo, base in bases.items())})
    return out


def sandbox_path(root, slug):
    return run_layout.path(slug, root, run_layout.SANDBOX)


def _write_sandbox(root, slug, record, bases):
    """The sandbox as a manifest (qa_env.py up --manifest): each repository's worktree and
    commit, plus the branch it is on and the base it came from."""
    entries = []
    for repo in bases:
        entry = (record.get("repos") or {}).get(repo) or {}
        worktree = entry.get("path", "")
        rc, head = _git(worktree, "rev-parse", "HEAD") if worktree else (1, "")
        entries.append({"repo": repo, "worktree": worktree,
                        "commit": head if rc == 0 else entry.get("base_commit", ""),
                        "branch": entry.get("branch", ""), "base": bases[repo],
                        "base_commit": entry.get("base_commit", "")})
    doc = {"schema_version": 1, "feature_slug": slug, "kind": "sandbox", "repositories": entries}
    path = sandbox_path(root, slug)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def prepare_sandbox(root, slug, bases):
    """One worktree per repository on `fix/<slug>-<repo>`, off that repository's base. Every
    repository is checked before anything is created, and a failure part-way removes what this
    call made, so there is never a half-built sandbox. No workspace-lock pin: the base is the
    person's branch."""
    root = os.path.realpath(root)
    repos = list(bases)
    settings = _settings(root)
    if settings:
        distinct = sorted(set(bases.values()))
        if len(distinct) > 1:
            raise WorktreeError(
                "worktree.create in maestro.config.yaml builds the sandbox from one base branch, "
                f"but these repositories need different ones ({', '.join(distinct)})")
        result = prepare(root, slug, base_branch=distinct[0], selected=repos, pins=False)
        record = load_record(root, slug) or {}
        record["bases"] = bases
        _save_record(root, slug, record)
        path = _write_sandbox(root, slug, record, bases)
        return {**result, "sandbox_path": os.path.relpath(path, root)}

    discovered = dict(codebase_scan.discover_repos(root))
    record = load_record(root, slug) or {}
    if record.get("mode") not in (None, "default"):
        raise WorktreeError(f"this feature's worktrees were made with the {record['mode']} "
                            "method; remove them first")
    record.update({"schema_version": SCHEMA_VERSION, "slug": slug, "mode": "default",
                   "bases": bases})
    entries = record.setdefault("repos", {})
    plan, reused, problems = {}, [], []
    for repo in repos:
        repo_path = discovered.get(repo)
        if not repo_path:
            problems.append(f"{repo}: not found in the workspace")
            continue
        if repo in entries and _reusable(entries[repo], repo_path):
            reused.append(repo)
            continue
        worktree = os.path.join(root, DEFAULT_DIR, slug, repo)
        branch = _fill(FIX_BRANCH, slug=slug, repo=repo)
        if os.path.exists(worktree):
            problems.append(f"{repo}: {os.path.relpath(worktree, root)} already exists and this "
                            "run did not create it")
        if _ref_exists(repo_path, f"refs/heads/{branch}"):
            problems.append(f"{repo}: branch {branch} already exists and this run did not "
                            "create it")
        base = bases[repo]
        ref = find_branch(repo_path, base) or (base if _ref_exists(repo_path, base) else "")
        rc, commit = _git(repo_path, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") \
            if ref else (1, "")
        if rc:
            problems.append(f"{repo}: base {base} not found")
        plan[repo] = (repo_path, worktree, branch, commit)
    if problems:
        raise WorktreeError("cannot build the sandbox: " + "; ".join(problems))

    created = []
    try:
        for repo, (repo_path, worktree, branch, commit) in plan.items():
            _ignore_default_dir(root)
            os.makedirs(os.path.dirname(worktree), exist_ok=True)
            entries[repo] = {"path": os.path.realpath(worktree), "branch": branch,
                             "created_by_maestro": True, "pending": True}
            _save_record(root, slug, record)
            created.append(repo)
            rc, out = _git(repo_path, "worktree", "add", "-q", "-b", branch, worktree, commit)
            if rc:
                raise WorktreeError(f"{repo}: git worktree add failed: {out[-400:]}")
            worktree = os.path.realpath(worktree)
            _branch, head = _check_new(repo, repo_path, worktree, branch, None)
            entries[repo] = {"path": worktree, "branch": branch, "base": bases[repo],
                             "base_commit": head, "created_by_maestro": True}
            _save_record(root, slug, record)
    except BaseException:
        for repo in created:
            repo_path, worktree, branch, _commit = plan[repo]
            _discard(repo_path, worktree, branch)
            entries.pop(repo, None)
        _save_record(root, slug, record)
        raise
    path = _write_sandbox(root, slug, record, bases)
    parts = []
    if created:
        parts.append(f"created {', '.join(created)}")
    if reused:
        parts.append(f"reused {', '.join(reused)}")
    return {"mode": "default", "repos_csv": ",".join(repos), "created_csv": ",".join(created),
            "reused_csv": ",".join(reused), "path": os.path.relpath(record_path(root, slug), root),
            "sandbox_path": os.path.relpath(path, root),
            "summary": "Sandbox: " + ("; ".join(parts) or "none needed")}


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
    path = run_layout.path(slug, root, run_layout.DELIVERY)
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
        log = run_layout.path(slug, root, f"{run_layout.LOGS_DIR}/worktrees/remove.log")
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
    parser.add_argument("command", choices=["prepare", "remove", "check-base", "bases"])
    parser.add_argument("--root", default=".")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--branch", default="", help="check-base: the branch to look for")
    parser.add_argument("--repos", default="", help="check-base, bases: the repositories, a,b")
    parser.add_argument("--base-map", default="",
                        help="prepare: {repo: base ref} (a JSON file or inline JSON) for a "
                             "bugfix sandbox")
    parser.add_argument("--choice", default="as-is",
                        help="bases: as-is | default | named (empty or anything else: as-is)")
    parser.add_argument("--named", default="", help="bases: `repo=branch` pairs, or one branch")
    args = parser.parse_args(argv)
    if args.command == "bases":
        repos = [r.strip() for r in args.repos.split(",") if r.strip()]
        if not args.branch or not repos:
            print("FAIL: bases needs --branch and --repos", file=sys.stderr)
            return 1
        if _simulated():  # as check-base simulates it: the branch is everywhere
            rows = [{"repo": r, "present": True, "ref": args.branch, "default_branch": "main"}
                    for r in repos]
        else:
            rows = check_base(args.root, args.branch, repos, fetch=False)["repos"]
        choice = args.choice if args.choice in ("default", "named") else "as-is"
        print(json.dumps(bug_bases(args.root, args.slug, args.branch, rows, choice,
                                   args.named)))
        return 0
    if args.command == "check-base":
        repos = [r.strip() for r in args.repos.split(",") if r.strip()]
        if not args.branch or not repos:
            print("FAIL: check-base needs --branch and --repos", file=sys.stderr)
            return 1
        if _simulated():
            print(json.dumps({"branch": args.branch, "all_present": True, "missing_csv": "",
                              "repos": [{"repo": r, "present": True, "ref": args.branch,
                                         "default_branch": "main"} for r in repos],
                              "summary": "[simulated] the branch exists everywhere"}))
            return 0
        print(json.dumps(check_base(args.root, args.branch, repos)))
        return 0
    if _simulated() and args.command == "prepare" and args.base_map:
        # a simulated sandbox: no worktree, but the record the bug-fix steps read
        try:
            bases = load_base_map(args.base_map, args.root)
        except WorktreeError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
        path = sandbox_path(args.root, args.slug)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "feature_slug": args.slug, "kind": "sandbox",
                       "repositories": [
                           {"repo": repo, "worktree": "[simulated: no code was checked out]",
                            "commit": "[simulated commit]",
                            "branch": _fill(FIX_BRANCH, slug=args.slug, repo=repo),
                            "base": base, "base_commit": "[simulated commit]"}
                           for repo, base in bases.items()]}, fh, indent=2)
            fh.write("\n")
        print(json.dumps({"mode": "simulated", "repos_csv": ",".join(bases), "created_csv": "",
                          "reused_csv": "", "sandbox_path": os.path.relpath(path, args.root),
                          "summary": "[simulated] sandbox record only, no worktrees"}))
        return 0
    if _simulated():
        print(json.dumps({"mode": "simulated", "repos_csv": "", "created_csv": "",
                          "reused_csv": "", "removed": False, "kept_csv": "",
                          "summary": "[simulated] no worktrees"}))
        return 0
    if args.command == "remove":
        print(json.dumps(remove(args.root, args.slug)))
        return 0
    try:
        if args.base_map:
            print(json.dumps(prepare_sandbox(args.root, args.slug,
                                             load_base_map(args.base_map, args.root))))
        else:
            print(json.dumps(prepare(args.root, args.slug)))
    except WorktreeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
