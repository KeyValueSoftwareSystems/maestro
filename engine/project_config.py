#!/usr/bin/env python3
"""Per-project configuration: maestro.config.yaml at the workspace root.

The one place a client project records how it is built, tested and delivered, so engine
steps (verify, QA environment, delivery) run the project's real commands instead of an
agent's guess. `maestro init` writes it; humans may edit it. The golden workflow never
changes per client — it reads these values.

    version: 1
    repos:
      backend:                       # a repo name as Maestro discovers it
        stack: go
        commands: {build: make build, lint: golangci-lint run, test: go test ./...}
        timeout_s: 900
    environment: {start: docker compose up -d, stop: docker compose down}
    delivery: {mode: branch, base: main}

`preflight` checks the file against the repos on disk. Unknown TOP-LEVEL keys are allowed
(workflows may read their own values through `${config.<path>}`); unknown keys inside the
sections above are typos and fail.

Usage: project_config.py preflight [--root .]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402
import wf  # noqa: E402
from validate import Issue  # noqa: E402

CONFIG_FILE = "maestro.config.yaml"
CONFIG_VERSION = 1
COMMANDS = ("setup", "build", "lint", "typecheck", "test", "security", "e2e")
REQUIRED_COMMANDS = ("build", "test")
RECOMMENDED_COMMANDS = ("lint", "security", "e2e")
REPO_KEYS = {"stack", "role", "commands", "timeout_s", "test_patterns"}
REPO_ROLES = ("app", "infra")
INFRASTRUCTURE_LEVELS = ("none", "containers", "iac")
# Paths that count as test files for the test-edit guard (fnmatch; `*` crosses `/`).
DEFAULT_TEST_PATTERNS = (
    "test/*", "tests/*", "*/test/*", "*/tests/*", "__tests__/*", "*/__tests__/*",
    "spec/*", "*/spec/*", "*_test.*", "test_*.py", "*/test_*.py", "*.test.*", "*.spec.*",
    "*Test.java", "*Tests.java", "*Test.kt", "*Tests.kt", "*_spec.rb",
)
ENVIRONMENT_KEYS = {"start", "ready", "stop"}
DELIVERY_KEYS = {"mode", "base", "remote"}
DELIVERY_MODES = ("branch", "pull-request")
DEFAULT_TIMEOUT_S = 900


class ConfigError(ValueError):
    pass


def config_path(root="."):
    return os.path.join(root, CONFIG_FILE)


def load(root="."):
    """The parsed config, or None when the file is absent. Raises ConfigError when unparseable."""
    path = config_path(root)
    if not os.path.exists(path):
        return None
    try:
        data = wf.load_file(path)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{CONFIG_FILE} cannot be read: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{CONFIG_FILE} must be a mapping of settings")
    return data


def repo_commands(config, repo):
    """{command: shell string} for one repo; empty commands are treated as not configured."""
    entry = ((config or {}).get("repos") or {}).get(repo) or {}
    commands = entry.get("commands") or {}
    return {name: str(cmd).strip() for name, cmd in commands.items() if str(cmd or "").strip()}


def repo_timeout(config, repo):
    entry = ((config or {}).get("repos") or {}).get(repo) or {}
    return entry.get("timeout_s") or DEFAULT_TIMEOUT_S


def repo_test_patterns(config, repo):
    entry = ((config or {}).get("repos") or {}).get(repo) or {}
    return tuple(entry.get("test_patterns") or DEFAULT_TEST_PATTERNS)


def _check_strings(section, value, keys, where, issues):
    if not isinstance(value, dict):
        issues.append(Issue("error", "config-shape", f"`{section}` must be a mapping", where))
        return
    for key, item in value.items():
        if key not in keys:
            issues.append(Issue("error", "config-unknown-key",
                                f"unknown key `{key}` (allowed: {', '.join(sorted(keys))})",
                                f"{where}.{key}"))
        elif item is not None and not isinstance(item, str):
            issues.append(Issue("error", "config-shape", "must be a string", f"{where}.{key}"))


def check(config, discovered):
    """Validate a loaded config against discovered repo names. -> [Issue]"""
    issues = []
    if config.get("version") != CONFIG_VERSION:
        issues.append(Issue("error", "config-version",
                            f"`version` must be {CONFIG_VERSION}, got {config.get('version')!r}"))
    repos = config.get("repos")
    if repos is None:
        repos = {}
    if not isinstance(repos, dict):
        issues.append(Issue("error", "config-shape", "`repos` must be a mapping of repo names"))
        repos = {}
    for name in discovered:
        if name not in repos:
            issues.append(Issue("error", "config-missing-repo",
                                f"repo `{name}` has no entry under `repos`", f"repos.{name}"))
    for name, entry in repos.items():
        where = f"repos.{name}"
        if name not in discovered:
            issues.append(Issue("warning", "config-unknown-repo",
                                f"repo `{name}` is not in this workspace", where))
        if not isinstance(entry, dict):
            issues.append(Issue("error", "config-shape", "repo entry must be a mapping", where))
            continue
        for key in entry:
            if key not in REPO_KEYS:
                issues.append(Issue("error", "config-unknown-key",
                                    f"unknown key `{key}` (allowed: {', '.join(sorted(REPO_KEYS))})",
                                    f"{where}.{key}"))
        timeout = entry.get("timeout_s")
        if timeout is not None and (not isinstance(timeout, int) or isinstance(timeout, bool)
                                    or timeout <= 0):
            issues.append(Issue("error", "config-shape", "must be a positive whole number of seconds",
                                f"{where}.timeout_s"))
        if entry.get("role") is not None and entry.get("role") not in REPO_ROLES:
            issues.append(Issue("error", "config-shape", f"must be one of: {', '.join(REPO_ROLES)}",
                                f"{where}.role"))
        patterns = entry.get("test_patterns")
        if patterns is not None and (not isinstance(patterns, list) or not patterns
                                     or not all(isinstance(p, str) and p for p in patterns)):
            issues.append(Issue("error", "config-shape", "must be a non-empty list of path patterns",
                                f"{where}.test_patterns"))
        commands = entry.get("commands") or {}
        if not isinstance(commands, dict):
            issues.append(Issue("error", "config-shape", "`commands` must be a mapping",
                                f"{where}.commands"))
            continue
        _check_strings("commands", commands, set(COMMANDS), f"{where}.commands", issues)
        configured = repo_commands(config, name)
        for command in REQUIRED_COMMANDS:
            if command not in configured:
                issues.append(Issue("error", "config-missing-command",
                                    f"no `{command}` command; Maestro cannot verify this repo",
                                    f"{where}.commands.{command}"))
        for command in RECOMMENDED_COMMANDS:
            if command not in configured:
                issues.append(Issue("warning", "config-missing-command",
                                    f"no `{command}` command; that check will be skipped",
                                    f"{where}.commands.{command}"))
    if "environment" in config:
        _check_strings("environment", config["environment"], ENVIRONMENT_KEYS, "environment", issues)
    if "infrastructure" in config:
        infrastructure = config["infrastructure"]
        _check_strings("infrastructure", infrastructure, {"level"}, "infrastructure", issues)
        if isinstance(infrastructure, dict) and infrastructure.get("level") not in (
                None, *INFRASTRUCTURE_LEVELS):
            issues.append(Issue("error", "config-shape",
                                f"must be one of: {', '.join(INFRASTRUCTURE_LEVELS)}",
                                "infrastructure.level"))
    if "reviews" in config:
        reviews = config["reviews"]
        if not isinstance(reviews, dict):
            issues.append(Issue("error", "config-shape", "`reviews` must be a mapping", "reviews"))
        else:
            for key, value in reviews.items():
                if key != "max_rounds":
                    issues.append(Issue("error", "config-unknown-key",
                                        f"unknown key `{key}` (allowed: max_rounds)",
                                        f"reviews.{key}"))
                elif not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                    issues.append(Issue("error", "config-shape",
                                        "must be a positive whole number of review rounds",
                                        "reviews.max_rounds"))
    if "delivery" in config:
        delivery = config["delivery"]
        _check_strings("delivery", delivery, DELIVERY_KEYS, "delivery", issues)
        if isinstance(delivery, dict) and delivery.get("mode") not in (None, *DELIVERY_MODES):
            issues.append(Issue("error", "config-shape",
                                f"must be one of: {', '.join(DELIVERY_MODES)}", "delivery.mode"))
    return issues


def preflight(root="."):
    """Check that this workspace is ready for a Maestro run. -> [Issue]"""
    try:
        config = load(root)
    except ConfigError as exc:
        return [Issue("error", "config-unreadable", str(exc))]
    if config is None:
        return [Issue("error", "config-missing",
                      f"{CONFIG_FILE} not found at the workspace root; run maestro init or "
                      f"create it (see docs/project-config.md)")]
    discovered = [name for name, _path in codebase_scan.discover_repos(root)]
    return check(config, discovered)


def summary(issues):
    errors = [i for i in issues if i.level == "error"]
    return {
        "ok": not errors,
        "errors": len(errors),
        "warnings": len(issues) - len(errors),
        "issues": [{"level": i.level, "code": i.code, "message": i.msg, "where": i.where}
                   for i in issues],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["preflight"])
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    issues = preflight(args.root)
    for issue in issues:
        print(str(issue), file=sys.stderr)
    result = summary(issues)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
