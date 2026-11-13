#!/usr/bin/env python3
"""The greenfield path: a feature in a workspace that has no code yet.

  greenfield.py check     [--root .]
      {greenfield, repo_count} — greenfield when no repository is discovered.
  greenfield.py create    [--root .] --hld <hld.md> [--plan <plan.json>]
      creates `codebase/<name>` for every repository the approved HLD's Repositories section lists
      (`name` (stack): purpose): git init and an empty first commit; existing ones are left alone.
      {repos_csv, created_csv, plan_path}
  greenfield.py configure [--root .] --scaffold <scaffold.json>
      the scaffolding agent's report {"repos": {name: {"stack", "commands": {build, test, ...}}}}:
      adds each repository's entry to maestro.config.yaml (an existing entry is never changed; the
      previous file is kept as maestro.config.yaml.bak), then runs each new repository's build and
      test once to prove the skeleton works, then stamps each codebase map
      (docs/codebase-maps/<name>.md) with its repository's commit. The scaffold stage then records the knowledge's provenance and pins the
      commits with workspace_sync.py.
      {valid, failed_csv, summary} — exits 0; the workflow routes on `valid`.

The engine owns these steps so a swapped scaffolding skill cannot leave a repository unbuildable or
missing from the configuration.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402
import project_config  # noqa: E402
import repo_checks  # noqa: E402
import validate_hld  # noqa: E402
import wf  # noqa: E402


def _out(obj):
    print(json.dumps(obj))
    return 0


def cmd_check(args):
    repos = codebase_scan.discover_repos(args.root)
    return _out({"greenfield": not repos, "repo_count": len(repos)})


def cmd_create(args):
    try:
        with open(args.hld, encoding="utf-8") as fh:
            sections, _order = validate_hld._sections(fh.read())
    except OSError as exc:
        print(f"cannot read the HLD: {exc}", file=sys.stderr)
        return 1
    planned = validate_hld.new_repositories(sections)
    if not planned:
        print("the HLD lists no repositories to create", file=sys.stderr)
        return 1
    created = []
    for name, _stack in planned:
        path = os.path.join(args.root, "codebase", name)
        if os.path.isdir(os.path.join(path, ".git")):
            continue
        os.makedirs(path, exist_ok=True)
        subprocess.run(["git", "init", "-q", path], check=True)
        subprocess.run(["git", "-C", path, "commit", "-q", "--allow-empty", "-m",
                        "Initial commit (Maestro greenfield)"], check=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": os.environ.get("GIT_AUTHOR_NAME", "Maestro"),
                            "GIT_AUTHOR_EMAIL": os.environ.get("GIT_AUTHOR_EMAIL", "maestro@localhost"),
                            "GIT_COMMITTER_NAME": os.environ.get("GIT_COMMITTER_NAME", "Maestro"),
                            "GIT_COMMITTER_EMAIL": os.environ.get("GIT_COMMITTER_EMAIL",
                                                                  "maestro@localhost")})
        created.append(name)
    # the repositories planned: --plan, else greenfield-plan.json beside the HLD
    plan = args.plan or os.path.join(os.path.dirname(args.hld), "greenfield-plan.json")
    os.makedirs(os.path.dirname(os.path.abspath(plan)), exist_ok=True)
    with open(plan, "w", encoding="utf-8") as fh:
        json.dump({"repos": [{"name": n, "stack": s} for n, s in planned]}, fh, indent=2)
    return _out({"repos_csv": ",".join(n for n, _s in planned), "created_csv": ",".join(created),
                 "plan_path": os.path.relpath(plan, args.root)})


def _merge_config(root, scaffold):
    path = project_config.config_path(root)
    config = project_config.load(root) or {"version": project_config.CONFIG_VERSION}
    repos = config.get("repos") if isinstance(config.get("repos"), dict) else {}
    added = []
    for name, spec in scaffold.items():
        if name in repos:
            continue
        entry = {}
        if spec.get("stack"):
            entry["stack"] = spec["stack"]
        entry["commands"] = {k: v for k, v in (spec.get("commands") or {}).items()
                             if k in project_config.COMMANDS and isinstance(v, str) and v.strip()}
        repos[name] = entry
        added.append(name)
    if added:
        if os.path.exists(path):
            shutil.copyfile(path, path + ".bak")
        config["repos"] = repos
        wf.dump_file(path, config)
    return added


def _record_map(root, name, repo):
    """Stamp the scaffold's codebase map (docs/codebase-maps/<name>.md in the workspace) with the
    repository commit it describes, so the workspace check finds the map current."""
    path = codebase_scan.map_path(root, name)
    if os.path.isfile(path):
        codebase_scan.write_marker(path, codebase_scan._head(repo))


def cmd_configure(args):
    try:
        with open(args.scaffold, encoding="utf-8") as fh:
            scaffold = (json.load(fh) or {}).get("repos") or {}
    except (OSError, ValueError) as exc:
        return _out({"valid": False, "failed_csv": "",
                     "summary": f"scaffold report unreadable: {exc}"})
    discovered = dict(codebase_scan.discover_repos(args.root))
    problems, failed = [], []
    missing = [name for name in scaffold if name not in discovered]
    if missing:
        problems.append(f"not a repository in the workspace: {', '.join(missing)}")
    for name, spec in scaffold.items():
        commands = (spec or {}).get("commands") or {}
        for required in project_config.REQUIRED_COMMANDS:
            if not str(commands.get(required) or "").strip():
                problems.append(f"{name}: no {required} command")
    if problems:
        return _out({"valid": False, "failed_csv": ",".join(missing),
                     "summary": "; ".join(problems)})
    added = _merge_config(args.root, scaffold)
    config = project_config.load(args.root) or {}
    for name in scaffold:
        path = discovered[name]
        commands = project_config.repo_commands(config, name)
        log_dir = os.path.join(os.path.dirname(args.scaffold), "scaffold-logs", name)
        for check in ("build", "test"):
            result = repo_checks._run(commands[check], path, project_config.repo_timeout(config, name),
                                      os.path.join(log_dir, f"{check}.log"))
            if result["status"] != "passed":
                failed.append(name)
                problems.append(f"{name}: {check} failed (exit {result['exit_code']}): "
                                f"{result['tail'][-300:].strip()}")
                break
    if failed:
        return _out({"valid": False, "failed_csv": ",".join(failed), "summary": "; ".join(problems)})
    for name in scaffold:
        _record_map(args.root, name, discovered[name])
    return _out({"valid": True, "failed_csv": "", "added_csv": ",".join(added),
                 "summary": f"{len(scaffold)} repositories scaffolded; build and test pass"})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check")
    p.add_argument("--root", default=".")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("create")
    p.add_argument("--root", default=".")
    p.add_argument("--hld", required=True)
    p.add_argument("--plan", help="where to write the planned repositories")
    p.set_defaults(fn=cmd_create)
    p = sub.add_parser("configure")
    p.add_argument("--root", default=".")
    p.add_argument("--scaffold", required=True)
    p.set_defaults(fn=cmd_configure)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
