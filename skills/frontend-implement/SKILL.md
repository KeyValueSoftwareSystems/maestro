---
name: frontend-implement
description: Implement an approved frontend scope by consuming the cross-repo contract exactly, with all required UI states, meeting the frontend engineering standards (accessibility, performance, security, i18n, resilience). Edits code within scope only. Use only after the contract is stable. Front door for /frontend-impl.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write, Task
tags: [sdlc, implement, frontend]
---

# frontend-implement

Implement the approved frontend scope. **Consume** the contract exactly as published —
never invent API shapes. Start only after the contract is stable.

## When to use / not use
- **Use** after the contract is stable (backend need not be finished — mock to the contract).
- **Don't** ship happy-path-only UI; don't invent fields; don't ignore type errors.
- **Plan mode:** if invoked to plan only, produce the task/UI-state list and stop.

## Before editing
1. Read `CLAUDE.md`, the frontend LLD (`.maestro/<slug>/lld/frontend.md`) — reuse the
   components/patterns it identified before adding new ones — and the contract
   (paths resolve from `maestro.config.yaml` → `artifacts.lld_frontend` / `artifacts.contract`).
2. List pages affected, components to reuse/add, API hooks, form schema/validation,
   analytics, and tests. List files to change.

## Slice fan-out (owned by this skill)
This skill owns fanning the task DAG (`artifacts.tasks_frontend`,
`.maestro/<slug>/frontend/tasks.json`) out into slices — no orchestrator passes slices or
worktrees in.

1. **Validate first** — run `python3 engine/validate_tasks.py .maestro/<slug>/frontend/tasks.json`;
   it must print `OK`. Never build from an invalid tasks.json — fix or regenerate it first.
2. **With the Task tool** (where the harness provides it): spawn one implementer subagent per
   independent slice (`slices[]` group), **at most 3 concurrent**. Each subagent works in its
   own git worktree on branch `maestro/<slug>/frontend-<group_id>` — delegate worktree hygiene
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
   `context_manifest.reference` in a SINGLE call, delimited by `=== <path> ===` (not one
   `Read` per file). Keeps the run under ~50 SDK calls.
2. **Run the slice in order** — for each `task_id` in the slice's `task_ids`, batch-read its
   `reads` delta, then build test-first, wiring every required UI state for that task.
3. **Human gates** — stop and ask before any task with `needs_human_gate: true`.
4. **Stay in scope** — edit only files in the slice's tasks' `writes`; commit the slice on
   its branch.

This is distinct from **Plan mode** (produce the task/UI-state list and stop). If no
`tasks.json` exists (standalone run), author it first (plan mode), then proceed over its
slices as above.

### Plan mode / fallback authoring (emit tasks.json)
This is the **fallback** author: the design phase normally emits `tasks.json` via
`/frontend-design`. Run this only when `.maestro/<slug>/frontend/tasks.json` is absent (e.g. a
standalone `/frontend-impl` run with no design phase, or when invoked in plan mode).

When invoked in plan mode with no `tasks.json` present, write
`.maestro/<slug>/frontend/tasks.json` conforming to `engine/schemas/tasks.schema.json`:
`context_manifest` (batched-read files), `tasks[]` (`id`, `group_id`, `title`, `depends_on`
intra-group only, `reads`, `writes`, `test`, `standards`, `needs_human_gate`), and `slices[]`
(one entry per independent group — two tasks share a group iff one depends on the other OR
they write a common file). Validate with
`python3 engine/validate_tasks.py .maestro/<slug>/frontend/tasks.json` (must print `OK`).
Return `tasks_path`, `slices`.

## Steps
1. **Types/API client** from the contract (generate or hand-write; single source of truth).
2. **State & data-fetching** via the existing layer; define cache keys & invalidation.
3. **Component/page** — build the happy path, then wire **every required UI state**.
4. **Form validation** mirroring the contract's rules; inline field errors.
5. **Error handling & resilience** — retries, messaging, optimistic-update rollback.
6. **Accessibility & i18n** pass.
7. **Tests** — component + the critical E2E flow; then Storybook if present.
8. Run `/verify`; on failure `/fix`.

## Required UI states (build AND test each)
loading · empty · success · validation error · API error · permission denied ·
retry / failed operation.

## Standards every frontend change must satisfy
- **Accessibility (WCAG AA)** — keyboard operable, visible focus, correct roles/labels,
  color contrast, screen-reader semantics, no keyboard traps, focus management on route/modal.
- **All UI states** — the seven above, each designed and tested.
- **Performance** — code-split heavy routes, lazy-load, memoize to avoid needless
  re-renders, watch bundle size, virtualize large lists.
- **Security** — no secrets/tokens in client code; escape/encode to prevent XSS; CSRF-safe
  requests; validate redirects/deep links; no PII in logs/analytics.
- **Resilience** — handle slow/failed/stale APIs with retry/backoff + clear messaging;
  optimistic updates roll back on failure; guard against double-submit.
- **Forms & validation** — mirror the contract; field-level errors; disable submit while pending.
- **Responsive & mobile** — works across breakpoints; long text/overflow; touch targets.
- **i18n/l10n** — user-facing strings localizable; locale-aware dates/numbers; RTL if supported.
- **Analytics** — emit the spec's events without leaking PII.

## Edge cases to handle and test
- Empty datasets; single vs many items; very long names/text; missing/broken images.
- Slow network, offline, request cancelled, race between rapid actions, stale cache.
- API 4xx/5xx, validation errors mapped to fields, permission denied, session expiry.
- Double-click / double-submit; back/forward navigation mid-flow; deep-link to a guarded page.
- Timezone/locale/number formatting; RTL layout; reduced-motion / high-contrast prefs.
- Large lists (virtualization); pagination first/last/empty; unstable ordering.

## External skill (provision — the TDD engine)
Read `maestro.config.yaml` → `external_skills.tdd` (a skill name or `none`). If set, drive
component work test-first; the tests must still cover the UI states and edge cases above. If
`none`, implement then test to that bar. Run the accessibility pass yourself either way — it
must cover keyboard, focus, roles/labels, and contrast (axe/WCAG-AA).

## Safety
Never run destructive commands or write prod config/secrets. Stop and ask a human before
auth/permission, prod config, or dependency changes. Nothing auto-blocks this; you are the
backstop.

## Verification
Invoke `/verify` (lint, typecheck, unit/component, build, Playwright E2E, a11y basics). On
failure invoke `/fix` (one attempt per invocation, bounded overall by
`maestro.config.yaml` → `fix_loop.max_attempts`).

## Definition of done
All required UI states built and tested; every slice merged; standards addressed; edge cases
handled; no TypeScript errors; reuses existing components; contract consumed exactly.

## Output contract
Return `branch`, `summary`, `tests_passed`. In plan mode, return `tasks_path` and `slices`
instead.

When invoked as a Maestro workflow step, your reply's LAST line must be exactly one JSON
object with these fields — short scalar values only, never file contents.
