#!/usr/bin/env python3
"""Run a repository's configured checks in its worktree and write a verification receipt.

The engine — not an agent — decides whether an implementation builds and passes its tests.
Commands come only from maestro.config.yaml (`project_config`), run in this order when
configured: setup, build, typecheck, lint, test. A setup or build failure stops the run:
later checks would only repeat it. `build` and `test` are required; a missing one fails closed
with exit 2 ("not configured") instead of passing silently.

The receipt records the reviewed commit and, per check, the exact command, exit code,
duration and a hash of its log, so "tests passed" is a checkable record, not a claim.
Commands run with CI=true so watch-mode test runners exit.

Test-edit guard: with --base-repo, the receipt also lists EXISTING test files the branch
modified, renamed or deleted (repo `test_patterns`, or defaults). They are flagged for the
reviewer to justify, never auto-failed — agents can make tests pass by weakening them.

Usage: repo_checks.py --root . --repo backend --worktree <path> --out <receipt.json>
                      [--base-repo <main checkout>]
Last stdout line: {"passed", "failed_checks", "tests_changed", "receipt_path", "receipt_sha256",
                   "commit", "summary"}
Exit: 0 when the checks ran (pass or fail; route on `passed`), 2 when they cannot run.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_config  # noqa: E402
import state as statemod  # noqa: E402

ORDER = ("setup", "build", "typecheck", "lint", "test")
STOP_ON_FAILURE = ("setup", "build")
LOG_TAIL_CHARS = 4000


def _fail(message):
    print(f"cannot verify: {message}", file=sys.stderr)
    return 2


def _git_head(worktree):
    proc = subprocess.run(["git", "-C", worktree, "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _test_changes(worktree, base_repo, patterns):
    """Existing test files the branch modified, renamed or deleted since it left the main checkout.

    New test files are fine and not listed. Changes are flagged, not failed: updating a test is
    sometimes right (the approved design changed behavior), so the reviewer must justify each.
    Returns (changes, note) — note explains why the guard could not run.
    """
    if not base_repo:
        return [], "no base repository given"
    base_head = subprocess.run(["git", "-C", base_repo, "rev-parse", "HEAD"],
                               capture_output=True, text=True).stdout.strip()
    base = subprocess.run(["git", "-C", worktree, "merge-base", "HEAD", base_head],
                          capture_output=True, text=True).stdout.strip() if base_head else ""
    if not base:
        return [], "cannot find the commit this branch started from"
    proc = subprocess.run(["git", "-C", worktree, "diff", "--name-status", "-M", base],
                          capture_output=True, text=True)
    if proc.returncode:
        return [], "git diff failed"
    kinds = {"M": "modified", "D": "deleted", "R": "renamed", "T": "modified"}
    changes = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        kind = kinds.get(parts[0][:1])
        if kind and any(fnmatch.fnmatch(parts[1], p) for p in patterns):
            changes.append({"status": kind, "path": parts[1]})
    return changes, None


def _run(command, cwd, timeout, log_path):
    env = os.environ.copy()
    env.setdefault("CI", "true")
    started = time.monotonic()
    try:
        proc = subprocess.run(command, shell=True, cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=timeout)
        code, output, status = proc.returncode, proc.stdout + proc.stderr, None
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or b"") + (exc.stderr or b"")
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        code, output, status = 124, partial + f"\n[maestro] timed out after {timeout}s\n", "timed-out"
    duration = round(time.monotonic() - started, 1)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(f"$ {command}\n{output}")
    return {
        "exit_code": code,
        "duration_s": duration,
        "status": status or ("passed" if code == 0 else "failed"),
        "log_sha256": statemod.sha256_file(log_path),
        "tail": output[-LOG_TAIL_CHARS:],
    }


def run_checks(root, repo, worktree, out, base_repo=None):
    try:
        config = project_config.load(root)
    except project_config.ConfigError as exc:
        return _fail(str(exc))
    if config is None:
        return _fail(f"{project_config.CONFIG_FILE} not found; run `maestroctl preflight`")
    commands = project_config.repo_commands(config, repo)
    missing = [name for name in project_config.REQUIRED_COMMANDS if name not in commands]
    if missing:
        return _fail(f"repo {repo!r} has no {' or '.join(missing)} command in "
                     f"{project_config.CONFIG_FILE}")
    full_worktree = worktree if os.path.isabs(worktree) else os.path.join(root, worktree)
    if not os.path.isdir(full_worktree):
        return _fail(f"worktree {worktree!r} does not exist")
    commit = _git_head(full_worktree)
    if not commit:
        return _fail(f"worktree {worktree!r} is not a git checkout")

    timeout = project_config.repo_timeout(config, repo)
    full_out = out if os.path.isabs(out) else os.path.join(root, out)
    log_dir = os.path.splitext(full_out)[0] + "-logs"
    checks, stopped_by = [], None
    for name in ORDER:
        if name not in commands:
            continue
        if stopped_by:
            checks.append({"name": name, "command": commands[name], "status": "not-run"})
            continue
        result = _run(commands[name], full_worktree, timeout, os.path.join(log_dir, f"{name}.log"))
        checks.append({
            "name": name,
            "command": commands[name],
            "log": os.path.relpath(os.path.join(log_dir, f"{name}.log"), root),
            **result,
        })
        if result["status"] != "passed" and name in STOP_ON_FAILURE:
            stopped_by = name

    failed = [c["name"] for c in checks if c["status"] != "passed"]
    full_base = None
    if base_repo:
        full_base = base_repo if os.path.isabs(base_repo) else os.path.join(root, base_repo)
    test_changes, guard_note = _test_changes(
        full_worktree, full_base, project_config.repo_test_patterns(config, repo))
    receipt = {
        "schema_version": 1,
        "repo": repo,
        "worktree": worktree,
        "commit": commit,
        "verified_at": statemod.now_iso(),
        "passed": not failed,
        "skipped": [name for name in ORDER if name not in commands],
        "checks": checks,
        "test_changes": test_changes,
        "test_guard": guard_note or "ran",
    }
    os.makedirs(os.path.dirname(full_out), exist_ok=True)
    with open(full_out, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)
        fh.write("\n")
    ran = [c["name"] for c in checks if c["status"] != "not-run"]
    summary = (f"{repo}: all checks passed ({', '.join(ran)})" if not failed
               else f"{repo}: failed {', '.join(failed)}")
    if test_changes:
        summary += f"; {len(test_changes)} existing test file(s) changed — reviewer must justify"
    changed = [f"{c['path']} ({c['status']})" for c in test_changes]
    print(json.dumps({
        "passed": not failed,
        "failed_checks": ",".join(failed),
        "tests_changed": ", ".join(changed[:20]) + (" …" if len(changed) > 20 else ""),
        "receipt_path": os.path.relpath(full_out, root),
        "receipt_sha256": statemod.sha256_file(full_out),
        "commit": commit,
        "summary": summary,
    }))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--base-repo", help="main checkout the branch started from (test-edit guard)")
    args = parser.parse_args(argv)
    if os.environ.get("MAESTRO_SIMULATION") == "1":
        print(json.dumps({"passed": True, "failed_checks": "", "tests_changed": "",
                          "receipt_path": args.out,
                          "receipt_sha256": "", "commit": "[simulated commit]",
                          "summary": f"{args.repo}: [simulated] checks passed"}))
        return 0
    return run_checks(args.root, args.repo, args.worktree, args.out, args.base_repo)


if __name__ == "__main__":
    sys.exit(main())
