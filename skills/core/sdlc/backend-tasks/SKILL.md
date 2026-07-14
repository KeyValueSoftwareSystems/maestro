---
name: backend-tasks
description: Split an approved backend scope + contract into a small, ordered, test-first task list with a verification step per task and risk flags. Read-only planning — never edits code.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, plan, backend]
---

# backend-tasks

Break the approved backend scope into the **smallest ordered set of verifiable tasks** that
implement the contract. Small tasks keep the implement→verify→fix loop tight and every
change reviewable. Read-only — produces a task list, not code.

## Inputs
Your instructions name what to read — the cross-repo contract and the backend LLD — and the
artifact path to write. Standalone? read them and write to a path you choose (and tell the user where).

## Steps
1. **Read** the contract and the backend LLD (the inputs your instructions point to); read
   the target service's structure read-only.
2. **Slice vertically** where possible — a thin end-to-end slice (schema→API→test) before
   breadth, so value is demonstrable early.
3. **Order by dependency** — types/schema → domain/service logic → persistence →
   API/controller → tests → logging/metrics → docs. Sequence migrations
   **expand → migrate → contract**; never a breaking migration in one step.
4. **Make each task small** — ~one commit, one testable behavior, exact files.
5. **Attach a test + standards + risk** to every task (below).
6. **Write** the task list artifact.

## Each task must specify
- `id`, `title`, and the **exact files** it touches.
- `test` — the check that proves it (the failing test to write first).
- `standards` — which of {security, backward-compat, rate-limiting, idempotency,
  validation, observability, migrations, performance} this task must honor.
- `needs_human_gate` — true if it touches DB migration, auth/permission, payment, prod
  config, or dependencies.

## Coverage — the plan as a whole must include tasks for
- Input validation (all fields, bounds, formats) and the error responses.
- The negative/authz paths from the contract, not just the happy path.
- Idempotency & rate limiting where the contract requires them.
- Migration + **backfill** of existing data (+ a rollback task) when the schema changes.
- Observability (logs/metrics/traces) and docs.
- A **feature-flag** task if the HLD calls for gated rollout.

## Edge cases to plan for explicitly
- Tasks touching shared/legacy code with no tests (add characterization tests first).
- Migrations needing online/zero-downtime handling or large backfills.
- Tasks that require a coordinated frontend/contract change (flag the dependency).
- Concurrency-sensitive writes (add a locking/versioning task).

## External skill (provision — planner)
If the `writing-plans` skill (from the Superpowers pack) is installed, use it to produce
bite-sized, verifiable tasks — each task must still carry files + test + standards + risk as
above. If it is not installed, plan in-pack.

## Output
**Author it in one shot, then refine once** — compose the whole tasks.json (manifest, all
`tasks[]`, `slices[]`) in a single `Write`; do not stub-and-grow it with successive `Edit`s.
Validate once; if it fails, make one corrective edit and re-validate (repeat only to fix
validation errors, never to build the file up incrementally).

Write the DAG to the tasks.json path your instructions specify (the orchestrator passes it;
run standalone? use a sensible path you choose) conforming to
`engine/schemas/tasks.schema.json` (the same shape the design step emits): `context_manifest`
(batched-read files), `tasks[]` (`id`, `group_id`, `title`, `depends_on` intra-group only,
`reads`, `writes`, `test`, `standards`, `needs_human_gate`), and `slices[]` (one per
independent group — two tasks share a group iff one depends on the other or they write a
common file). Validate with
`python3 engine/validate_tasks.py <the tasks.json path>` (must print `OK`).

## Definition of done
Every task ≤ ~1 commit, has a test and standards, and is dependency-ordered; migrations are
expand/contract with rollback; negative paths and observability are represented; risky tasks
are flagged; tasks.json validates against the schema (no cross-group edges, disjoint writes across groups).

## Output contract
Return `tasks_path`, `task_count` (integer), `slice_count` (integer), and `risky`
(true if any task needs a human gate) — all short scalars.
