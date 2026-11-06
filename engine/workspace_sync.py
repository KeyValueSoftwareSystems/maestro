#!/usr/bin/env python3
"""Deterministic multi-repo remote + knowledge freshness coordination.

The LLM decides how documentation changes; this module owns the safety-critical facts:
which repositories exist, which upstream each current branch tracks, whether a fast-forward
is safe, which commits the living docs describe, and which exact commits a feature pins.

Commands
--------
  plan              Fetch current-branch remotes in parallel and write one consolidated plan.
                    `--fetch-errors note` keeps a failed fetch in the summary without asking the
                    person again (a later checkpoint, once the first one has asked).
  apply             Verify a plan, then fast-forward only repositories proven safe in it.
  record-knowledge  Stamp the exact repository commits assessed by a knowledge refresh.
  ensure-index-state  Fill docs_sha256/evidence when docs are current but provenance is incomplete.
  lock              Pin exact repository commits for a feature/checkpoint.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import subprocess
import sys

import codebase_scan


SCHEMA_VERSION = 1
# Shared provenance file used by Maestro and the template workspace-index skill.
DEFAULT_INDEX_STATE = "docs/.index-state.yaml"
# Pre-unification path; still read when the YAML is absent so existing workspaces stay current.
LEGACY_KNOWLEDGE_STATE = ".maestro/index/knowledge-state.json"
MANAGED_DIRTY_PREFIXES = (
    ".maestro/runs/",
    ".maestro/memory/",
    ".maestro/index/",
)
MANAGED_DIRTY_PATHS = {"docs/codebase-map.md"}
MAX_CHANGED = 500


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _git_env():
    """Never block on a credential/host-key prompt; fail a dead connection fast."""
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GCM_INTERACTIVE", "never")
    env.setdefault("GIT_HTTP_LOW_SPEED_LIMIT", "1000")
    env.setdefault("GIT_HTTP_LOW_SPEED_TIME", "30")
    if "GIT_SSH_COMMAND" not in env and "GIT_SSH" not in env:
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=10"
    return env


_GIT_ENV = _git_env()


def _git(repo, *args, timeout=60):
    try:
        proc = subprocess.run(
            ["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout,
            env=_GIT_ENV,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path, doc):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _yaml_scalar(value):
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if text == "" or any(ch in text for ch in ":#{}[]&*!|>'\"%@`") or text.strip() != text:
        return json.dumps(text)
    return text


def _atomic_index_state(path, doc):
    """Write docs/.index-state.yaml without depending on PyYAML."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = [
        "# Auto-generated index provenance (Maestro + workspace-index). Do not edit manually.",
        f"schema_version: {int(doc.get('schema_version', SCHEMA_VERSION))}",
        f"indexed_at: {_yaml_scalar(doc.get('indexed_at', ''))}",
    ]
    if doc.get("docs_sha256"):
        lines.append(f"docs_sha256: {_yaml_scalar(doc['docs_sha256'])}")
    if doc.get("evidence"):
        lines.append(f"evidence: {_yaml_scalar(doc['evidence'])}")
    if doc.get("evidence_sha256"):
        lines.append(f"evidence_sha256: {_yaml_scalar(doc['evidence_sha256'])}")
    lines.append("repos:")
    for entry in doc.get("repos") or []:
        lines.append(f"  - name: {_yaml_scalar(entry.get('name', ''))}")
        if entry.get("path"):
            lines.append(f"    path: {_yaml_scalar(entry['path'])}")
        if entry.get("branch"):
            lines.append(f"    branch: {_yaml_scalar(entry['branch'])}")
        lines.append(f"    commit: {_yaml_scalar(entry.get('commit', ''))}")
        if entry.get("indexed_at"):
            lines.append(f"    indexed_at: {_yaml_scalar(entry['indexed_at'])}")
    lines.append("")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _parse_index_state_yaml(text):
    """Minimal parser for the shared index-state schema (no PyYAML dependency)."""
    doc = {"repos": []}
    current = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith("schema_version:"):
            try:
                doc["schema_version"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                doc["schema_version"] = None
            continue
        if line.startswith("indexed_at:") or line.startswith("updated_at:"):
            doc["indexed_at"] = _unquote(line.split(":", 1)[1].strip())
            continue
        if line.startswith("docs_sha256:"):
            doc["docs_sha256"] = _unquote(line.split(":", 1)[1].strip())
            continue
        if line.startswith("evidence:") and not line.startswith("evidence_sha256:"):
            doc["evidence"] = _unquote(line.split(":", 1)[1].strip())
            continue
        if line.startswith("evidence_sha256:"):
            doc["evidence_sha256"] = _unquote(line.split(":", 1)[1].strip())
            continue
        if line.strip() == "repos:":
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("- name:") or stripped.startswith("- name :"):
            if current and current.get("name"):
                doc["repos"].append(current)
            current = {"name": _unquote(stripped.split(":", 1)[1].strip())}
            continue
        if current is None or indent < 2:
            continue
        for key in ("path", "branch", "commit", "indexed_at"):
            prefix = f"{key}:"
            if stripped.startswith(prefix):
                current[key] = _unquote(stripped.split(":", 1)[1].strip())
                break
    if current and current.get("name"):
        doc["repos"].append(current)
    return doc


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        try:
            return json.loads(value) if value[0] == '"' else value[1:-1]
        except ValueError:
            return value[1:-1]
    return value


def _read_index_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    if not text.strip():
        return None
    if path.endswith(".json"):
        try:
            return json.loads(text)
        except ValueError:
            return None
    try:
        return _parse_index_state_yaml(text)
    except (TypeError, ValueError):
        return None


def _resolve(root, path):
    return path if os.path.isabs(path) else os.path.join(root, path)


def _rel(path, root):
    return os.path.relpath(path, root)


def _porcelain_path(line):
    value = line[3:] if len(line) >= 4 else line
    if " -> " in value:
        value = value.split(" -> ", 1)[1]
    return value.strip('"')


def _is_managed_parent(path):
    """A collapsed untracked dir (`docs/`) that may hold only engine-managed files."""
    return path.endswith("/") and any(
        managed.startswith(path)
        for managed in (*MANAGED_DIRTY_PATHS, *MANAGED_DIRTY_PREFIXES)
    )


def _dirty_paths(repo):
    # `normal` lists a new untracked directory once instead of walking every file in it;
    # only directories that could contain engine-managed paths are expanded.
    rc, out, _ = _git(repo, "status", "--porcelain=v1", "--untracked-files=normal")
    if rc != 0:
        return ["<status-unavailable>"]
    lines = []
    for line in out.splitlines():
        path = _porcelain_path(line)
        if line.startswith("?? ") and _is_managed_parent(path):
            rc, sub, _ = _git(repo, "status", "--porcelain=v1", "--untracked-files=all",
                              "--", path)
            if rc != 0:
                return ["<status-unavailable>"]
            lines.extend(sub.splitlines())
        else:
            lines.append(line)
    paths = []
    for line in lines:
        path = _porcelain_path(line)
        if (path in MANAGED_DIRTY_PATHS
                or any(path == p.rstrip("/") or path.startswith(p)
                       for p in MANAGED_DIRTY_PREFIXES)):
            continue
        paths.append(path)
    return paths


def _branch_facts(name, repo, root):
    head = codebase_scan._head(repo)
    rc, branch, _ = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    if rc != 0:
        branch = ""
    upstream = ""
    remote = ""
    upstream_commit = ""
    if branch:
        rc, upstream, _ = _git(
            repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}",
        )
        if rc != 0:
            upstream = ""
        if upstream:
            rc, remote, _ = _git(repo, "config", "--get", f"branch.{branch}.remote")
            if rc != 0 or remote == ".":
                remote = ""
    return {
        "name": name,
        "path": _rel(repo, root),
        "branch": branch,
        "head_commit": head or "",
        "upstream": upstream,
        "upstream_remote": remote,
        "upstream_commit": upstream_commit,
    }


