---
name: api-contract
description: Generate the cross-repo API/event CONTRACT (OpenAPI) by reconciling the per-stack LLDs — the backend LLD (what it exposes) and the frontend LLD (what it consumes) — into the single boundary both build against. Also derives acceptance criteria and the affected stacks. Reads the LLDs; writes the contract; never edits app code. Runs after the per-stack LLDs and before implementation. Front door for /api-contract.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, design, contract]
---

# api-contract — cross-repo contract generation

The per-stack LLDs each describe one side of the boundary: the **backend LLD** says what it
will *expose*; the **frontend LLD** says what it needs to *consume*. This skill reconciles
them into ONE authoritative **contract** (OpenAPI) that the backend implements and the
frontend consumes — the boundary that lets each side build and verify alone. Writes the
contract + acceptance criteria only; no app code.

## When to use / not use
- **Use** once both per-stack LLDs exist (`.maestro/<slug>/lld/backend.md` and
  `.../frontend.md`). Runs after the design phase, before implementation.
- **Don't** design internals (that's the LLDs) or implement. Don't invent operations neither
  LLD calls for.

## Inputs
- `feature`, `feature_slug`, optional `hld_path`.
- `backend_lld`, `frontend_lld` — the two per-stack LLD paths.
- **Artifact paths** — resolve from `maestro.config.yaml` → `artifacts.contract` and
  `artifacts.acceptance` with `<slug>` = `feature_slug` (`.maestro/<slug>/openapi.yaml`,
  `.maestro/<slug>/acceptance-criteria.md`). The caller passes no paths; this skill owns
  where it writes.

## Steps
1. **Read** both LLDs, any existing `.maestro/<slug>/openapi.yaml`, and the acceptance intent in the HLD.
2. **Reconcile** the backend's *exposed* API against the frontend's *consumed* API. Where
   they disagree (shape, field, pagination, error), resolve it explicitly — the contract is
   the source of truth — and note which side must adjust its LLD/implementation.
3. **Specify the contract precisely** (checklist below) and write it as OpenAPI.
4. **Acceptance criteria** — the checks QA will automate; cover negative paths.
5. **Determine `affected_repos`** from which LLDs exist / which stacks the contract touches.
6. **Write** the contract + acceptance criteria; flag every breaking change in plain language.

## Contract standards (specify ALL of these)
- **Operations** — method/path or event/topic; request & response DTOs; status codes.
- **Error shape** — one consistent envelope; which code maps to which failure.
- **Auth & permissions** — scheme + the exact permission required per operation.
- **Validation** — every field: type, required/optional, format, min/max, enum.
- **Pagination & limits** — page/cursor shape, default & max page size, payload/size caps.
- **Rate limiting** — limits/quotas and the response when exceeded (429 + retry-after).
- **Idempotency** — idempotency key semantics for mutating/retryable operations.
- **Concurrency** — optimistic locking / ETag / version fields where updates can race.
- **Versioning & backward compatibility** — additive by default; call out breaking changes
  and the migration/deprecation path.

## Edge cases the contract must define
- Empty / missing / null inputs; oversized payloads; duplicate submissions.
- Pagination boundaries; unstable ordering.
- Authz denied, expired token, insufficient scope, cross-tenant attempts.
- Rate-limit exhaustion; downstream dependency errors surfaced to the client.
- A field the frontend needs but the backend LLD doesn't expose (or vice-versa) — resolve, don't paper over.

## External skill (provision — research)
Read `maestro.config.yaml` → `external_skills.research` (a skill name, e.g. `deep-research`, or
`none`). If set, use it to research a protocol/standard the contract must follow. If `none`,
work from the LLDs.

## Output — write these artifacts
- `.maestro/<slug>/openapi.yaml` — the contract (source of truth).
- `.maestro/<slug>/acceptance-criteria.md` — what QA automates (include negative paths).

## Definition of done
Contract covers every item above (no undefined fields/errors); backend-exposed and
frontend-consumed APIs reconciled (no silent mismatch); acceptance criteria include negative
paths. End with the human contract-approval ask; do not implement.

## Output contract
Return `contract_path`, `contract_summary` (breaking changes flagged), `affected_repos`
(objects with `name` exactly `backend`/`frontend`), and `acceptance_criteria`.

When invoked as a Maestro workflow step, your reply's LAST line must be exactly one JSON
object with these fields — short scalar values only, never file contents.
