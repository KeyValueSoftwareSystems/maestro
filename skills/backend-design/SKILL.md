---
name: backend-design
description: Author the backend low-level design (LLD) for a feature — read the relevant backend code to ground the design, then design how the feature slots in — component/sequence design, data model + migration plan, the API/events the backend will expose, error handling, security, observability, and test plan. Writes .maestro/<slug>/lld/backend.md; never edits app code. Runs in the design phase (parallel with the frontend). Front door for /backend-design.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, design, lld, backend]
---

# backend-design — backend low-level design

Design the **backend** for a feature: read enough of the existing code to ground the design
in real conventions, then write a **buildable backend LLD**. This is a design artifact, not
code — never edit app code. Accuracy over breadth: cite `file:line` for every constraint you
rely on; don't guess.

## When to use / not use
- **Use** in the design phase, after the HLD is approved, in parallel with the frontend LLD.
- **Don't** implement, and don't design the frontend. The **cross-repo contract** is not
  written here — you describe the API/events your stack will **expose**, and `/api-contract`
  reconciles the two LLDs into the formal OpenAPI contract afterward.

## Inputs
- `feature`, `feature_slug`, approved `hld_path`.
- **Artifact path** — you write `.maestro/<slug>/lld/backend.md`, with `<slug>` =
  `feature_slug`. The caller passes no path; this skill owns where it writes.

## Steps
1. **Ground in the code (read-only).** Locate the service(s) this feature touches and read
   the layers that matter — routing/controllers → services/domain → persistence; the data
   model and migration tool; existing endpoints/events, DTOs, error envelope, auth/roles,
   jobs/queues, external integrations, rate-limit/idempotency patterns, logging/metrics,
   tests/fixtures, and the dominant conventions. Capture only what constrains the design,
   with `file:line` evidence. (No separate map is produced — this understanding feeds the LLD.)
2. **Component & sequence design** — the modules/objects, their responsibilities, and the
   call/sequence for each critical path (happy + main error paths); where new code slots in.
3. **Data model & migration plan** — entities, relations, indexes; a concrete
   **expand → migrate → contract** plan with rollback and any backfill of existing rows.
4. **API/events to EXPOSE** — the operations this backend will offer (your side of the
   contract): method/path or event/topic, request/response DTOs, status codes, error
   envelope, auth + the exact permission per operation, per-field validation, pagination &
   limits, rate limits (429 + retry-after), idempotency keys, concurrency/versioning,
   backward-compatibility. `/api-contract` formalizes this into OpenAPI.
5. **Threat-model** the change (authz per operation, data exposure, abuse); design
   **observability** (logs/metrics/traces for new paths), timeouts/retries/degradation, and
   **performance** considerations.
6. **Test plan** — unit + integration coverage, including the contract's negative paths.
7. **Write** the backend LLD; flag every breaking change in plain language.
8. **Emit the task DAG** — write `.maestro/<slug>/backend/tasks.json` (see section below),
   reusing the code you already read. No re-reading.

## What the backend LLD must cover (write all)
Context & constraints (grounded in the code, cited) · component/sequence design · data model
+ migration plan · API/events exposed (the backend's side of the contract) · error handling ·
security & privacy (authz, tenancy, PII, secrets handling) · observability · performance ·
reliability (timeouts, retries, idempotency, partial-failure) · test plan · rollout/backout.

## Edge cases the design must define (not leave to the implementer)
- Empty / missing / null inputs; maximum-size and oversized payloads; duplicate submissions.
- Concurrent updates to the same entity; lost-update prevention.
- Partial failure across services; retries and idempotency; timeouts and their fallbacks.
- Pagination boundaries (first/last/empty page, unstable ordering).
- Authz denied, expired token, insufficient scope, cross-tenant access attempts.
- Rate-limit exhaustion; downstream dependency down or slow.
- Migration failure mid-way; backfill of large existing datasets; rollback safety.
- Monorepo vs multi-repo; generated code; vendored/legacy areas; areas with **no tests**.

## External skill (provision — research)
If a suitable deep-research skill is installed you may delegate to it to research unfamiliar
libraries, protocols, or compliance — it must return sourced findings you can cite in the
LLD. Otherwise design from the code + HLD.

## Emit tasks.json (the parallel task DAG)
Write `.maestro/<slug>/backend/tasks.json` conforming to `engine/schemas/tasks.schema.json`. It is
the plan the backend impl phase fans out over — build it from the LLD you just wrote, reusing
the files you already read (do not re-read the codebase).

**Author it in one shot, then refine once.** Compose the entire tasks.json — manifest, every
`tasks[]` entry, and `slices[]` — in a single `Write`. Do **not** stub the file and grow it with
successive `Edit`s; assemble the whole structure in memory first and emit it once. After the
one `Write`, run the validator (below): if it prints `OK` you are done; if it fails, make **one**
corrective `Edit` (or a single rewriting `Write`) and re-validate. If that still fails, fix and
re-validate as needed — but never build the file up incrementally.

Fields:
- `context_manifest.read_once` = the code files the tasks edit against; `reference` = this LLD
  path, the (pending) contract path, and `CLAUDE.md`/`AGENTS.md`.
- One `tasks[]` entry per ≤1-commit slice, each with `id`, `group_id`, `title`, `depends_on`
  (**intra-group only**), `reads` (files needed beyond the manifest), `writes` (exact files),
  `test` (the failing test to write first), `standards`, `needs_human_gate` (true for DB
  migration, auth/permission, payment, prod config, or dependency changes).
- **Grouping into independent slices:** two tasks share a `group_id` **iff** one depends on
  the other OR they write a common file; otherwise put them in different groups. Then fill
  `slices[]` — one entry per group, `task_ids` in dependency order.
- **Validate before returning:** run
  `python3 engine/validate_tasks.py .maestro/<slug>/backend/tasks.json` — it must print `OK`.
  Fix any `FAIL` (cross-group edge, shared write, mis-ordered slice) before finishing.

## Output contract
Write `.maestro/<slug>/lld/backend.md` with the sections above, each constraint citing
`file:line`. Return `lld_path`, `tasks_path` (`.maestro/<slug>/backend/tasks.json`), and
`contract_notes` — a short summary of the **decisions/constraints that shape the contract**
(e.g. "auth is centralized in X — new endpoints must use it"; "exposes `GET /searches` with
cursor pagination"). The API/events section feeds `/api-contract`.

When invoked as a Maestro workflow step, your reply's LAST line must be exactly one JSON
object with these fields — short scalar values only, never file contents.

## Definition of done
Every section present; API surface concrete enough to formalize; migration reversible; edge
cases specified (not "TBD"); breaking changes flagged. Do not implement — that is
`/backend-impl` after the contract is approved.