def _fetch_one(entry, root):
    repo = os.path.join(root, entry["path"])
    if not entry["upstream"] or not entry["upstream_remote"]:
        return entry["name"], ""
    remote = entry["upstream_remote"]
    args = ["fetch", "--prune", remote]
    # Fetch only the tracked branch into its own tracking ref — not every branch and tag.
    rc_m, merge_ref, _ = _git(repo, "config", "--get", f"branch.{entry['branch']}.merge")
    rc_u, tracking_ref, _ = _git(
        repo, "rev-parse", "--symbolic-full-name", "@{upstream}",
    )
    if (rc_m == 0 and rc_u == 0 and merge_ref.startswith("refs/heads/")
            and tracking_ref.startswith(f"refs/remotes/{remote}/")):
        args = ["fetch", "--no-tags", remote, f"+{merge_ref}:{tracking_ref}"]
    rc, _, err = _git(repo, *args, timeout=60)
    return entry["name"], "" if rc == 0 else (err or "fetch failed")


def _classify(entry, root, fetch_error=""):
    repo = os.path.join(root, entry["path"])
    dirty_paths = _dirty_paths(repo)
    upstream_commit = ""
    ahead = behind = 0
    if entry["upstream"]:
        rc, upstream_commit, _ = _git(repo, "rev-parse", entry["upstream"])
        if rc != 0:
            upstream_commit = ""
        if upstream_commit:
            rc, counts, _ = _git(repo, "rev-list", "--left-right", "--count",
                                 f"HEAD...{entry['upstream']}")
            if rc == 0:
                parts = counts.split()
                if len(parts) == 2:
                    ahead, behind = (int(parts[0]), int(parts[1]))
    if not entry["branch"]:
        status = "detached"
    elif not entry["upstream"]:
        status = "no-upstream"
    elif ahead and behind:
        status = "diverged"
    elif behind:
        status = "behind"
    elif ahead:
        status = "ahead"
    else:
        status = "current"
    entry.update({
        "upstream_commit": upstream_commit,
        "ahead": ahead,
        "behind": behind,
        "dirty": bool(dirty_paths),
        "dirty_paths": dirty_paths[:50],
        "fetch_error": fetch_error,
        "status": status,
        "pullable": status == "behind" and not dirty_paths and not fetch_error,
    })
    return entry


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _repo_commits(repos):
    return {r["name"]: {"path": r["path"], "commit": r["head_commit"]} for r in repos}


