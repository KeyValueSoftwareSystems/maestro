#!/usr/bin/env python3
"""The QA environment and the project's own E2E suites, run by the engine from maestro.config.yaml.

  qa_env.py plan [--root .]                   whether the workspace has an E2E suite: any repo
                                              with an `e2e` command (has_e2e, e2e_repos_csv)
  qa_env.py up   [--root .] --manifest M      environment.start, then environment.ready
  qa_env.py e2e  [--root .] --manifest M --out R
                 each manifest repository's `e2e` command, in its verified worktree
  qa_env.py down [--root .] --manifest M      environment.stop (never fails the run)

Every command gets the exact code under test as environment variables, so a start command can
build the stack from the verified worktrees instead of the main checkouts:
  MAESTRO_SLUG, MAESTRO_MANIFEST, and per repository MAESTRO_WORKTREE_<REPO> and
  MAESTRO_COMMIT_<REPO> (<REPO> upper-cased, non-alphanumerics as `_`).

QA writes and runs an E2E suite only when `plan` reports has_e2e, in that repository's framework;
otherwise it checks the test cases directly against the running system and adds no framework.
Nothing configured is not a failure: `up`/`down` report `configured: false`, and `e2e` passes
with a summary saying no suite is configured, so QA results stay agent-reported for that repo.
`up` exits 1 when start or ready fails (QA cannot run against a stack that is not up). `e2e`
writes a receipt like the verify step's and exits 0; route on `passed`.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_config  # noqa: E402
import repo_checks  # noqa: E402
import state as statemod  # noqa: E402


def _simulated():
    return os.environ.get("MAESTRO_SIMULATION") == "1"


def _manifest(root, path):
    full = path if os.path.isabs(path) else os.path.join(root, path)
    with open(full, encoding="utf-8") as fh:
        return json.load(fh)


def _env_name(repo):
    return re.sub(r"[^A-Za-z0-9]", "_", repo).upper()


def code_under_test_env(manifest, manifest_path):
    env = {"MAESTRO_SLUG": str(manifest.get("feature_slug") or ""),
           "MAESTRO_MANIFEST": manifest_path}
    for entry in manifest.get("repositories") or []:
        name = _env_name(entry.get("repo", ""))
        env[f"MAESTRO_WORKTREE_{name}"] = str(entry.get("worktree") or "")
        env[f"MAESTRO_COMMIT_{name}"] = str(entry.get("commit") or "")
    return env


def _run(command, cwd, timeout, log_path, extra_env):
    return repo_checks._run(command, cwd, timeout, log_path, extra_env)


def _environment(root):
    config = project_config.load(root) or {}
    return config, config.get("environment") or {}, project_config.DEFAULT_TIMEOUT_S


def _log_dir(root, manifest_path):
    full = manifest_path if os.path.isabs(manifest_path) else os.path.join(root, manifest_path)
    return os.path.join(os.path.dirname(full), "qa", "environment")


def cmd_up(args):
    if _simulated():
        print(json.dumps({"configured": False, "started": True,
                          "summary": "[simulated] QA environment not started"}))
        return 0
    _config, environment, timeout = _environment(args.root)
    manifest = _manifest(args.root, args.manifest)
    env = code_under_test_env(manifest, args.manifest)
    if not environment.get("start"):
        print(json.dumps({"configured": False, "started": False,
                          "summary": "No QA environment configured (environment.start); QA uses "
                                     "whatever its suite starts itself"}))
        return 0
    log_dir = _log_dir(args.root, args.manifest)
    for name in ("start", "ready"):
        command = environment.get(name)
        if not command:
            continue
        result = _run(command, args.root, timeout, os.path.join(log_dir, f"{name}.log"), env)
        if result["status"] != "passed":
            print(f"QA environment {name} failed ({command}): {result['tail'][-800:]}",
                  file=sys.stderr)
            return 1
    summary = f"QA environment up ({environment['start']})"
    if not environment.get("ready"):
        summary += "; no ready check configured, so not confirmed healthy"
    print(json.dumps({"configured": True, "started": True, "summary": summary}))
    return 0


def cmd_down(args):
    if _simulated():
        print(json.dumps({"configured": False, "stopped": True, "summary": "[simulated]"}))
        return 0
    _config, environment, timeout = _environment(args.root)
    if not environment.get("stop"):
        print(json.dumps({"configured": False, "stopped": False,
                          "summary": "No environment.stop configured"}))
        return 0
    manifest = _manifest(args.root, args.manifest)
    result = _run(environment["stop"], args.root, timeout,
                  os.path.join(_log_dir(args.root, args.manifest), "stop.log"),
                  code_under_test_env(manifest, args.manifest))
    print(json.dumps({"configured": True, "stopped": result["status"] == "passed",
                      "summary": "QA environment stopped" if result["status"] == "passed"
                      else f"environment.stop failed (exit {result['exit_code']}); stop it by hand"}))
    return 0


def cmd_plan(args):
    if _simulated():
        print(json.dumps({"has_e2e": True, "e2e_repos_csv": "",
                          "summary": "[simulated] project E2E suite present"}))
        return 0
    config = project_config.load(args.root) or {}
    suites = []
    for repo, entry in sorted((config.get("repos") or {}).items()):
        command = project_config.repo_commands(config, repo).get("e2e")
        if command:
            record = entry.get("e2e") if isinstance(entry, dict) else None
            framework = record.get("framework") if isinstance(record, dict) else None
            suites.append((repo, f"{repo} ({framework + ': ' if framework else ''}{command})"))
    if suites:
        summary = ("Project E2E suite: " + "; ".join(text for _repo, text in suites)
                   + ". Write the suite in that framework")
    else:
        summary = ("No E2E suite in this workspace: check each test case directly against the "
                   "running system; add no framework and write no suite")
    print(json.dumps({"has_e2e": bool(suites), "e2e_repos_csv": ",".join(r for r, _t in suites),
                      "summary": summary}))
    return 0


def cmd_e2e(args):
    if _simulated():
        print(json.dumps({"passed": True, "failed_repos": "", "ran_csv": "",
                          "receipt_path": args.out, "summary": "[simulated] e2e suites passed"}))
        return 0
    config = project_config.load(args.root) or {}
    manifest = _manifest(args.root, args.manifest)
    env = code_under_test_env(manifest, args.manifest)
    full_out = args.out if os.path.isabs(args.out) else os.path.join(args.root, args.out)
    log_dir = os.path.splitext(full_out)[0] + "-logs"
    checks, unconfigured = [], []
    for entry in manifest.get("repositories") or []:
        repo = entry.get("repo", "")
        command = project_config.repo_commands(config, repo).get("e2e")
        if not command:
            unconfigured.append(repo)
            continue
        worktree = entry.get("worktree") or ""
        cwd = worktree if os.path.isabs(worktree) else os.path.join(args.root, worktree)
        log = os.path.join(log_dir, f"{repo}.log")
        result = _run(command, cwd, project_config.repo_timeout(config, repo), log, env)
        checks.append({"repo": repo, "commit": entry.get("commit"), "command": command,
                       "log": os.path.relpath(log, args.root), **result})
    failed = [c["repo"] for c in checks if c["status"] != "passed"]
    receipt = {"schema_version": 1, "ran_at": statemod.now_iso(), "passed": not failed,
               "checks": checks, "not_configured": unconfigured}
    os.makedirs(os.path.dirname(full_out), exist_ok=True)
    with open(full_out, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)
        fh.write("\n")
    if failed:
        summary = "Project e2e failed: " + ", ".join(failed)
    elif checks:
        summary = "Project e2e passed: " + ", ".join(c["repo"] for c in checks)
    else:
        summary = "No project e2e command configured; QA results are agent-reported"
    if checks and unconfigured:
        summary += f" (no e2e command: {', '.join(unconfigured)})"
    print(json.dumps({"passed": not failed, "failed_repos": ",".join(failed),
                      "ran_csv": ",".join(c["repo"] for c in checks),
                      "receipt_path": os.path.relpath(full_out, args.root), "summary": summary}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn in (("plan", cmd_plan), ("up", cmd_up), ("down", cmd_down), ("e2e", cmd_e2e)):
        p = sub.add_parser(name)
        p.add_argument("--root", default=".")
        p.add_argument("--manifest", required=name != "plan")
        if name == "e2e":
            p.add_argument("--out", required=True)
        p.set_defaults(fn=fn)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
