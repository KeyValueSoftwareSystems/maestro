---
name: api-contract
description: Generate the cross-repo API/event CONTRACT (OpenAPI) by reconciling the per-stack LLDs — the backend LLD (what it exposes) and the frontend LLD (what it consumes) — into the single boundary both build against. Also derives acceptance criteria and the affected stacks. Reads the LLDs; writes the contract; never edits app code. Front door for /api-contract.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, design, contract]
---

# api-contract — cross-repo contract generation

The per-stack LLDs each describe one side of the boundary: the **backend LLD** says what it
will *expose*; the **frontend LLD** says what it needs to *consume*. This skill reconciles
them into ONE authoritative **contract** (OpenAPI) that the backend implements and the
frontend consumes — the boundary that lets each side build and verify alone. Writes the
contract + acceptance criteria only; no app code. Don't design internals (that's the LLDs) or
implement, and don't invent operations neither LLD calls for.

## Inputs
Your instructions name the concrete files to read — the backend and frontend LLDs, plus the
HLD if one exists — and the artifact path(s) to write. Standalone? read the LLDs and write the
contract to a path you choose (and tell the user where).

## Steps
1. **Read** the LLDs and HLD your instructions point to, plus any existing contract at the target path.
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
If a suitable deep-research skill is installed you may delegate to it to research a
protocol/standard the contract must follow. Otherwise work from the LLDs.

## Output — write these artifacts
Write the artifacts to the paths your instructions specify:
- the contract, OpenAPI (source of truth).
- acceptance criteria — what QA automates (include negative paths).

## Definition of done
Contract covers every item above (no undefined fields/errors); backend-exposed and
frontend-consumed APIs reconciled (no silent mismatch); acceptance criteria include negative
paths. End with the human contract-approval ask; do not implement.

## Output contract
Return `contract_path`, `contract_summary` (breaking changes flagged) — both short
scalars. The affected repos and acceptance criteria belong IN the artifacts, not the JSON
line; never return arrays or objects.