def _load_index_state(root, state_path):
    """Load shared index provenance; fall back to legacy knowledge-state.json once."""
    state_abs = _resolve(root, state_path)
    state = _read_index_state(state_abs)
    if state is not None:
        return state, state_abs
    legacy_abs = _resolve(root, LEGACY_KNOWLEDGE_STATE)
    if os.path.abspath(legacy_abs) != os.path.abspath(state_abs):
        legacy = _read_index_state(legacy_abs)
        if legacy is not None:
            # Normalize legacy JSON field name for callers that expect indexed_at.
            if "indexed_at" not in legacy and legacy.get("updated_at"):
                legacy["indexed_at"] = legacy["updated_at"]
            return legacy, legacy_abs
    return None, state_abs


def _knowledge_status(root, repos, state_path):
    state, _ = _load_index_state(root, state_path)
    current = _repo_commits(repos)
    recorded = {}
    # Accept schema_version == 1, or legacy/template files that omit it but list repos.
    if isinstance(state, dict) and state.get("schema_version") in (None, SCHEMA_VERSION):
        for entry in state.get("repos") or []:
            if isinstance(entry, dict) and entry.get("name"):
                name = entry["name"]
                path = entry.get("path") or f"codebase/{name}"
                recorded[name] = {"path": path, "commit": entry.get("commit", "")}
    architecture = os.path.join(root, "docs", "architecture.md")
    technical = os.path.join(root, "docs", "technical")
    functional = os.path.join(root, "docs", "functional")
    has_technical = os.path.isdir(technical) and any(
        name.endswith(".md") for name in os.listdir(technical)
    )
    has_functional = os.path.isdir(functional) and any(
        name.endswith(".md") for name in os.listdir(functional)
    )
    stale_repos = sorted(name for name, value in current.items() if recorded.get(name) != value)
    removed_repos = sorted(set(recorded) - set(current))
    missing_docs = (not os.path.isfile(architecture) or os.path.getsize(architecture) == 0
                    or not has_technical or not has_functional)
    docs_hash_stale = False
    if isinstance(state, dict) and state.get("docs_sha256"):
        docs_hash_stale = state["docs_sha256"] != _docs_hash(root)
    return {
        "stale": bool(stale_repos or removed_repos or missing_docs or docs_hash_stale),
        "stale_repos": stale_repos,
        "removed_repos": removed_repos,
        "missing_docs": missing_docs,
        "docs_hash_stale": docs_hash_stale,
        "state_missing": state is None,
    }, recorded


