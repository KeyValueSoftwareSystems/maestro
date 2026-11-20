---
name: design
description: Work out the technical design for an agreed change — where it lives in the codebase, interfaces, data model, infrastructure, test approach and risks — grounded in the actual code. Use after the direction is agreed and before writing a plan.
---

# Design

Turn an agreed direction into a concrete technical shape that fits the existing codebase.

## Steps

1. **Ground in the code.** Read the project's `CLAUDE.md`/`AGENTS.md` and the modules the change
   touches. Find existing functions, patterns and utilities to reuse; prefer extending them over
   adding new ones.
2. **Place the change.** Name the modules/files (or repositories) that change and what each one
   does in this change. Mark anything new.
3. **Interfaces.** For anything crossing a boundary (API, event, public function, CLI), give the
   exact shape: name/path, inputs and outputs with types, errors, and compatibility with
   existing callers. None → say None.
4. **Data.** Schema or model changes, migrations (expand → migrate → contract, reversible),
   backfills.
5. **Infrastructure.** Config, queues, jobs, deploy changes — or None.
6. **Tests.** What proves it works: main cases and the riskiest negative paths.
7. **Risks.** What could break, and how the design guards against it.

## Rules

- Follow the decisions already agreed; do not reopen them. If one looks wrong, say so to the user
  instead of silently changing it.
- Simplest design that meets the need. No speculative abstractions.
- This skill produces design content for the caller to write down; it does not write files on its
  own unless the caller gives a path.
