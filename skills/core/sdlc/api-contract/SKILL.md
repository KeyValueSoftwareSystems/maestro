---
name: api-contract
description: Define the cross-repository API/event CONTRACT (OpenAPI, or AsyncAPI for events) for every interface an approved HLD lists, following the owning repository's existing API conventions, before the repository LLDs are written. Also applies a narrow requested change to an existing contract. Writes the contract; never edits app code. Front door for /api-contract.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, design, contract]
---

# api-contract — cross-repository contract

The HLD names each interface between repositories: the operation or event, its owner and caller,
sync or async, and the data in words. This skill turns that list into ONE authoritative contract
that every repository's LLD then implements or calls exactly. Written first, it is the single
place a cross-repository change happens. Writes the contract only; no app code and no internal
design.

## Inputs

Your instructions name the approved HLD and the contract path, and in change mode the requested
change. Read the owning repository's codebase map and existing routes, handlers or schemas to
follow its conventions. Standalone? read the HLD the user names and write the contract to a path
you choose (and tell the user where).

## Steps

1. **List** every interface in the HLD's Interfaces section. Define exactly those — never invent an
   operation the HLD does not list.
2. **Follow the owner's conventions** — existing error envelope, naming, auth headers, versioning,
   pagination and ID formats. Do not introduce a new style beside an established one.
3. **Specify each interface completely** (checklist below) and write OpenAPI for HTTP operations;
   AsyncAPI, or an OpenAPI `webhooks`/components section, for events.
4. **Flag breaking changes** to existing operations in plain language, with the migration path.

**Change mode.** When your instructions supply a requested change (for example a field a client
needs), apply only that change, keep every unaffected operation byte-for-byte, and flag it as
breaking or additive.

## Contract standards (specify all of these)

- **Operations** — method/path or event/topic; request and response schemas; status codes.
- **Error shape** — one consistent envelope; which code maps to which failure.
- **Auth and permissions** — scheme and the exact permission required per operation.
- **Validation** — every field: type, required/optional, nullability, format, min/max, enum.
- **Pagination and limits** — page/cursor shape, default and max page size, payload caps.
- **Rate limiting** — limits and the response when exceeded (429 + retry-after).
- **Idempotency** — key semantics for mutating or retryable operations.
- **Concurrency** — optimistic locking, ETag or version fields where updates can race.
- **Versioning and compatibility** — additive by default; breaking changes called out.

## Edge cases the contract must define

Empty, missing or null inputs; oversized payloads; duplicate submissions; pagination boundaries
and ordering; authorization denied, expired token, insufficient scope, cross-tenant attempts;
rate-limit exhaustion; downstream errors surfaced to the client.

## Safety

Write only the contract file. Never edit application code, the HLD or LLDs.

## Output contract

Return `contract_path` and `contract_summary` (one or two sentences: operations defined, breaking
changes flagged) — both short scalars.
