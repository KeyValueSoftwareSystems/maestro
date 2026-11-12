---
name: detect-stack
description: Scan the codebase to detect its technology stack(s) and each repository's E2E suite (proposed for the engine to confirm), then install only the matching stack-tagged skills (plus the always-installed core SDLC pack) by running the installer with a --stack filter. Does not write maestro.config.yaml. Front door for /detect-stack.
allowed-tools: Read, Grep, Glob, Bash
tags: [maestro, bootstrap, install]
---

# detect-stack — detect the repo's stack and install the matching skills

Read the repository, decide which technology **stacks** it uses, then install the
per-stack skills tagged for exactly those stacks. Core SDLC skills (anything
with no `stack:` tag) install regardless. This is a one-time (re-runnable) bootstrap.

## Inputs
Run from the root of the target repo (or a `codebase/`-of-repos umbrella). No artifact
inputs — you discover everything from the files on disk. If your instruction names harness
targets (`claude-code`, `cursor`, `codex`, `hermes`), use them; otherwise infer them (below).

## Stack vocabulary
Emit only these tokens (they match the `stack:` tags on the skills):

`go` · `java` · `kotlin` · `python` · `django` · `fastapi` · `pytorch` · `react` · `vue` ·
`angular` · `node` · `rust` · `flutter` · `android` · `db` · `terraform` · `kubernetes` ·
`docker`

## Detection method
1. **Scan for manifests and sources** (breadth-first; ignore `node_modules`, `vendor`,
   `.git`, build output). Map signals to tokens — a repo can match several:

   | Signal (files / dependencies) | Stack token |
   | --- | --- |
   | `go.mod`, `*.go` | `go` |
   | `pom.xml`, `build.gradle`(.kts), `*.java` (Spring Boot / Quarkus deps still ⇒ java) | `java` |
   | `*.kt`, `*.kts`, Kotlin Gradle plugin | `kotlin` |
   | `requirements.txt`, `pyproject.toml`, `setup.py`, `Pipfile`, `*.py` | `python` |
   | a `django` dependency, or `manage.py` with Django settings (plus `python`) | `django` |
   | a `fastapi` dependency (plus `python`) | `fastapi` |
   | a `torch` dependency (plus `python`) | `pytorch` |
   | `package.json` with `react`/`next` | `react` |
   | `package.json` with `vue`/`nuxt` | `vue` |
   | `package.json` with `@angular/core` | `angular` |
   | `package.json` with `@nestjs/*`, or Node/TS backend without a UI framework | `node` |
   | `Cargo.toml` | `rust` |
   | `pubspec.yaml` | `flutter` |
   | `AndroidManifest.xml`, `com.android.*` Gradle plugin | `android` |
   | SQL migrations dir, or `postgres`/`mysql`/`redis`/`prisma`/`clickhouse` deps | `db` |
   | `*.tf` | `terraform` |
   | `Chart.yaml`, `kustomization.yaml`, Kubernetes manifests (`apiVersion:` + `kind: Deployment`…) | `kubernetes` |
   | `Dockerfile`, `docker-compose*.yml`, `compose.yaml` | `docker` |

2. **Prefer dependency evidence over file extensions** when they disagree (a `.ts` file in
   a Go repo's tooling dir is not a `node` stack). Only emit a token you can point to a
   concrete signal for; list that evidence.
3. **De-duplicate and sort** the tokens.

## E2E suite
For each repository, find whether it has an end-to-end / UI-journey suite and the command that
runs it. You only propose; the engine confirms it before it is recorded, so report what you
found, not what you hope. Look beyond the obvious, for example:

- **Frameworks** (examples, not a complete list): Playwright, Cypress, WebdriverIO, Nightwatch,
  TestCafe, Puppeteer, Selenium, Cucumber (`*.feature`), Robot Framework, Karate, Appium, Detox,
  Maestro flows (in the app repo), Espresso (`androidTest/`), XCUITest (`*UITests`), Flutter
  `integration_test/`, Rails system tests, Laravel Dusk, Go tests behind an `e2e` build tag.
- **Where**: dependencies and framework config files; `package.json` scripts and Makefile
  targets; CI jobs (`.github/workflows/*`, `.gitlab-ci.yml`, `Jenkinsfile`, …), which usually
  show the exact command and its environment; monorepo sub-projects (`apps/*-e2e`, packages with
  their own config); a repository in the workspace that exists only to hold E2E tests.
- **Not E2E**: unit and component tests, and integration tests that never drive the product
  the way a user or client does. A config file with no specs is not a suite.

Per repository, report `e2e` as either
`{"command": <the command that runs the suite, from the repo root>, "list": <the framework's
list / collect / dry-run command that prints the specs without running them, when it has one —
e.g. "npx playwright test --list", "npx jest --listTests", "pytest --collect-only -q -m e2e",
"go test -list . -tags e2e ./e2e/...">, "framework": <name>, "evidence": [<repo-relative files
that run or define the command: the package.json, Makefile or CI file>]}`
or `{"command": null, "reason": <one line: what you looked for and did not find>}`.
Prefer the repository's own script or CI command over a framework default; use a framework
default (`npx playwright test`) only when its config and specs exist. A list command must not
install anything. Never invent a command.

When your instruction asks only for the E2E suite of named repositories, scan just those, report
`repos` with `name` and `e2e`, and skip the stack tokens and the install step.

## Install step
1. **Pick harness targets.** Include every already-installed Maestro host you can evidence:
   `.claude/skills/maestro/SKILL.md` ⇒ `claude-code`,
   `.cursor/skills/maestro/SKILL.md` ⇒ `cursor`, and
   `.agents/skills/maestro/SKILL.md` ⇒ `codex` (that one copy also serves Hermes Agent). If none is present, default to
   `claude-code`. Do not treat a generic `.agents/` folder as proof that Maestro was installed
   for Codex.
2. **Run the installer with the detected filter.** Prefer the repo-local wrapper; fall back
   to the installer script:
   ```bash
   ./maestro install <harness-targets> --stack <detected-tokens>
   # or, if there is no ./maestro wrapper:
   bash install.sh <harness-targets> --stack <detected-tokens>
   ```
   e.g. `./maestro install codex --stack go,react,db`. The installer always adds the
   core SDLC skills; `--stack` only gates the per-stack ones.
3. **Report** what installed (the installer prints `N installed, M skipped by --stack`).

Do not write `maestro.config.yaml`. `/maestro-init` passes your per-repo result to the
**project-config** skill, which owns that file.

## Standards
- Detect what the repo **actually uses today** — never install a stack you can't evidence.
- Re-runnable: re-running re-detects and re-installs; it overwrites the installed copies,
  never the `skills/` source of truth.
- If you detect a stack the vocabulary doesn't cover, say so plainly and skip it (don't
  invent a token — the installer would match nothing).

## Safety
- Read-only against application code. The only thing you run is the installer, which writes
  ONLY into harness config dirs (`.claude/`, `.cursor/`, `.agents/`) — never application code,
  never `maestro.config.yaml`, never `.maestro/runs/` state.
- If no stack is detected, install just the core pack (`--stack` with no tokens installs
  everything; to install core-only, pass a token that matches nothing is wrong — instead
  report "no stack detected" and let the human choose).

## Output contract
Return `stacks` (the detected stack tokens, comma-separated), `installed_count` (skills +
agents installed), `repos` (one entry per repo: `name`, `stacks` for that repo, the
`evidence` files you already cited, and `e2e`, the E2E suite proposal above), and `summary` (one line naming the stacks and harness
targets). Do not write those fields to `maestro.config.yaml`.
