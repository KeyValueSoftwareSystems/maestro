---
name: repo-tasks
description: Build a validated, repo-specific parallel task DAG from an approved LLD and contract.
allowed-tools: Read, Grep, Glob, Bash, Write, Edit
tags: [sdlc, plan, repository]
---

# repo-tasks

Plan only the repository named by the workflow. Read its `AGENTS.md`/`CLAUDE.md`, codebase
map, approved LLD, contract, and the live files needed to verify paths. Do not edit product
code.

Write the requested `tasks.json` in one pass using
`.maestro/engine/schemas/tasks.schema.json`. Set `stack` to the repository name. Split work
into independent slices with disjoint writes; dependencies may only point within a slice.
Every task must list exact reads/writes, a concrete test, applicable standards, and whether
it needs a human gate. Include negative paths, security, compatibility, observability, and
framework-native verification appropriate to the detected repo (web, backend, mobile, or
otherwise). Validate with `python3 .maestro/engine/validate_tasks.py <path>` and correct any
reported error before returning.

Return `task_count` and `slice_count` as short scalar JSON fields on the last line.