def _map_stale_repos(root, repos):
    stale = []
    for entry in repos:
        repo = os.path.join(root, entry["path"])
        if not codebase_scan.map_is_current(repo, head=entry["head_commit"]):
            stale.append(entry["name"])
    return stale


def _lock_drift(lock_path, repos):
    lock = _read_json(lock_path) if lock_path else None
    if not lock:
        return []
    pinned = {e.get("name"): (e.get("path"), e.get("commit"))
              for e in lock.get("repos") or [] if isinstance(e, dict)}
    current = {e["name"]: (e["path"], e["head_commit"]) for e in repos}
    return sorted(name for name in set(pinned) | set(current)
                  if pinned.get(name) != current.get(name))


def _changed_files(root, repo, previous):
    if not previous or not repo["head_commit"] or previous == repo["head_commit"]:
        return []
    path = os.path.join(root, repo["path"])
    rc, out, _ = _git(path, "diff", "--name-only", previous, repo["head_commit"])
    if rc != 0:
        return []
    return [line for line in out.splitlines() if line.strip()][:MAX_CHANGED]


def _summary(repos, knowledge, map_stale, lock_drift):
    lines = []
    for repo in repos:
        bits = [f"{repo['name']}: {repo['branch'] or 'detached'}"]
        if repo["status"] == "behind":
            bits.append(f"{repo['behind']} commit(s) behind {repo['upstream']}")
            bits.append("safe to fast-forward" if repo["pullable"] else "not safe to update automatically")
        elif repo["status"] == "diverged":
            bits.append(f"diverged ({repo['ahead']} ahead, {repo['behind']} behind)")
        elif repo["status"] == "ahead":
            bits.append(f"{repo['ahead']} commit(s) ahead")
        elif repo["status"] == "current":
            bits.append("current")
        elif repo["status"] == "no-upstream":
            bits.append("no upstream configured")
        else:
            bits.append(repo["status"])
        if repo["dirty"]:
            bits.append("has local changes")
        if repo["fetch_error"]:
            bits.append(f"fetch failed: {repo['fetch_error']}")
        lines.append("- " + "; ".join(bits))
    if knowledge["stale"]:
        if knowledge.get("docs_hash_stale") and not (
                knowledge["stale_repos"] or knowledge["removed_repos"] or knowledge["missing_docs"]):
            lines.append("- Living docs content changed since last index (docs_sha256 drift).")
        else:
            names = ", ".join(knowledge["stale_repos"] or knowledge["removed_repos"] or ["workspace"])
            lines.append(f"- Living technical/functional knowledge needs refresh: {names}.")
    if map_stale:
        lines.append("- Codebase maps need refresh: " + ", ".join(map_stale) + ".")
    if lock_drift:
        lines.append("- Feature commit lock no longer matches: " + ", ".join(lock_drift) + ".")
    return "\n".join(lines) or "Workspace is current."


