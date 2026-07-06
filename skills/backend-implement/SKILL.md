---
name: backend-implement
description: Implement an approved backend scope against the cross-repo contract, test-first, meeting the backend engineering standards (security, backward compatibility, rate limiting, idempotency, migrations, observability, performance). Edits code within the approved scope only. Use only after the contract is approved. Front door for /backend-impl.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write
---

# backend-implement

Implement the approved backend scope so it satisfies the contract exactly. The backend
**owns** the contract — implement it as published; never silently change it.

## When to use / not use
- **Use** after the contract is approved (and ideally `/backend-tasks` has produced a plan).
- **Don't** start if the contract is unstable, or expand scope beyond what was approved.

## Before editing
1. Read `CLAUDE.md`, `AGENTS.md`, the backend LLD (`docs/technical/<slug>/lld/backend.md`),
   and the contract (`contracts/<slug>/openapi.yaml`).
2. Read the `/backend-tasks` plan if present; otherwise derive the same ordered slices.
3. List the files you intend to change.
4. **Stop and ask a human** before DB migrations, auth/permission, payment logic, prod
   config, or dependency upgrades.

## Slice execution (one invocation per slice, from the impl `for_each`)
When called with a `group_id` and `tasks_path`, implement **only that slice**:
1. **Batch-load context once** — `cat` every path in `context_manifest.read_once` +
   `context_manifest.reference` in a SINGLE call, delimited by `=== <path> ===`. Do not use
   one `Read` per file. This is how the run stays under ~50 SDK calls.
2. **Run the slice in order** — for each `task_id` in the slice's `task_ids` (already
   dependency-ordered), batch-read that task's `reads` delta, then TDD it (write the failing
   `test` → minimal code → refactor) before moving to the next task.
3. **Human gates** — stop and ask before any task with `needs_human_gate: true`.
4. **Stay in scope** — edit only files in the slice's tasks' `writes`. Work in the worktree
   the `for_each` item provides; commit the slice on its worktree branch.

If no `tasks.json` exists (standalone run), author it first via `/backend-tasks`, then proceed
over its slices sequentially in this one session.

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
Read `skills.config.yaml` → `backend.external.tdd` (default
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
contract validation). On failure invoke `/fix` (bounded to 3; delegates to
`shared.external.debug`).

## Definition of done (stop condition)
Tests ran and pass; every standards item addressed or explicitly noted; edge-case tests
exist; changed files summarized; remaining risks listed; contract honored exactly. Passing
checks are the proof — not a message that says "done". Outputs: `branch`, `summary`,
`tests_passed`. In slice mode, also return `worktree` and `tasks_done` (the ids implemented).
