---
name: frontend-design
description: Author the frontend low-level design (LLD) for a feature — read the relevant frontend code to ground the design, then design component/state architecture, routing, the full UI-state matrix, the API it needs to consume, accessibility, performance, i18n, and tests. Writes docs/technical/<slug>/lld/frontend.md; never edits app code. Runs in the design phase (parallel with the backend). Front door for /frontend-design.
allowed-tools: Read, Grep, Glob, Bash, Write
---

# frontend-design — frontend low-level design

Design the **frontend** for a feature: read enough of the existing UI to ground the design in
real components and patterns, then write a **buildable frontend LLD**. Design artifact, not
code — never edit app code. Prefer reuse over reinvention; cite `file:line` for constraints.

## When to use / not use
- **Use** in the design phase, after the HLD is approved, in parallel with the backend LLD.
- **Don't** implement, and don't design the backend. The **cross-repo contract** is not
  written here — you describe the API/data your UI needs to **consume**, and `/api-contract`
  reconciles the two LLDs into the formal OpenAPI contract afterward.

## Inputs
- `feature`, `feature_slug`, approved `hld_path`.
- **Artifact path** — resolve it yourself from `skills.config.yaml` → `artifacts.lld` with
  `{slug}` = `feature_slug`, i.e. `docs/technical/<slug>/lld/frontend.md`. The caller passes
  no path; this skill owns where it writes.

## Steps
1. **Ground in the code (read-only).** Locate the app(s)/routes this feature touches and read
   what matters — routing/pages, the component library/design system, state & data-fetching
   layer (store, cache/invalidation, the API client/hooks), forms/validation approach, the
   existing loading/empty/error/permission UI-state patterns, accessibility conventions,
   i18n, and the component/E2E test setup. Capture only what constrains the design, with
   `file:line` evidence. (No separate map is produced — this feeds the LLD.)
2. **Component & state design** — the component hierarchy and responsibilities, where screens
   attach in routing, the state model, data-fetching + cache keys/invalidation, and the form
   schema/validation (parity with backend rules).
3. **UI-state matrix** — for each view, define **every** state: loading, empty, success,
   partial, error/retry, permission-denied, and offline/slow-network where relevant.
4. **API to CONSUME** — the endpoints/events and response shapes the UI expects (your side of
   the contract). `/api-contract` reconciles this with the backend's exposed API.
5. **Accessibility strategy** (keyboard, focus, roles/labels, contrast — WCAG AA),
   **performance** (bundle/render, code-splitting on heavy routes), **security** (XSS/CSRF,
   authz in the UI, no secrets in the client), **i18n**, and **resilience** (error boundaries,
   optimistic UI + rollback).
6. **Test plan** — component + E2E coverage, including the negative UI states.
7. **Write** the frontend LLD; flag anything that forces a backend/contract change.
8. **Emit the task DAG** — write `.sdlc/<slug>/frontend/tasks.json` (see section below),
   reusing the code you already read. No re-reading.

## What the frontend LLD must cover (write all)
Context & constraints (grounded in the code, cited) · component & state design · routing ·
data-fetching + caching · forms & validation · **UI-state matrix** · API consumed (the
frontend's side of the contract) · accessibility · performance · security · i18n ·
resilience · test plan.

## Edge cases the design must define (not leave to the implementer)
- Views with no existing loading/empty/error state to copy; long lists / virtualization.
- Concurrent edits / stale data; optimistic update failure and rollback.
- Slow or failed API calls; partial data; pagination boundaries (first/last/empty page).
- Permission-gated UI; expired session mid-flow.
- Unicode / locale / timezone / RTL; large form validation; accessibility of dynamic content.
- Bundle-size-sensitive routes; areas with no tests; heavy/legacy components.

## External skill (provision — research)
Read `skills.config.yaml` → `lld.external.research` (a skill name, e.g. `deep-research`, or
`none`). If set, use it to research unfamiliar libraries or patterns — it must return sourced
findings you can cite in the LLD. If `none`, design from the code + HLD.

## Emit tasks.json (the parallel task DAG)
Write `.sdlc/<slug>/frontend/tasks.json` conforming to `workflows/tasks.schema.json`. Build it
from the LLD you just wrote, reusing files you already read (do not re-read the codebase):
- `context_manifest.read_once` = the component/state/hook files the tasks edit against;
  `reference` = this LLD path, the (pending) contract path, and `CLAUDE.md`.
- One `tasks[]` entry per ≤1-commit slice (e.g. types/API-client, a component + its UI states,
  form+validation, a route), each with `id`, `group_id`, `title`, `depends_on`
  (**intra-group only**), `reads`, `writes` (exact files), `test`, `standards`,
  `needs_human_gate` (true for auth/permission, prod config, or dependency changes).
- **Grouping:** two tasks share a `group_id` **iff** one depends on the other OR they write a
  common file; otherwise different groups. Fill `slices[]`, `task_ids` in dependency order.
- **Validate before returning:** `python3 workflows/validate_tasks.py .sdlc/<slug>/frontend/tasks.json`
  must print `OK`.

## Output
`file:line`. Return `lld_path`, `tasks_path` (`.sdlc/<slug>/frontend/tasks.json`), and a short
list of the **decisions/constraints that shape the contract** (e.g. "data-fetching goes through hook X — reuse it"; "needs `GET /searches`
returning `{items, nextCursor}`"). The API-consumed section feeds `/api-contract`.

## Definition of done
Every section present; UI-state matrix complete (no state omitted); API-consumed concrete
enough to formalize; edge cases specified (not "TBD"). Do not implement — that is
`/frontend-impl` after the contract is approved.
