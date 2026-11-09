#!/usr/bin/env python3
"""Parse optional template `registry.yaml` at the umbrella root (stdlib only).

When present, registry is the source of truth for remotes and default/index
branches. Discovery still scans `codebase/` for git repos; this module validates
alignment and supplies branch hints for sync/index.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import codebase_scan

DEFAULT_REGISTRY = "registry.yaml"


def _strip_comment(line):
    in_single = in_double = False
    out = []
    for ch in line:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load(root=".", path=DEFAULT_REGISTRY):
    """Load registry.yaml → dict or None if missing.

    Shape: {"default_branch": str|None, "repos": [{"name","remote","branch"|None,
    "worktree_include": [str, ...]}, ...]}
    """
    root = os.path.abspath(root)
    abs_path = path if os.path.isabs(path) else os.path.join(root, path)
    if not os.path.isfile(abs_path):
        return None
    default_branch = None
    repos = []
    current = None
    in_includes = False
    with open(abs_path, encoding="utf-8") as fh:
        for raw in fh:
            line = _strip_comment(raw)
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            stripped = line.strip()
            if indent == 0 and stripped.startswith("default_branch:"):
                default_branch = _scalar(stripped.split(":", 1)[1]) or None
                in_includes = False
                continue
            if indent == 0 and stripped in ("repos:", "repos: []"):
                in_includes = False
                continue
            if stripped.startswith("- name:"):
                if current and current.get("name"):
                    repos.append(current)
                current = {
                    "name": _scalar(stripped.split(":", 1)[1]),
                    "remote": "",
                    "branch": None,
                    "worktree_include": [],
                }
                in_includes = False
                continue
            if current is None:
                continue
            if stripped.startswith("remote:"):
                current["remote"] = _scalar(stripped.split(":", 1)[1])
                in_includes = False
            elif stripped.startswith("branch:"):
                current["branch"] = _scalar(stripped.split(":", 1)[1]) or None
                in_includes = False
            elif stripped.startswith("worktree_include:"):
                rest = stripped.split(":", 1)[1].strip()
                in_includes = True
                if rest.startswith("[") and rest.endswith("]"):
                    inner = rest[1:-1].strip()
                    if inner:
                        current["worktree_include"] = [
                            _scalar(p) for p in inner.split(",") if p.strip()
                        ]
                    in_includes = False
            elif in_includes and stripped.startswith("- "):
                current["worktree_include"].append(_scalar(stripped[2:]))
            elif indent <= 2 and not stripped.startswith("-"):
                in_includes = False
    if current and current.get("name"):
        repos.append(current)
    return {"default_branch": default_branch, "repos": repos, "path": abs_path}


def effective_branch(registry, name, fallback="main"):
    if not registry:
        return fallback
    for entry in registry.get("repos") or []:
        if entry.get("name") == name:
            return entry.get("branch") or registry.get("default_branch") or fallback
    return registry.get("default_branch") or fallback


def validate(root=".", registry_path=DEFAULT_REGISTRY, strict=False):
    """Compare registry.yaml to discovered codebase/ repos.

    Returns {"ok": bool, "warnings": [...], "errors": [...], "registered": [...],
    "discovered": [...], "missing_clones": [...], "unregistered": [...]}
    """
    root = os.path.abspath(root)
    reg = load(root, registry_path)
    discovered = codebase_scan.discover_repos(root)
    discovered_names = [name for name, _ in discovered]
    warnings = []
    errors = []
    if reg is None:
        return {
            "ok": True,
            "warnings": [],
            "errors": [],
            "registered": [],
            "discovered": discovered_names,
            "missing_clones": [],
            "unregistered": [],
            "present": False,
        }
    registered = [e["name"] for e in reg.get("repos") or [] if e.get("name")]
    missing = [n for n in registered if n not in discovered_names]
    unregistered = [n for n in discovered_names if n not in registered]
    for name in missing:
        msg = f"registry lists {name} but codebase/{name} is not a git clone"
        (errors if strict else warnings).append(msg)
    for name in unregistered:
        msg = f"codebase/{name} is a git repo but not in registry.yaml"
        warnings.append(msg)
    return {
        "ok": not errors,
        "warnings": warnings,
        "errors": errors,
        "registered": registered,
        "discovered": discovered_names,
        "missing_clones": missing,
        "unregistered": unregistered,
        "present": True,
        "default_branch": reg.get("default_branch"),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate")
    p.add_argument("--root", default=".")
    p.add_argument("--registry", default=DEFAULT_REGISTRY)
    p.add_argument("--strict", action="store_true")
    p = sub.add_parser("show")
    p.add_argument("--root", default=".")
    p.add_argument("--registry", default=DEFAULT_REGISTRY)
    args = parser.parse_args(argv)
    if args.cmd == "show":
        doc = load(args.root, args.registry)
        print(json.dumps(doc, indent=2))
        return 0 if doc is not None else 1
    result = validate(args.root, args.registry, strict=args.strict)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
