#!/usr/bin/env python3
"""The QA environment and the project's own E2E suites, run by the engine from maestro.config.yaml.

  qa_env.py up   [--root .] --manifest M      environment.start, then environment.ready
  qa_env.py harness [--root .] (--manifest M | --slug S) --out R
                 prepare the E2E harness the QA agent authors its suite in (--slug: the
                 feature's worktrees.json, before implementation; --manifest: in QA)
  qa_env.py e2e  [--root .] --manifest M --out R
                 each manifest repository's `e2e` command, in its verified worktree
  qa_env.py down [--root .] --manifest M      environment.stop (never fails the run)

Every command gets the exact code under test as environment variables, so a start command can
build the stack from the verified worktrees instead of the main checkouts:
  MAESTRO_SLUG, MAESTRO_MANIFEST, and per repository MAESTRO_WORKTREE_<REPO> and
  MAESTRO_COMMIT_<REPO> (<REPO> upper-cased, non-alphanumerics as `_`).

Nothing configured is not a failure: `up`/`down` report `configured: false`, and `e2e` passes
with a summary saying no suite is configured, so QA results stay agent-reported for that repo.
`up` exits 1 when start or ready fails (QA cannot run against a stack that is not up). `e2e`
writes a receipt like the verify step's and exits 0; route on `passed`.

`harness` decides how the QA agent's suite runs, so the agent never has to install a framework.
The first that applies wins:
  1. the workspace E2E folder -> mode `workspace`: maestro.config.yaml `e2e.path`, else an `e2e/`
     folder at the workspace root holding a package.json or a Playwright config. Its dependencies
     are installed when node_modules is missing; for Playwright, headless Chromium too (when a web repo is
     in scope) and a browser launch. Specs stay in the run's `qa/tests/`; Playwright runs from the
     workspace folder with MAESTRO_QA_TESTS pointing at them, so the workspace config must read
     `testDir: process.env.MAESTRO_QA_TESTS ?? './tests'` (checked; the summary says how to fix it).
     `qa/node_modules` links to the workspace's, so specs resolve `@playwright/test` and helpers.
  2. which repositories are web comes from maestro.config.yaml: a repo whose `stack` is set is web
     when it names a web stack (react, vue, angular, ...). Only a repo without a `stack` falls back
     to its package.json (at the root or one folder down, for monorepos). No web repository ->
     mode `not-needed` (API journeys need no browser);
  3. every web repository has its own E2E framework (an `e2e` command, a Playwright/Cypress/
     WebdriverIO config, or the package in package.json) -> mode `existing`, nothing installed;
  4. otherwise -> mode `playwright`: a self-contained Playwright project in the run's `qa/` folder
     (package.json, playwright.config.mjs, tests/), `npm install`, `npx playwright install
     --only-shell chromium` (headless only), then a browser launch. Web repos that do have a framework keep using it.
Everything is idempotent: delivery runs it before implementation so a broken setup surfaces
early, and QA runs it again as a quick re-check (nothing is reinstalled when it is in place).
The setup commands share one time budget (HARNESS_BUDGET_S) that fits inside the workflow step's
timeout, so a slow download ends as a reported failure rather than a killed step. It writes a
receipt with each step's log and exits 0; route on `ready`. A setup failure is an environment
problem for a person, not a test failure for the fix loop.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

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

# Stack tokens (maestro.config.yaml `stack`) and package.json dependencies that mark a web UI.
WEB_STACKS = {"react", "vue", "angular", "svelte", "next", "nextjs", "nuxt", "solid", "preact",
              "web", "frontend"}
WEB_PACKAGES = {"react", "react-dom", "vue", "@angular/core", "svelte", "@sveltejs/kit", "next",
                "nuxt", "solid-js", "preact", "lit"}
E2E_PACKAGES = {"@playwright/test", "playwright", "cypress", "webdriverio", "@wdio/cli",
                "testcafe", "nightwatch"}
E2E_CONFIGS = tuple(f"{name}.{ext}" for name in ("playwright.config", "cypress.config")
                    for ext in ("ts", "js", "mjs", "cjs")) + (
    "cypress.json", "wdio.conf.ts", "wdio.conf.js")
PLAYWRIGHT_VERSION = "^1.55.0"
# All harness setup commands together; below the qa_harness step's `timeout` (1800s) in qa.yaml.
HARNESS_BUDGET_S = 1500
SKIP_DIRS = {"node_modules", "dist", "build", "coverage", "vendor"}
WORKSPACE_E2E_DEFAULT = "e2e"
WORKSPACE_TESTS_ENV = "MAESTRO_QA_TESTS"
INSTALL = "npm install --no-audit --no-fund"
CLEAN_INSTALL = "npm ci --no-audit --no-fund"
# QA always runs headless: only the headless shell (~90 MB, not ~250 MB with full Chromium).
# A config that sets `channel: 'chromium'` needs the full browser and fails the smoke launch.
BROWSERS = "npx --no-install playwright install --only-shell chromium"
PLAYWRIGHT_CONFIG = """// Written by the Maestro engine (qa_env.py harness). The QA agent's specs live in tests/.
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  outputDir: './test-results',
  fullyParallel: true,
  retries: 0,
  reporter: [['list'], ['json', { outputFile: 'playwright-results.json' }],
             ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: process.env.BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
"""
BROWSER_SMOKE = ("node -e \"require('@playwright/test').chromium.launch()"
                 ".then(b => b.close()).catch(e => { console.error(e.message); process.exit(1); })\"")


def _package_deps(folder):
    try:
        with open(os.path.join(folder, "package.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set()
    deps = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        if isinstance(data.get(key), dict):
            deps.update(data[key])
    return deps


def _package_folders(worktree):
    """The worktree and its first-level subfolders (monorepo apps such as web/, frontend/)."""
    folders = [worktree]
    try:
        names = sorted(os.listdir(worktree))
    except OSError:
        return folders
    for name in names:
        path = os.path.join(worktree, name)
        if not name.startswith(".") and name not in SKIP_DIRS and os.path.isdir(path):
            folders.append(path)
    return folders


def _worktree_path(root, entry):
    worktree = entry.get("worktree") or ""
    return worktree if os.path.isabs(worktree) else os.path.join(root, worktree)


def classify_repo(config, repo, worktree):
    """-> (is_web, web_source, framework or None) for one manifest repository.

    maestro.config.yaml decides: a repo with a `stack` is web exactly when that stack names a
    web framework. package.json is read only for a repo with no `stack` configured."""
    folders = _package_folders(worktree)
    deps_by_folder = {folder: _package_deps(folder) for folder in folders}
    stack = str(((config.get("repos") or {}).get(repo) or {}).get("stack") or "").lower()
    tokens = {t.strip() for t in stack.split(",") if t.strip()}
    if tokens:
        is_web, source = bool(tokens & WEB_STACKS), "maestro.config.yaml stack"
    else:
        is_web = any(deps & WEB_PACKAGES for deps in deps_by_folder.values())
        source = "package.json"
    if project_config.repo_commands(config, repo).get("e2e"):
        return is_web, source, "e2e command"
    for folder in folders:
        for name in E2E_CONFIGS:
            if os.path.exists(os.path.join(folder, name)):
                return is_web, source, os.path.relpath(os.path.join(folder, name), worktree)
    found = sorted(set().union(*deps_by_folder.values()) & E2E_PACKAGES)
    return is_web, source, (found[0] if found else None)


def _write_if_missing(path, text):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def setup_playwright(qa_dir, log_dir, budget_s, env):
    """Create and install the Playwright project in qa_dir, all commands within budget_s.
    -> list of step results."""
    os.makedirs(os.path.join(qa_dir, "tests"), exist_ok=True)
    _write_if_missing(os.path.join(qa_dir, "package.json"), json.dumps({
        "name": "maestro-qa-suite", "private": True,
        "scripts": {"test": "playwright test"},
        "devDependencies": {"@playwright/test": PLAYWRIGHT_VERSION}}, indent=2) + "\n")
    _write_if_missing(os.path.join(qa_dir, "playwright.config.mjs"), PLAYWRIGHT_CONFIG)
    _write_if_missing(os.path.join(qa_dir, ".gitignore"),
                      "node_modules/\ntest-results/\nplaywright-report/\n")
    installed = os.path.exists(os.path.join(qa_dir, "node_modules", "@playwright", "test",
                                            "package.json"))
    commands = [] if installed else [("install", INSTALL)]
    commands += [("browsers", BROWSERS), ("browser-smoke", BROWSER_SMOKE)]
    return run_steps(qa_dir, commands, log_dir, budget_s, env)


def run_steps(cwd, commands, log_dir, budget_s, env):
    """Run (name, command) pairs in cwd within one budget; stop at the first failure."""
    steps = []
    deadline = time.monotonic() + budget_s
    for name, command in commands:
        remaining = int(deadline - time.monotonic())
        if remaining < 1:
            steps.append({"step": name, "command": command, "log": None, "exit_code": 124,
                          "duration_s": 0, "status": "timed-out", "log_sha256": None,
                          "tail": f"[maestro] harness budget of {budget_s}s used up"})
            break
        result = _run(command, cwd, remaining, os.path.join(log_dir, f"{name}.log"), env)
        steps.append({"step": name, "command": command,
                      "log": os.path.join(log_dir, f"{name}.log"), **result})
        if result["status"] != "passed":
            break
    return steps


def _playwright_config(folder):
    for ext in ("ts", "js", "mjs", "cjs"):
        path = os.path.join(folder, f"playwright.config.{ext}")
        if os.path.exists(path):
            return path
    return None


def workspace_e2e(root, config):
    """-> (info or None, error or None). info: {dir, framework, command}."""
    section = config.get("e2e") if isinstance(config.get("e2e"), dict) else {}
    configured = section.get("path")
    rel = configured or WORKSPACE_E2E_DEFAULT
    folder = rel if os.path.isabs(rel) else os.path.join(root, rel)
    if not os.path.isdir(folder):
        if configured:
            return None, f"maestro.config.yaml e2e.path `{configured}` is not a folder"
        return None, None
    pw_config = _playwright_config(folder)
    deps = _package_deps(folder)
    if not configured and not pw_config and not os.path.exists(os.path.join(folder, "package.json")):
        return None, None  # an unrelated e2e/ folder
    if pw_config or deps & {"@playwright/test", "playwright"}:
        framework = "playwright"
    else:
        found = sorted(deps & E2E_PACKAGES)
        framework = found[0] if found else "unknown"
    command = section.get("command") or ("npx playwright test" if framework == "playwright"
                                         else None)
    return {"dir": folder, "framework": framework, "command": command,
            "config": pw_config}, None


def setup_workspace(info, qa_dir, browsers, log_dir, budget_s, env):
    """Install the workspace E2E folder when needed and link the run's qa/ folder to it.
    -> (steps, error or None)."""
    folder = info["dir"]
    if info["framework"] == "playwright":
        if not info["config"]:
            return [], (f"{os.path.basename(folder)}/ uses Playwright but has no "
                        f"playwright.config.*")
        with open(info["config"], encoding="utf-8") as fh:
            if WORKSPACE_TESTS_ENV not in fh.read():
                return [], (f"{os.path.relpath(info['config'], os.path.dirname(folder))} must take "
                            f"its specs from the run: set `testDir: process.env."
                            f"{WORKSPACE_TESTS_ENV} ?? './tests'`")
    commands = []
    if (os.path.exists(os.path.join(folder, "package.json"))
            and not os.path.isdir(os.path.join(folder, "node_modules"))):
        lock = os.path.exists(os.path.join(folder, "package-lock.json"))
        commands.append(("install", CLEAN_INSTALL if lock else INSTALL))
    if info["framework"] == "playwright" and browsers:
        commands += [("browsers", BROWSERS), ("browser-smoke", BROWSER_SMOKE)]
    steps = run_steps(folder, commands, log_dir, budget_s, env)
    if any(s["status"] != "passed" for s in steps):
        return steps, None
    os.makedirs(os.path.join(qa_dir, "tests"), exist_ok=True)
    link = os.path.join(qa_dir, "node_modules")
    target = os.path.join(folder, "node_modules")
    if os.path.isdir(target) and not os.path.lexists(link):
        os.symlink(target, link)
    return steps, None


def _harness_repos(root, args):
    """-> ([(repo, worktree)], env) from the manifest (QA) or the worktree record (delivery)."""
    if args.manifest:
        manifest = _manifest(root, args.manifest)
        repos = [(e.get("repo", ""), _worktree_path(root, e))
                 for e in manifest.get("repositories") or []]
        return repos, code_under_test_env(manifest, args.manifest)
    import worktrees  # noqa: E402  (only the delivery-time call needs it)
    record = worktrees.load_record(root, args.slug) or {}
    repos = [(repo, _worktree_path(root, {"worktree": entry.get("path")}))
             for repo, entry in sorted((record.get("repos") or {}).items())]
    env = {"MAESTRO_SLUG": args.slug}
    env.update({f"MAESTRO_WORKTREE_{_env_name(repo)}": path for repo, path in repos})
    return repos, env


def _summarize_steps(receipt, root, steps):
    receipt["steps"] = [{**s, "log": s["log"] and os.path.relpath(s["log"], root)} for s in steps]
    failed = next((s for s in receipt["steps"] if s["status"] != "passed"), None)
    if not failed:
        return None
    where = f"log: {failed['log']}" if failed["log"] else failed["tail"]
    return f"failed at `{failed['step']}` (exit {failed['exit_code']}); {where}"


def cmd_harness(args):
    full_out = args.out if os.path.isabs(args.out) else os.path.join(args.root, args.out)
    qa_dir = os.path.dirname(full_out)
    rel_dir = os.path.relpath(qa_dir, args.root)
    if _simulated():
        print(json.dumps({"ready": True, "mode": "not-needed", "dir": rel_dir, "workspace_dir": "",
                          "receipt_path": args.out, "summary": "[simulated] no harness needed"}))
        return 0
    if not (args.manifest or args.slug):
        print("harness needs --manifest or --slug", file=sys.stderr)
        return 2
    config = project_config.load(args.root) or {}
    repos, env = _harness_repos(args.root, args)
    web, frameworks, sources = [], {}, {}
    for repo, worktree in repos:
        is_web, source, framework = classify_repo(config, repo, worktree)
        sources[repo] = source
        if is_web:
            web.append(repo)
        if framework:
            frameworks[repo] = framework
    covered = [repo for repo in web if repo in frameworks]
    uncovered = [repo for repo in web if repo not in frameworks]
    existing = ", ".join(f"{repo} ({frameworks[repo]})" for repo in covered)
    receipt = {"schema_version": 1, "ran_at": statemod.now_iso(), "web_repos": web,
               "web_source": sources, "frameworks": frameworks, "dir": rel_dir, "steps": []}
    workspace, workspace_error = workspace_e2e(args.root, config)
    workspace_dir = ""
    if workspace_error:
        mode, ready, summary = "workspace", False, f"Workspace E2E setup unusable: {workspace_error}"
    elif workspace:
        mode = "workspace"
        workspace_dir = os.path.relpath(workspace["dir"], args.root)
        receipt["workspace"] = {"dir": workspace_dir, "framework": workspace["framework"],
                                "command": workspace["command"]}
        missing = [tool for tool in ("node", "npm", "npx") if not shutil.which(tool)]
        if missing and os.path.exists(os.path.join(workspace["dir"], "package.json")):
            ready, problem = False, f"{', '.join(missing)} not found on PATH"
        else:
            steps, problem = setup_workspace(workspace, qa_dir, bool(web),
                                             os.path.join(qa_dir, "harness-logs"),
                                             HARNESS_BUDGET_S, env)
            problem = problem or _summarize_steps(receipt, args.root, steps)
            ready = problem is None
        if not ready:
            summary = f"Workspace E2E setup ({workspace_dir}) not ready: {problem}"
        elif workspace["framework"] == "playwright":
            summary = (f"Use the workspace E2E setup in {workspace_dir} (Playwright): write specs "
                       f"in {rel_dir}/tests and run them from {workspace_dir} with "
                       f"{WORKSPACE_TESTS_ENV}=<absolute path of {rel_dir}/tests> "
                       f"{workspace['command']} --output <absolute path of "
                       f"{rel_dir}/test-results>")
        else:
            summary = (f"Use the workspace E2E setup in {workspace_dir} ({workspace['framework']}"
                       + (f", run with `{workspace['command']}`" if workspace["command"] else "")
                       + f"); keep this feature's specs in {rel_dir}")
    elif not web:
        mode, ready = "not-needed", True
        summary = ("No web repository detected (" + ", ".join(
            f"{repo}: {sources[repo]}" for repo in sources) + "); no browser harness prepared. "
            "If a repo is a web app, set its `stack` in maestro.config.yaml")
    elif not uncovered:
        mode, ready = "existing", True
        summary = "Use the existing E2E framework: " + existing
    else:
        mode = "playwright"
        missing = [tool for tool in ("node", "npm", "npx") if not shutil.which(tool)]
        if missing:
            ready = False
            summary = (f"Playwright harness not set up: {', '.join(missing)} not found on PATH "
                       f"(web repos without an E2E framework: {', '.join(uncovered)})")
        else:
            steps = setup_playwright(qa_dir, os.path.join(qa_dir, "harness-logs"),
                                     HARNESS_BUDGET_S, env)
            problem = _summarize_steps(receipt, args.root, steps)
            ready = problem is None
            if problem:
                summary = f"Playwright harness setup {problem}"
            else:
                summary = (f"Playwright harness ready in {rel_dir} (specs in tests/, run "
                           f"`npx playwright test` there) for: {', '.join(uncovered)}")
        if existing:
            summary += f". Use the existing E2E framework for: {existing}"
    receipt.update({"mode": mode, "ready": ready, "summary": summary})
    _write_json(full_out, receipt)
    print(json.dumps({"ready": ready, "mode": mode, "dir": rel_dir,
                      "workspace_dir": workspace_dir,
                      "receipt_path": os.path.relpath(full_out, args.root), "summary": summary}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn in (("up", cmd_up), ("down", cmd_down), ("e2e", cmd_e2e),
                     ("harness", cmd_harness)):
        p = sub.add_parser(name)
        p.add_argument("--root", default=".")
        p.add_argument("--manifest", required=name != "harness")
        if name == "harness":
            p.add_argument("--slug", help="the feature; reads its worktrees.json (delivery)")
        if name in ("e2e", "harness"):
            p.add_argument("--out", required=True)
        p.set_defaults(fn=fn)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