def cmd_plan(root, out, lock=None, index_state=DEFAULT_INDEX_STATE, fetch=True,
             remote_only=False, on_fetch_error="ask"):
    root = os.path.abspath(root)
    out_abs = _resolve(root, out)
    lock_abs = _resolve(root, lock) if lock else None
    discovered = codebase_scan.discover_repos(root)
    repos = []
    if discovered:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(discovered))) as pool:
            repos = list(pool.map(lambda item: _branch_facts(item[0], item[1], root), discovered))
    fetch_errors = {}
    if fetch and repos:
        # Network-bound: one worker per repo so a slow remote never queues the others.
        workers = min(32, len(repos))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for name, error in pool.map(lambda e: _fetch_one(e, root), repos):
                fetch_errors[name] = error
    if repos:
        workers = min(8, len(repos))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            repos = list(pool.map(
                lambda repo: _classify(repo, root, fetch_errors.get(repo["name"], "")),
                repos,
            ))
    knowledge, recorded = _knowledge_status(root, repos, index_state)
    map_stale = _map_stale_repos(root, repos)
    if remote_only:
        knowledge = {**knowledge, "stale": False}
        map_stale = []
    lock_drift = _lock_drift(lock_abs, repos)
    for repo in repos:
        previous = (recorded.get(repo["name"]) or {}).get("commit")
        repo["knowledge_changed_files"] = _changed_files(root, repo, previous)
    remote_attention = any(
        repo["behind"] or repo["status"] == "diverged" or repo["dirty"]
        or (repo["fetch_error"] and on_fetch_error != "note") for repo in repos
    )
    refresh_needed = knowledge["stale"] or bool(map_stale)
    doc = {
        "schema_version": SCHEMA_VERSION,
        "created_at": _now(),
        "root": root,
        "repos": repos,
        "knowledge": knowledge,
        "map_stale_repos": map_stale,
        "lock_drift_repos": lock_drift,
        "refresh_needed": refresh_needed,
        "needs_attention": remote_attention or refresh_needed or bool(lock_drift),
        "summary": _summary(repos, knowledge, map_stale, lock_drift),
    }
    _atomic_json(out_abs, doc)
    print(json.dumps({
        "plan_path": _rel(out_abs, root),
        "plan_sha256": _sha256(out_abs),
        "needs_attention": doc["needs_attention"],
        "refresh_needed": refresh_needed,
        "pullable_count": sum(1 for repo in repos if repo["pullable"]),
        "summary": doc["summary"],
    }))
    return 0


def _load_verified_plan(root, plan, expected_hash):
    path = _resolve(root, plan)
    if not expected_hash or _sha256(path) != expected_hash:
        raise ValueError("workspace sync plan is missing or changed after the engine created it")
    doc = _read_json(path)
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid workspace sync plan schema")
    if os.path.abspath(doc.get("root", "")) != os.path.abspath(root):
        raise ValueError("workspace sync plan belongs to a different root")
    return doc


def cmd_apply(root, plan, plan_sha256, out):
    root = os.path.abspath(root)
    out_abs = _resolve(root, out)
    try:
        doc = _load_verified_plan(root, plan, plan_sha256)
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    discovered = {name: path for name, path in codebase_scan.discover_repos(root)}
    failures = []
    candidates = []
    blocked = []
    for entry in doc.get("repos") or []:
        repo = discovered.get(entry.get("name"))
        if not entry.get("pullable"):
            if entry.get("behind") or entry.get("status") == "diverged":
                blocked.append(entry.get("name"))
            continue
        if not repo or _rel(repo, root) != entry.get("path"):
            failures.append(f"{entry.get('name')}: repository path changed")
            continue
        if codebase_scan._head(repo) != entry.get("head_commit"):
            failures.append(f"{entry['name']}: HEAD changed after planning")
            continue
        if _dirty_paths(repo):
            failures.append(f"{entry['name']}: local changes appeared after planning")
            continue
        rc, upstream_commit, _ = _git(repo, "rev-parse", entry.get("upstream", ""))
        if rc != 0 or upstream_commit != entry.get("upstream_commit"):
            failures.append(f"{entry['name']}: upstream moved after planning; fetch again")
            continue
        candidates.append((entry, repo))
    if failures:
        print("FAIL: refusing workspace update: " + "; ".join(failures), file=sys.stderr)
        return 1
    updated = []
    for entry, repo in candidates:
        rc, _, err = _git(repo, "merge", "--ff-only", entry["upstream_commit"], timeout=120)
        if rc != 0:
            print(f"FAIL: {entry['name']}: fast-forward failed: {err}", file=sys.stderr)
            return 1
        updated.append({
            "name": entry["name"], "path": entry["path"],
            "from": entry["head_commit"], "to": codebase_scan._head(repo),
        })
    result = {
        "schema_version": SCHEMA_VERSION,
        "created_at": _now(),
        "root": root,
        "plan_sha256": plan_sha256,
        "updated_repos": updated,
        "blocked_repos": blocked,
        "refresh_needed": bool(updated) or bool(doc.get("refresh_needed")),
    }
    _atomic_json(out_abs, result)
    print(json.dumps({
        "result_path": _rel(out_abs, root),
        "result_sha256": _sha256(out_abs),
        "updated": bool(updated),
        "updated_repos_csv": ",".join(e["name"] for e in updated),
        "blocked_repos_csv": ",".join(blocked),
        "refresh_needed": result["refresh_needed"],
    }))
    return 0


