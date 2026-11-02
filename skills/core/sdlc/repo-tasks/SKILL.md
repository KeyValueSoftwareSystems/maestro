---
name: repo-tasks
description: Build a validated, repo-specific parallel task DAG from an approved LLD and contract.
allowed-tools: Read, Grep, Glob, Bash, Write, Edit
tags: [sdlc, plan, repository]
---

# repo-tasks

Plan only the repository named by your instructions. Read its `AGENTS.md`/`CLAUDE.md`,
codebase map, approved LLD, contract, and the live files needed to verify paths. Do not edit
product code.

## Shape

Write the requested `tasks.json` in one pass against the task schema your instructions name
(standalone: describe the same structure in a file you choose). Set `stack` to the repository
name.

- **Small, verifiable tasks** — about one commit and one testable behavior each, with exact
  reads and writes, a concrete test to write first, the standards it must honor, and whether
  it needs a human gate (migrations, auth/permission, payments, production config,
  dependencies).
- **Slices** — split work into independent slices with disjoint writes; dependencies may only
  point within a slice. Prefer a thin end-to-end slice before breadth.
- **Order** — types and schema → domain logic → persistence → API, UI or entry point → tests →
  logging and metrics → docs. Migrations go expand → migrate → contract, never breaking in one
  step.

## Coverage

The plan as a whole includes tasks for input validation and error responses, the contract's
negative and authorization paths, idempotency and rate limits where required, migration plus
backfill and rollback when the schema changes, every required UI state, observability, and
framework-native verification for this repository's technology. Add characterization tests
before touching untested legacy code, and flag any task that needs a coordinated change in
another repository.

## Validate

Run the validator your instructions name on the file and correct every reported error before
returning. Never return an invalid task file.

## Output contract

Return `task_count` and `slice_count` as short scalar JSON fields on the last line.
