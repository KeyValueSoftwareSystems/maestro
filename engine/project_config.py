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
    worktree:                        # optional: how each feature's worktrees are made
      create: ./scripts/sandbox create {slug} -y
      path: sandbox/{slug}/codebase/{repo}
      branch: sandbox/{slug}
      remove: ./scripts/sandbox rm {slug} -y

`preflight` checks the file against the repos on disk. Unknown TOP-LEVEL keys are allowed
(workflows may read their own values through `${config.<path>}`); unknown keys inside the
sections above are typos and fail.

Usage: project_config.py preflight [--root .]
       project_config.py init [--root .]     # create maestro.config.yaml if missing
       project_config.py apply --detected F  # fill stack and commands from detect-stack
       project_config.py sync [--dry-run]    # add entries for repos new to the workspace
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
WORKTREE_KEYS = {"create", "path", "branch", "remove"}
# Placeholders each worktree setting may use (worktrees.py fills them). `${VAR}` is shell, not ours.
WORKTREE_PLACEHOLDERS = {"create": {"slug", "root"}, "remove": {"slug", "root"},
                         "path": {"slug", "repo"}, "branch": {"slug", "repo"}}
DEFAULT_TIMEOUT_S = 900
# detect-stack vocabulary, used only to keep a stack string in a stable order.
STACK_ORDER = (
    "go", "java", "kotlin", "python", "react", "vue", "angular", "node", "rust",
    "flutter", "android", "db", "terraform", "kubernetes", "docker",
)


class ConfigError(ValueError):
    pass


def config_path(root="."):
    return os.path.join(root, CONFIG_FILE)


def repo_names(root="."):
    """Names for a new config. registry.yaml wins when Maestro is a template guest;
    otherwise the git repos discover_repos already found. No stack or command scan."""
    import registry as registry_mod
    registry = registry_mod.load(root)
    if registry and registry.get("repos"):
        return [entry["name"] for entry in registry["repos"] if entry.get("name")]
    return [name for name, _path in codebase_scan.discover_repos(root)]


def _stack_text(value):
    if isinstance(value, list):
        tokens = [str(item).strip() for item in value if str(item).strip()]
    else:
        tokens = [item.strip() for item in str(value or "").split(",") if item.strip()]
    ordered = [token for token in STACK_ORDER if token in tokens]
    return ", ".join(ordered + [token for token in tokens if token not in ordered])


def init(root="."):
    """Create maestro.config.yaml when it is absent. Never overwrites.

    Copies repository names from registry.yaml when that file exists. Stack and
    commands are left for the project-config skill (maestro-init only). -> 'wrote' or 'exists'."""
    path = config_path(root)
    if os.path.exists(path):
        return "exists"
    wf.dump_file(path, {"version": CONFIG_VERSION, "repos": {name: {} for name in repo_names(root)}})
    return "wrote"


def apply_detected(root, detected):
    """Merge a project-config report into maestro.config.yaml.

    `detected` is {"repos": {name: {"stack", "role", "commands"}}, "worktree": {...}?}. Missing
    file is created. Names come from registry.yaml when present, plus any name in the report.
    A stack, role, or command that is already set is left alone; `worktree` is added only when
    the file has none.
    -> {"created": bool, "updated": [repo names], "worktree_added": bool}
    """
    if not isinstance(detected, dict):
        raise ConfigError("detected stacks must be a mapping")
    reported = detected.get("repos") or {}
    if not isinstance(reported, dict):
        raise ConfigError("detected repos must be a mapping")
    path = config_path(root)
    created = not os.path.exists(path)
    config = load(root) or {"version": CONFIG_VERSION}
    if not isinstance(config, dict):
        raise ConfigError(f"{CONFIG_FILE} must be a mapping of settings")
    if config.get("version") is None:
        config["version"] = CONFIG_VERSION
    repos = config.get("repos") if isinstance(config.get("repos"), dict) else {}
    names = list(repo_names(root))
    for name in reported:
        if name not in names:
            names.append(name)
    updated = []
    for name in names:
        spec = reported.get(name) if isinstance(reported.get(name), dict) else {}
        entry = repos.get(name) if isinstance(repos.get(name), dict) else {}
        changed = name not in repos
        stack = _stack_text(spec.get("stack"))
        if stack and not entry.get("stack"):
            entry["stack"] = stack
            changed = True
        role = spec.get("role")
        if role in REPO_ROLES and not entry.get("role"):
            entry["role"] = role
            changed = True
        commands = dict(entry.get("commands") or {}) if isinstance(entry.get("commands"), dict) else {}
        incoming = spec.get("commands") or {}
        if isinstance(incoming, dict):
            for key, value in incoming.items():
                if key in COMMANDS and isinstance(value, str) and value.strip() and not str(
                        commands.get(key) or "").strip():
                    commands[key] = value.strip()
                    changed = True
        if commands:
            entry["commands"] = commands
        repos[name] = entry
        if changed:
            updated.append(name)
    config["repos"] = repos
    worktree = _detected_worktree(detected.get("worktree"))
    worktree_added = bool(worktree) and not config.get("worktree")
    if worktree_added:
        config["worktree"] = worktree
    if created or updated or worktree_added:
        wf.dump_file(path, config)
    return {"created": created, "updated": updated, "worktree_added": worktree_added}