def _docs_hash(root):
    docs = os.path.join(root, "docs")
    digest = hashlib.sha256()
    if not os.path.isdir(docs):
        return ""
    for base, dirs, files in os.walk(docs):
        dirs.sort()
        for name in sorted(files):
            if not name.endswith(".md"):
                continue
            path = os.path.join(base, name)
            digest.update(os.path.relpath(path, root).encode("utf-8"))
            with open(path, "rb") as fh:
                digest.update(fh.read())
    return digest.hexdigest()


def _provenance_fields_complete(state):
    return bool(
        isinstance(state, dict)
        and state.get("docs_sha256")
        and state.get("evidence")
        and state.get("evidence_sha256")
    )


def cmd_record_knowledge(root, evidence, state_path=DEFAULT_INDEX_STATE):
    root = os.path.abspath(root)
    evidence_abs = _resolve(root, evidence)
    architecture = os.path.join(root, "docs", "architecture.md")
    if not os.path.isfile(evidence_abs) or os.path.getsize(evidence_abs) == 0:
        print("FAIL: knowledge refresh evidence is missing or empty", file=sys.stderr)
        return 1
    if not os.path.isfile(architecture) or os.path.getsize(architecture) == 0:
        print("FAIL: docs/architecture.md is missing or empty", file=sys.stderr)
        return 1
    for surface in ("technical", "functional"):
        directory = os.path.join(root, "docs", surface)
        if not os.path.isdir(directory) or not any(
                name.endswith(".md") and os.path.getsize(os.path.join(directory, name)) > 0
                for name in os.listdir(directory)):
            print(f"FAIL: docs/{surface}/ has no non-empty Markdown domain docs", file=sys.stderr)
            return 1
    now = _now()
    repos = []
    for name, path in codebase_scan.discover_repos(root):
        head = codebase_scan._head(path)
        if not head:
            print(f"FAIL: {name}: cannot resolve HEAD", file=sys.stderr)
            return 1
        rc, branch, _ = _git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
        repos.append({
            "name": name,
            "path": _rel(path, root),
            "branch": branch if rc == 0 else "",
            "commit": head,
            "indexed_at": now,
        })
    state_abs = _resolve(root, state_path)
    doc = {
        "schema_version": SCHEMA_VERSION,
        "indexed_at": now,
        "repos": repos,
        "docs_sha256": _docs_hash(root),
        "evidence": _rel(evidence_abs, root),
        "evidence_sha256": _sha256(evidence_abs),
    }
    _atomic_index_state(state_abs, doc)
    print(json.dumps({
        "index_state_path": _rel(state_abs, root),
        "index_state_sha256": _sha256(state_abs),
        "knowledge_state_path": _rel(state_abs, root),  # back-compat alias
        "knowledge_state_sha256": _sha256(state_abs),
        "recorded_repos_csv": ",".join(e["name"] for e in repos),
        "ensured": True,
    }))
    return 0


def cmd_ensure_index_state(root, evidence, state_path=DEFAULT_INDEX_STATE):
    """Fill docs_sha256/evidence when living docs are current but provenance is incomplete.

    Used after template workspace-index + Maestro skip-authoring so content drift is
    detectable without a second prose pass. No-ops when fields are already present or
    when a knowledge refresh is still required (do not stamp stale docs as current).
    """
    root = os.path.abspath(root)
    state, _ = _load_index_state(root, state_path)
    if _provenance_fields_complete(state):
        print(json.dumps({
            "ensured": False,
            "reason": "already_complete",
            "index_state_path": state_path,
        }))
        return 0
    discovered = codebase_scan.discover_repos(root)
    repos = [_branch_facts(name, path, root) for name, path in discovered]
    knowledge, _ = _knowledge_status(root, repos, state_path)
    # Missing docs_sha256 does not mark stale; commit/doc gaps do. Only enrich when current.
    if knowledge["stale"]:
        print(json.dumps({
            "ensured": False,
            "reason": "refresh_needed",
            "stale_repos": knowledge["stale_repos"],
            "missing_docs": knowledge["missing_docs"],
        }))
        return 0
    return cmd_record_knowledge(root, evidence, state_path)


