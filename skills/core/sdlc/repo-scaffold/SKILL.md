---
name: repo-scaffold
description: Create the starting skeleton of new repositories from an approved high-level design — project layout, a passing build and test, lint, a README, CI, a container image when the design deploys one, and a codebase map — and report each repository's commands. Front door for /repo-scaffold.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write
tags: [sdlc, implement, greenfield]
---

# repo-scaffold

Turn an empty repository into the smallest working starting point the design calls for, so the
detailed design and implementation build on real, verifiable ground. Scaffolding is not the
feature: write no feature behaviour.

## Inputs

Your instructions name the approved HLD (its Repositories section lists each repository, its
stack and purpose), the repositories to scaffold (already created and committed empty) and where
to write the scaffold report. Standalone? scaffold the repositories the user names and tell them
where the report is.

## For each repository

1. **Layout** — the stack's conventional structure and package manager, at current stable
   versions pinned in the lock file the stack uses. Follow the installed stack skill for that
   stack when there is one.
2. **Build, test and lint** — one trivial passing test, a build that compiles or packages it, and
   the stack's standard linter configured. Every command runs from the repository root without
   network access beyond installing declared dependencies.
3. **README** — what the repository is for (from the HLD), how to build, test and run it.
4. **CI** — a pipeline in the repository's CI system (GitHub Actions by default) that runs the
   same build, lint and test commands.
5. **Deployability** — when the HLD's Infrastructure and operations section deploys this
   repository, a container image definition; when it names an infrastructure platform, that
   repository's starting definitions (an empty Terraform root module, a Helm chart) — using the
   matching infrastructure pack when installed.
6. **Codebase map** — at the path your instructions name (by default
   `docs/codebase-maps/<name>.md`): the layout, entry points and conventions, so later steps read
   the map instead of exploring.
7. **Commit** the skeleton on the repository's default branch.

## Report

Write the scaffold report your instructions name as
`{"repos": {"<name>": {"stack": "<stack>", "commands": {"build": "...", "test": "...",
"lint": "...", "security": "..."}}}}`. `build` and `test` are required; the engine adds them to
the project configuration and runs them once to prove the skeleton works.

## Safety

Touch only the repositories you were given. No feature code, no secrets, no real credentials or
cloud resources; infrastructure definitions are files only — never apply them.

## Output contract

Return `summary`: one line naming each repository scaffolded and its stack.
