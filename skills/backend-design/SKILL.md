---
name: backend-design
description: Author the backend low-level design (LLD) for a feature — read the relevant backend code to ground the design, then design how the feature slots in — component/sequence design, data model + migration plan, the API/events the backend will expose, error handling, security, observability, and test plan. Writes docs/technical/<slug>/lld/backend.md; never edits app code. Runs in the design phase (parallel with the frontend). Front door for /backend-design.
allowed-tools: Read, Grep, Glob, Bash, Write
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
- **Artifact path** — resolve it yourself from `skills.config.yaml` → `artifacts.lld` with
  `{slug}` = `feature_slug`, i.e. `docs/technical/<slug>/lld/backend.md`. The caller passes no
  path; this skill owns where it writes.

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
Read `skills.config.yaml` → `lld.external.research` (a skill name, e.g. `deep-research`, or
`none`). If set, use it to research unfamiliar libraries, protocols, or compliance — it must
return sourced findings you can cite in the LLD. If `none`, design from the code + HLD.

## Output
Write `docs/technical/<slug>/lld/backend.md` with the sections above, each constraint citing
`file:line`. Return `lld_path` and a short list of the **decisions/constraints that shape the
contract** (e.g. "auth is centralized in X — new endpoints must use it"; "exposes `GET
/searches` with cursor pagination"). The API/events section feeds `/api-contract`.

## Definition of done
Every section present; API surface concrete enough to formalize; migration reversible; edge
cases specified (not "TBD"); breaking changes flagged. Do not implement — that is
`/backend-impl` after the contract is approved.
