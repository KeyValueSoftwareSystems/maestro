---
name: detect-stack
description: Scan the codebase to detect its technology stack(s), then install only the matching stack-tagged skills and agents (plus the always-installed core SDLC pack) by running the installer with a --stack filter. Front door for /detect-stack.
allowed-tools: Read, Grep, Glob, Bash
tags: [maestro, bootstrap, install]
---

# detect-stack — detect the repo's stack and install the matching skills

Read the repository, decide which technology **stacks** it uses, then install the
per-stack skills + agents tagged for exactly those stacks. Core SDLC skills (anything
with no `stack:` tag) install regardless. This is a one-time (re-runnable) bootstrap.

## Inputs
Run from the root of the target repo (or a `codebase/`-of-repos umbrella). No artifact
inputs — you discover everything from the files on disk. If your instruction names IDE
targets (`claude-code`, `cursor`), use them; otherwise infer them (below).

## Stack vocabulary
Emit only these tokens (they match the `stack:` tags on the skills/agents):

`go` · `java` · `kotlin` · `python` · `react` · `vue` · `angular` · `node` · `rust` ·
`flutter` · `android` · `db`

## Detection method
1. **Scan for manifests and sources** (breadth-first; ignore `node_modules`, `vendor`,
   `.git`, build output). Map signals to tokens — a repo can match several:

   | Signal (files / dependencies) | Stack token |
   | --- | --- |
   | `go.mod`, `*.go` | `go` |
   | `pom.xml`, `build.gradle`(.kts), `*.java` (Spring Boot / Quarkus deps still ⇒ java) | `java` |
   | `*.kt`, `*.kts`, Kotlin Gradle plugin | `kotlin` |
   | `requirements.txt`, `pyproject.toml`, `setup.py`, `Pipfile`, `*.py` (Django/FastAPI deps ⇒ still python) | `python` |
   | `package.json` with `react`/`next` | `react` |
   | `package.json` with `vue`/`nuxt` | `vue` |
   | `package.json` with `@angular/core` | `angular` |
   | `package.json` with `@nestjs/*`, or Node/TS backend without a UI framework | `node` |
   | `Cargo.toml` | `rust` |
   | `pubspec.yaml` | `flutter` |
   | `AndroidManifest.xml`, `com.android.*` Gradle plugin | `android` |
   | SQL migrations dir, or `postgres`/`mysql`/`redis`/`prisma`/`clickhouse` deps | `db` |

2. **Prefer dependency evidence over file extensions** when they disagree (a `.ts` file in
   a Go repo's tooling dir is not a `node` stack). Only emit a token you can point to a
   concrete signal for; list that evidence.
3. **De-duplicate and sort** the tokens.

## Install step
1. **Pick IDE targets.** `.cursor/` present ⇒ include `cursor`; otherwise (or if `.claude/`
   present) use `claude-code`. Default `claude-code`.
2. **Run the installer with the detected filter.** Prefer the repo-local wrapper; fall back
   to the installer script:
   ```bash
   ./maestro install <ide-targets> --stack <detected-tokens>
   # or, if there is no ./maestro wrapper:
   bash install.sh <ide-targets> --stack <detected-tokens>
   ```
   e.g. `./maestro install claude-code --stack go,react,db`. The installer always adds the
   core SDLC skills; `--stack` only gates the per-stack ones.
3. **Report** what installed (the installer prints `N installed, M skipped by --stack`).

## Standards
- Detect what the repo **actually uses today** — never install a stack you can't evidence.
- Re-runnable: re-running re-detects and re-installs; it overwrites the installed copies,
  never the `skills/` source of truth.
- If you detect a stack the vocabulary doesn't cover, say so plainly and skip it (don't
  invent a token — the installer would match nothing).

## Safety
- Read-only against application code. The only thing you run is the installer, which writes
  ONLY into IDE config dirs (`.claude/`, `.cursor/`) — never application code, never
  `.maestro/` run state.
- If no stack is detected, install just the core pack (`--stack` with no tokens installs
  everything; to install core-only, pass a token that matches nothing is wrong — instead
  report "no stack detected" and let the human choose).

## Output contract
Return `stacks` (the detected stack tokens, comma-separated), `installed_count` (skills +
agents installed), and `summary` (one line naming the stacks and IDE targets).
