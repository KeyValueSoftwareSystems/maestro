#!/usr/bin/env python3
"""Run a repository's configured checks in its worktree and write a verification receipt.

The engine — not an agent — decides whether an implementation builds and passes its tests.
Commands come only from maestro.config.yaml (`project_config`), run in this order when
configured: setup, build, typecheck, lint, test, security (the project's own scanner, e.g.
semgrep, npm audit, gosec). A setup or build failure stops the run:
later checks would only repeat it. `build` and `test` are required; a missing one fails closed
with exit 2 ("not configured") instead of passing silently.

The receipt records the reviewed commit and, per check, the exact command, exit code,
duration and a hash of its log, so "tests passed" is a checkable record, not a claim.
Commands run with CI=true so watch-mode test runners exit.

Secret scan: with --base-repo the engine also scans the lines the branch ADDED for committed
credentials (cloud keys, private keys, provider tokens). A hit fails verification as the
`secrets` check; the receipt records the file, line and rule — never the value. Placeholder values
containing EXAMPLE are ignored.

Test-edit guard: with --base-repo, the receipt also lists EXISTING test files the branch
modified, renamed or deleted (repo `test_patterns`, or defaults). They are flagged for the
reviewer to justify, never auto-failed — agents can make tests pass by weakening them.

Baseline: with --base-repo, a check that fails is run once more on the commit the branch started
from, in an engine-owned checkout under .maestro/baseline/<repo>/ (setup first, when configured).
If it fails there too, the failure is `pre-existing` — the feature did not cause it — and does not
fail verification; the receipt records the base commit and its log, and the summary names it.
Results are cached per base commit and command, so a slow baseline runs once.

Usage: repo_checks.py --root . --repo backend --worktree <path> --out <receipt.json>
                      [--base-repo <main checkout>]
Last stdout line: {"passed", "failed_checks", "pre_existing_csv", "tests_changed", "receipt_path",
                   "receipt_sha256", "commit", "summary"}
Exit: 0 when the checks ran (pass or fail; route on `passed`), 2 when they cannot run.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_config  # noqa: E402
import state as statemod  # noqa: E402

ORDER = ("setup", "build", "typecheck", "lint", "test", "security")
SECRET_RULES = (
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("stripe-live-key", re.compile(r"\b(?:sk|rk)_live_[0-9A-Za-z]{24,}\b")),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b")),
)
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
    base = _branch_base(worktree, base_repo)
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


def _branch_base(worktree, base_repo):
    base_head = subprocess.run(["git", "-C", base_repo, "rev-parse", "HEAD"],
                               capture_output=True, text=True).stdout.strip()
    if not base_head:
        return ""
    return subprocess.run(["git", "-C", worktree, "merge-base", "HEAD", base_head],
                          capture_output=True, text=True).stdout.strip()


def _secret_scan(worktree, base_repo):
    """Credentials in lines the branch added. -> (findings, note); note says why it could not run."""
    if not base_repo:
        return [], "no base repository given"
    base = _branch_base(worktree, base_repo)
    if not base:
        return [], "cannot find the commit this branch started from"
    proc = subprocess.run(["git", "-C", worktree, "diff", "--unified=0", "--no-color", base],
                          capture_output=True, text=True, errors="replace")
    if proc.returncode:
        return [], "git diff failed"
    findings, path, line_no = [], None, 0
    for line in proc.stdout.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            line_no = int(match.group(1)) if match else 0
        elif line.startswith("+") and path:
            for rule, pattern in SECRET_RULES:
                hit = pattern.search(line)
                if hit and "EXAMPLE" not in hit.group(0).upper():
                    findings.append({"path": path, "line": line_no, "rule": rule})
            line_no += 1
    return findings, None


def _run(command, cwd, timeout, log_path, extra_env=None):
    env = os.environ.copy()
    env.setdefault("CI", "true")
    env.update(extra_env or {})
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


def _baseline_dir(root, repo):
    folder = os.path.join(root, ".maestro", "baseline", repo)
    os.makedirs(folder, exist_ok=True)
    ignore = os.path.join(root, ".maestro", "baseline", ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w", encoding="utf-8") as fh:
            fh.write("# engine-owned base-commit checkouts and results; never committed\n*\n")
    return folder


def _baseline_checkout(root, repo, base_repo, commit):
    """A detached checkout of `commit`, reused across runs; older ones for the repo are removed."""
    folder = _baseline_dir(root, repo)
    path = os.path.join(folder, commit[:12])
    if os.path.isdir(path) and _git_head(path) == commit:
        return path, False
    for name in os.listdir(folder):
        stale = os.path.join(folder, name)
        if os.path.isdir(stale):
            subprocess.run(["git", "-C", base_repo, "worktree", "remove", "--force", stale],
                           capture_output=True, text=True)
            shutil.rmtree(stale, ignore_errors=True)
    subprocess.run(["git", "-C", base_repo, "worktree", "prune"], capture_output=True, text=True)
    proc = subprocess.run(["git", "-C", base_repo, "worktree", "add", "--detach", path, commit],
                          capture_output=True, text=True)
    return (path, True) if proc.returncode == 0 else (None, False)


def _baseline_result(root, repo, base_repo, base, name, commands, timeout):
    """How check `name` fares on the base commit: cached {status, exit_code, log}, or None."""
    folder = _baseline_dir(root, repo)
    cache_path = os.path.join(folder, f"results-{base[:12]}.json")
    try:
        with open(cache_path, encoding="utf-8") as fh:
            cache = json.load(fh)
    except (OSError, ValueError):
        cache = {}
    key = hashlib.sha256(commands[name].encode("utf-8")).hexdigest()[:16]
    cached = (cache.get(name) or {})
    if cached.get("command_sha") == key:
        return cached
    checkout, fresh = _baseline_checkout(root, repo, base_repo, base)
    if checkout is None:
        return None
    log_dir = os.path.join(folder, f"logs-{base[:12]}")
    if "setup" in commands and name != "setup" and (fresh or "setup" not in cache):
        setup = _run(commands["setup"], checkout, timeout, os.path.join(log_dir, "setup.log"))
        cache["setup"] = {"command_sha": hashlib.sha256(commands["setup"].encode("utf-8"))
                          .hexdigest()[:16], "status": setup["status"],
                          "exit_code": setup["exit_code"]}
    result = _run(commands[name], checkout, timeout, os.path.join(log_dir, f"{name}.log"))
    cache[name] = {"command_sha": key, "status": result["status"],
                   "exit_code": result["exit_code"],
                   "log": os.path.relpath(os.path.join(log_dir, f"{name}.log"), root)}
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2)
        fh.write("\n")
    return cache[name]


def run_checks(root, repo, worktree, out, base_repo=None):
    # Absolute from here on: the baseline checkout is made with `git -C <base repo>`, which would
    # resolve a relative path inside that repository instead of under the workspace.
    root = os.path.abspath(root)
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
    full_base = None
    if base_repo:
        full_base = base_repo if os.path.isabs(base_repo) else os.path.join(root, base_repo)
    base = _branch_base(full_worktree, full_base) if full_base else ""
    checks, stopped_by = [], None
    for name in ORDER:
        if name not in commands:
            continue
        if stopped_by:
            checks.append({"name": name, "command": commands[name], "status": "not-run"})
            continue
        result = _run(commands[name], full_worktree, timeout, os.path.join(log_dir, f"{name}.log"))
        check = {
            "name": name,
            "command": commands[name],
            "log": os.path.relpath(os.path.join(log_dir, f"{name}.log"), root),
            **result,
        }
        if result["status"] != "passed" and base and base != commit:
            before = _baseline_result(root, repo, full_base, base, name, commands, timeout)
            if before and before["status"] != "passed":
                check["status"] = "pre-existing"
                check["baseline"] = {"commit": base, "exit_code": before["exit_code"],
                                     "log": before.get("log")}
        checks.append(check)
        if check["status"] not in ("passed", "pre-existing") and name in STOP_ON_FAILURE:
            stopped_by = name

    secrets, secret_note = _secret_scan(full_worktree, full_base)
    if secrets:
        checks.append({"name": "secrets", "command": "engine secret scan of added lines",
                       "status": "failed", "findings": secrets})
    failed = [c["name"] for c in checks if c["status"] not in ("passed", "pre-existing")]
    pre_existing = [c["name"] for c in checks if c["status"] == "pre-existing"]
    test_changes, guard_note = _test_changes(
        full_worktree, full_base, project_config.repo_test_patterns(config, repo))
    receipt = {
        "schema_version": 1,
        "repo": repo,
        "worktree": worktree,
        "commit": commit,
        "verified_at": statemod.now_iso(),
        "passed": not failed,
        "pre_existing": pre_existing,
        "skipped": [name for name in ORDER if name not in commands],
        "checks": checks,
        "test_changes": test_changes,
        "test_guard": guard_note or "ran",
        "secret_scan": secret_note or "ran",
    }
    os.makedirs(os.path.dirname(full_out), exist_ok=True)
    with open(full_out, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)
        fh.write("\n")
    ran = [c["name"] for c in checks if c["status"] not in ("not-run", "pre-existing")]
    summary = (f"{repo}: all checks passed ({', '.join(ran)})" if not failed
               else f"{repo}: failed {', '.join(failed)}")
    if pre_existing:
        summary += (f"; pre-existing failures, also failing on base {base[:12]}: "
                    f"{', '.join(pre_existing)}")
    if secrets:
        summary += "; committed secret(s): " + ", ".join(
            f"{f['path']}:{f['line']} ({f['rule']})" for f in secrets[:5])
    if test_changes:
        summary += f"; {len(test_changes)} existing test file(s) changed — reviewer must justify"
    changed = [f"{c['path']} ({c['status']})" for c in test_changes]
    print(json.dumps({
        "passed": not failed,
        "failed_checks": ",".join(failed),
        "pre_existing_csv": ",".join(pre_existing),
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
        print(json.dumps({"passed": True, "failed_checks": "", "pre_existing_csv": "",
                          "tests_changed": "",
                          "receipt_path": args.out,
                          "receipt_sha256": "", "commit": "[simulated commit]",
                          "summary": f"{args.repo}: [simulated] checks passed"}))
        return 0
    return run_checks(args.root, args.repo, args.worktree, args.out, args.base_repo)


if __name__ == "__main__":
    sys.exit(main())