def sync(root=".", dry_run=False):
    """Add maestro.config.yaml entries for repositories new to the workspace. Deterministic,
    no scan; only ever adds.

    Every repo on disk (discover_repos — what preflight checks) without an entry gets an empty
    one for the project-config skill to fill. registry.yaml, when present, only adds facts: a
    registered repo not cloned yet is reported, not added, and a clone the registry does not
    list is still added but reported. Existing entries are never touched. The edit is textual,
    so comments and layout survive.
    -> {"created", "added", "missing_clones", "unregistered", "needs_commands", "changed"}
    """
    import registry as registry_mod
    discovered = [name for name, _path in codebase_scan.discover_repos(root)]
    reg = registry_mod.load(root)
    registered = [e["name"] for e in (reg or {}).get("repos") or [] if e.get("name")]
    path = config_path(root)
    created = not os.path.exists(path)
    config = load(root) or {"version": CONFIG_VERSION}
    repos = config.get("repos") if isinstance(config.get("repos"), dict) else {}
    added = [name for name in discovered if name not in repos]
    needs_commands = [name for name in discovered if any(
        command not in repo_commands(config, name) for command in REQUIRED_COMMANDS)]
    changed = bool(created or added)
    if changed and not dry_run:
        _write_synced(path, config, added, created)
    return {
        "created": created,
        "added": added,
        "missing_clones": [name for name in registered if name not in discovered],
        "unregistered": [name for name in discovered if reg is not None and name not in registered],
        "needs_commands": needs_commands,
        "changed": changed,
        "dry_run": bool(dry_run),
    }


def _write_synced(path, config, added, created):
    """Append empty entries under `repos:` by editing lines, then reload to prove the result;
    anything the line edit cannot handle falls back to a full re-dump."""
    existing = dict(config.get("repos") or {})
    if not created:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        edited = _append_repos(text, added)
        if edited is not None:
            tmp = path + ".sync.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(edited)
            try:
                reloaded = wf.load_file(tmp)
                ok = (isinstance(reloaded, dict) and isinstance(reloaded.get("repos"), dict)
                      and sorted(reloaded["repos"]) == sorted([*existing, *added])
                      and all(reloaded["repos"][name] == spec for name, spec in existing.items()))
            except (OSError, ValueError):
                ok = False
            if ok:
                os.replace(tmp, path)
                return
            os.remove(tmp)
    for name in added:
        existing[name] = {}
    config["repos"] = existing
    wf.dump_file(path, config)


