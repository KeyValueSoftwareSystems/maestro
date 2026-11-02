#!/usr/bin/env python3
"""Build the workspace for one evaluation case, ready for a Maestro run.

  eval_setup.py --case evals/cases/<case> --dest <empty dir>

A case folder holds `case.yaml` (the requirement, the repositories and their commands, the run
mode, and what a good run must achieve) and `workspace/<repo>/...` fixture files. This copies each
fixture repository to `<dest>/codebase/<repo>`, makes it a git repository with one commit, writes
`maestro.config.yaml` from the case, puts the requirement in
`.maestro/runs/<slug>/requirement/`, and records the case in `.maestro/eval-case.json`. Then
install Maestro into <dest> and start the run as printed. Score it with eval_score.py.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wf  # noqa: E402


def load_case(case_dir):
    case = wf.load_file(os.path.join(case_dir, "case.yaml"))
    for key in ("name", "slug", "requirement", "repos"):
        if not case.get(key):
            raise ValueError(f"{case_dir}/case.yaml: {key} is required")
    return case


def _git(cwd, *args):
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True)


def _yaml_scalar(value):
    return json.dumps(value)  # JSON strings are valid in the engine's YAML subset


def setup(case_dir, dest):
    case = load_case(case_dir)
    if os.path.exists(dest) and os.listdir(dest):
        raise ValueError(f"{dest} is not empty")
    os.makedirs(dest, exist_ok=True)
    lines = ["version: 1", "repos:"]
    for repo, spec in case["repos"].items():
        target = os.path.join(dest, "codebase", repo)
        fixture = os.path.join(case_dir, "workspace", repo)
        if os.path.isdir(fixture):
            shutil.copytree(fixture, target)
        else:
            os.makedirs(target)
        subprocess.run(["git", "init", "-q", target], check=True)
        _git(target, "config", "user.email", "eval@maestro.local")
        _git(target, "config", "user.name", "Maestro eval")
        _git(target, "add", "-A")
        _git(target, "commit", "-q", "--allow-empty", "-m", "Evaluation fixture")
        lines.append(f"  {repo}:")
        for key in ("stack", "role"):
            if spec.get(key):
                lines.append(f"    {key}: {_yaml_scalar(spec[key])}")
        commands = spec.get("commands") or {}
        if commands:
            lines.append("    commands:")
            lines.extend(f"      {name}: {_yaml_scalar(cmd)}" for name, cmd in commands.items())
    with open(os.path.join(dest, "maestro.config.yaml"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    requirement = os.path.join(dest, ".maestro", "runs", case["slug"], "requirement")
    os.makedirs(requirement)
    with open(os.path.join(requirement, case.get("requirement_file") or "brief.md"), "w",
              encoding="utf-8") as fh:
        fh.write(case["requirement"])
    record = {"case": case["name"], "case_dir": os.path.abspath(case_dir), "slug": case["slug"],
              "mode": case.get("mode", "auto"), "path": case.get("path", "auto")}
    with open(os.path.join(dest, ".maestro", "eval-case.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)
    return case, record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--case", required=True)
    parser.add_argument("--dest", required=True)
    args = parser.parse_args(argv)
    try:
        case, record = setup(args.case, args.dest)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"cannot set up the case: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({**record, "next": [
        f"install Maestro into {args.dest} (install.sh claude-code)",
        f"start the run: /maestro {case['slug']} — init --mode {record['mode']} "
        f"--input path={record['path']} --input feature=\"{case.get('feature', case['slug'])}\"",
        f"score it: python3 engine/eval_score.py score --root {args.dest} --case {args.case}",
    ]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