def cmd_lock(root, out, result=None):
    root = os.path.abspath(root)
    out_abs = _resolve(root, out)
    old = _read_json(out_abs)
    repos = []
    for name, path in codebase_scan.discover_repos(root):
        head = codebase_scan._head(path)
        if not head:
            print(f"FAIL: {name}: cannot pin unresolved HEAD", file=sys.stderr)
            return 1
        rc, branch, _ = _git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
        repos.append({
            "name": name, "path": _rel(path, root), "branch": branch if rc == 0 else "",
            "commit": head,
        })
    old_commits = {(e.get("name"), e.get("path"), e.get("commit"))
                   for e in (old or {}).get("repos", []) if isinstance(e, dict)}
    new_commits = {(e["name"], e["path"], e["commit"]) for e in repos}
    result_doc = _read_json(_resolve(root, result)) if result else None
    updated = bool((result_doc or {}).get("updated_repos"))
    doc = {
        "schema_version": SCHEMA_VERSION,
        "pinned_at": _now(),
        "repos": repos,
        "sync_result": result or "",
        "sync_result_sha256": _sha256(_resolve(root, result)) if result and result_doc else "",
    }
    _atomic_json(out_abs, doc)
    head_changed = bool(old) and old_commits != new_commits
    print(json.dumps({
        "lock_path": _rel(out_abs, root),
        "lock_sha256": _sha256(out_abs),
        "updated": updated,
        "head_changed": head_changed,
        "changed": updated or head_changed,
        "pinned_repos_csv": ",".join(e["name"] for e in repos),
    }))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan")
    p.add_argument("--root", default=".")
    p.add_argument("--out", required=True)
    p.add_argument("--lock")
    p.add_argument("--index-state", "--knowledge-state", default=DEFAULT_INDEX_STATE,
                   dest="index_state",
                   help="shared docs/.index-state.yaml provenance path")
    p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--remote-only", action="store_true",
                   help="ignore knowledge/map freshness (used before initial indexing)")
    p.add_argument("--fetch-errors", choices=("ask", "note"), default="ask",
                   help="note: a failed fetch alone does not need the person's attention")

    p = sub.add_parser("apply")
    p.add_argument("--root", default=".")
    p.add_argument("--plan", required=True)
    p.add_argument("--plan-sha256", required=True)
    p.add_argument("--out", required=True)

    p = sub.add_parser("record-knowledge")
    p.add_argument("--root", default=".")
    p.add_argument("--evidence", required=True)
    p.add_argument("--index-state", "--knowledge-state", default=DEFAULT_INDEX_STATE,
                   dest="index_state")

    p = sub.add_parser("ensure-index-state")
    p.add_argument("--root", default=".")
    p.add_argument("--evidence", default="docs/architecture.md")
    p.add_argument("--index-state", "--knowledge-state", default=DEFAULT_INDEX_STATE,
                   dest="index_state")

    p = sub.add_parser("lock")
    p.add_argument("--root", default=".")
    p.add_argument("--out", required=True)
    p.add_argument("--result")

    args = parser.parse_args(argv)
    if args.cmd == "plan":
        return cmd_plan(args.root, args.out, args.lock, args.index_state,
                        fetch=not args.no_fetch, remote_only=args.remote_only,
                        on_fetch_error=args.fetch_errors)
    if args.cmd == "apply":
        return cmd_apply(args.root, args.plan, args.plan_sha256, args.out)
    if args.cmd == "record-knowledge":
        return cmd_record_knowledge(args.root, args.evidence, args.index_state)
    if args.cmd == "ensure-index-state":
        return cmd_ensure_index_state(args.root, args.evidence, args.index_state)
    return cmd_lock(args.root, args.out, args.result)


if __name__ == "__main__":
    sys.exit(main())