def _append_repos(text, added):
    """`text` with `added` appended to the block-style `repos:` map, or None when there is no
    block-style `repos:` to edit."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines)
                  if re.match(r"repos:\s*(#.*)?$", line.rstrip("\r\n"))), None)
    if start is None:
        return None

    def top_level(line):
        body = line.rstrip("\r\n")
        return bool(body) and not body[0].isspace() and not body.lstrip().startswith("#")

    end = next((i for i in range(start + 1, len(lines)) if top_level(lines[i])), len(lines))
    block = lines[start + 1:end]
    # Blank lines closing the block stay after the new entries, before the next section.
    tail = []
    while block and not block[-1].strip():
        tail.insert(0, block.pop())
    widths = [len(line) - len(line.lstrip(" ")) for line in block
              if line.strip() and not line.lstrip().startswith("#")]
    indent = min(widths, default=2) or 2
    newline = "\r\n" if lines[start].endswith("\r\n") else "\n"
    if block and not block[-1].endswith(("\n", "\r\n")):
        block[-1] += newline
    block += [f"{' ' * indent}{_yaml_key(name)}: {{}}{newline}" for name in added]
    head = lines[:start + 1]
    if not head[-1].endswith(("\n", "\r\n")):
        head[-1] += newline
    return "".join(head + block + tail + lines[end:])


def _yaml_key(name):
    return name if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name) else json.dumps(name)


def _detected_worktree(value):
    """A reported `worktree` section, kept only when create and path are both given; an existing
    section in the file is never touched (whole section or nothing)."""
    if not isinstance(value, dict):
        return None
    section = {key: str(value[key]).strip() for key in ("create", "path", "branch", "remove")
               if isinstance(value.get(key), str) and value[key].strip()}
    return section if section.get("create") and section.get("path") else None


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
        environment = config["environment"]
        _check_strings("environment", environment, ENVIRONMENT_KEYS, "environment", issues)
        if isinstance(environment, dict) and environment.get("start") and not environment.get("ready"):
            issues.append(Issue("warning", "config-missing-command",
                                "no `ready` command; QA will treat the stack as up as soon as "
                                "`start` returns — add a health probe (e.g. curl -fsS …/health)",
                                "environment.ready"))
    if "infrastructure" in config:
        infrastructure = config["infrastructure"]
        _check_strings("infrastructure", infrastructure, {"level"}, "infrastructure", issues)
        if isinstance(infrastructure, dict) and infrastructure.get("level") not in (
                None, *INFRASTRUCTURE_LEVELS):
            issues.append(Issue("error", "config-shape",
                                f"must be one of: {', '.join(INFRASTRUCTURE_LEVELS)}",
                                "infrastructure.level"))
    if "design" in config:
        design = config["design"]
        if not isinstance(design, dict):
            issues.append(Issue("error", "config-shape", "`design` must be a mapping", "design"))
        else:
            for key, value in design.items():
                if key != "light_max_criteria":
                    issues.append(Issue("error", "config-unknown-key",
                                        f"unknown key `{key}` (allowed: light_max_criteria)",
                                        f"design.{key}"))
                elif not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                    issues.append(Issue("error", "config-shape",
                                        "must be a positive whole number of acceptance criteria",
                                        "design.light_max_criteria"))
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
    if "worktree" in config:
        issues.extend(_check_worktree(config["worktree"]))
    if "delivery" in config:
        delivery = config["delivery"]
        _check_strings("delivery", delivery, DELIVERY_KEYS, "delivery", issues)
        if isinstance(delivery, dict) and delivery.get("mode") not in (None, *DELIVERY_MODES):
            issues.append(Issue("error", "config-shape",
                                f"must be one of: {', '.join(DELIVERY_MODES)}", "delivery.mode"))
    return issues


def _check_worktree(section):
    """`worktree`: create + path together; path per feature and repo, inside the workspace."""
    issues = []
    _check_strings("worktree", section, WORKTREE_KEYS, "worktree", issues)
    if not isinstance(section, dict) or issues:
        return issues
    values = {key: str(section.get(key) or "").strip() for key in WORKTREE_KEYS}
    for key in ("create", "path"):
        if not values[key]:
            issues.append(Issue("error", "config-missing-command",
                                "`worktree.create` and `worktree.path` go together: Maestro runs "
                                "create, then finds each repository at path", f"worktree.{key}"))
    for key, value in values.items():
        unknown = sorted(set(re.findall(r"(?<!\$)\{(\w+)\}", value)) - WORKTREE_PLACEHOLDERS[key])
        if unknown:
            issues.append(Issue("error", "config-shape",
                                f"unknown placeholder(s) {', '.join('{' + u + '}' for u in unknown)} "
                                f"(allowed: {', '.join('{' + a + '}' for a in sorted(WORKTREE_PLACEHOLDERS[key]))})",
                                f"worktree.{key}"))
    path = values["path"]
    if path:
        if "{slug}" not in path or "{repo}" not in path:
            issues.append(Issue("error", "config-shape",
                                "must contain {slug} and {repo}: one worktree per feature and "
                                "repository", "worktree.path"))
        if os.path.isabs(path) or ".." in path.replace("\\", "/").split("/"):
            issues.append(Issue("error", "config-shape",
                                "must be a path inside the workspace (relative, no ..)",
                                "worktree.path"))
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
    issues = check(config, discovered)
    # Optional template registry.yaml: warn on clone/registry drift.
    try:
        import registry as registry_mod
        result = registry_mod.validate(root, strict=False)
        if result.get("present"):
            for msg in result.get("errors") or []:
                issues.append(Issue("error", "registry-mismatch", msg, "registry.yaml"))
            for msg in result.get("warnings") or []:
                issues.append(Issue("warning", "registry-drift", msg, "registry.yaml"))
    except Exception as exc:  # noqa: BLE001 — preflight must never crash on optional registry
        issues.append(Issue("warning", "registry-unreadable", str(exc), "registry.yaml"))
    return issues


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
    parser.add_argument("command", choices=["preflight", "init", "apply", "sync"])
    parser.add_argument("--root", default=".")
    parser.add_argument("--detected", help="detect-stack JSON report (apply)")
    parser.add_argument("--dry-run", action="store_true", help="sync: report, write nothing")
    args = parser.parse_args(argv)
    if args.command == "sync":
        try:
            print(json.dumps(sync(args.root, dry_run=args.dry_run), indent=2))
        except ConfigError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0
    if args.command == "init":
        # `wrote` or `exists` — /maestro-init reports which one happened.
        print(init(args.root))
        return 0
    if args.command == "apply":
        if not args.detected:
            print("apply requires --detected <detect-stack.json>", file=sys.stderr)
            return 2
        try:
            with open(args.detected, encoding="utf-8") as fh:
                detected = json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"cannot read detected stacks: {exc}", file=sys.stderr)
            return 2
        try:
            print(json.dumps(apply_detected(args.root, detected)))
        except ConfigError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0
    issues = preflight(args.root)
    for issue in issues:
        print(str(issue), file=sys.stderr)
    result = summary(issues)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
