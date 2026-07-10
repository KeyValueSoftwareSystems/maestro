---
name: backend-implement
description: Implement an approved backend scope against the cross-repo contract, test-first, meeting the backend engineering standards (security, backward compatibility, rate limiting, idempotency, migrations, observability, performance). Edits code within the approved scope only. Use only after the contract is approved. Front door for /backend-impl.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write, Task
tags: [sdlc, implement, backend]
---

# backend-implement

Implement the approved backend scope so it satisfies the contract exactly. The backend
**owns** the contract — implement it as published; never silently change it.

## When to use / not use
- **Use** after the contract is approved (and ideally `/backend-tasks` has produced a plan).
- **Don't** start if the contract is unstable, or expand scope beyond what was approved.

## Before editing
1. Read `CLAUDE.md`, `AGENTS.md`, the backend LLD (`.maestro/<slug>/lld/backend.md`),
   and the contract (`.maestro/<slug>/openapi.yaml`) — paths resolve from
   `maestro.config.yaml` → `artifacts.lld_backend` / `artifacts.contract`.
2. Read the task DAG at `artifacts.tasks_backend` (`.maestro/<slug>/backend/tasks.json`)
   if present; otherwise derive the same ordered slices (via `/backend-tasks`).
3. List the files you intend to change.
4. **Stop and ask a human** before DB migrations, auth/permission, payment logic, prod
   config, or dependency upgrades.

## Slice fan-out (owned by this skill)
This skill owns fanning the task DAG out into slices — no orchestrator passes slices or
worktrees in.

1. **Validate first** — run `python3 engine/validate_tasks.py .maestro/<slug>/backend/tasks.json`;
   it must print `OK`. Never build from an invalid tasks.json — fix or regenerate it first.
2. **With the Task tool** (where the harness provides it): spawn one implementer subagent per
   independent slice (`slices[]` group), **at most 3 concurrent**. Each subagent works in its
   own git worktree on branch `maestro/<slug>/backend-<group_id>` — delegate worktree hygiene
   to `maestro.config.yaml` → `external_skills.worktrees` when installed. Each subagent gets
   its slice's tasks + the context manifest and follows the per-slice discipline below. When
   all slices are green, **merge the slice branches into the feature branch** and resolve any
   conflicts (disjoint `writes` across groups should make these rare).
3. **Without the Task tool**: build the slices yourself, sequentially, in dependency order,
   in the current checkout.

Either way, **this skill is accountable for every slice building and testing clean** — a
subagent's claim is not proof; its slice's tests must pass.

Per slice (subagent or inline):
1. **Batch-load context once** — `cat` every path in `context_manifest.read_once` +
   `context_manifest.reference` in a SINGLE call, delimited by `=== <path> ===`. Do not use
   one `Read` per file. This is how the run stays under ~50 SDK calls.
2. **Run the slice in order** — for each `task_id` in the slice's `task_ids` (already
   dependency-ordered), batch-read that task's `reads` delta, then TDD it (write the failing
   `test` → minimal code → refactor) before moving to the next task.
3. **Human gates** — stop and ask before any task with `needs_human_gate: true`.
4. **Stay in scope** — edit only files in the slice's tasks' `writes`; commit the slice on
   its branch.

If no `tasks.json` exists (standalone run), author it first via `/backend-tasks`, then proceed
over its slices as above.

## Steps (per task, test-first)
1. **Write the failing test first** from the contract/acceptance criteria (RED).
2. **Implement the minimum** to pass it (GREEN), in dependency order: types/schema →
   domain/service → persistence → API/controller.
3. **Refactor** with tests green; remove duplication.
4. **Add cross-cutting concerns** for the slice: validation, error mapping, logging/metrics.
5. **Run the targeted check**, then move to the next task. On failure, invoke `/fix`.
6. After all tasks, run full **`/verify`** and address the standards checklist.

## Standards every backend change must satisfy
- **Security** — authorize every operation (never trust the client); validate & bound all
  input; parameterize queries (no injection); encode output; secrets never in code/logs;
  minimize/protect PII; safe deserialization; no SSRF from user-supplied URLs.
- **Backward compatibility** — additive by default; don't remove/rename/retype fields or
  tighten validation without a version + migration; defaults for new fields; old clients keep working.
- **Rate limiting & abuse** — limits/quotas on new endpoints; cap page size & payload size;
  sane timeouts; guard expensive operations; return 429 + retry-after when exceeded.
- **Idempotency & retries** — mutating/retryable operations honor an idempotency key or are
  naturally idempotent; no duplicate side effects on retry.
- **Data & migrations** — expand → migrate → contract; reversible; index new query paths;
  no online long locks / full-table rewrites; backfill existing rows safely.
- **Concurrency** — transactions where needed; prevent lost updates (optimistic version/ETag);
  choose correct isolation; handle races.
- **Observability** — structured logs (no secrets/PII), metrics on new paths, tracing spans,
  and an error taxonomy mapped to the contract's error shape.
- **Performance** — no N+1 or unbounded queries; bound query cost; cache/pool where the LLD says.
- **Error contract** — return the contract's error envelope and correct status codes; never
  leak internals in messages.

## Edge cases to implement and test (not just the happy path)
- Inputs: null / missing / empty / whitespace / max-length / oversized / negative / zero /
  boundary numbers / invalid enum / malformed / duplicate / unicode / injection payloads.
- Auth: unauthenticated, expired token, insufficient scope, cross-tenant access attempt.
- Concurrency: two writers on the same entity; retry after timeout; idempotency-key reuse.
- Failure: downstream dependency down/slow; DB error; partial write; timeout → correct fallback.
- Pagination: first/last/empty page, invalid cursor, unstable ordering.
- Rate limit reached; large result sets; time zones / DST / numeric precision & rounding.

## External skill (provision — the TDD engine)
Read `maestro.config.yaml` → `external_skills.tdd` (default
`test-driven-development`, from the Superpowers pack, or `none`). If set, use it to drive
RED → GREEN → REFACTOR. **Whatever the engine, ensure the tests it produces cover** the
edge cases above and the contract's negative paths — not happy-path only. If `none`,
implement then add unit + integration tests to the same bar.

## Safety
Never run destructive commands (`rm -rf`, force-push, `DROP`/`TRUNCATE TABLE`) or write
prod config/secrets (`.env`, keys) — those are human pre-steps. Nothing auto-blocks this;
you are the backstop.

## Verification
Invoke `/verify` (lint, typecheck, unit + integration, migration check, provider-side
contract validation). On failure invoke `/fix` (one attempt per invocation, bounded overall
by `maestro.config.yaml` → `fix_loop.max_attempts`; delegates to `external_skills.debug`).

## Definition of done (stop condition)
Tests ran and pass; every slice merged; every standards item addressed or explicitly noted;
edge-case tests exist; changed files summarized; remaining risks listed; contract honored
exactly. Passing checks are the proof — not a message that says "done".

## Output contract
Return `branch`, `summary`, `tests_passed`.

When invoked as a Maestro workflow step, your reply's LAST line must be exactly one JSON
object with these fields — short scalar values only, never file contents.
