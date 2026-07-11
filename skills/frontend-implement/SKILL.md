---
name: frontend-implement
description: Implement an approved frontend scope by consuming the cross-repo contract exactly, with all required UI states, meeting the frontend engineering standards (accessibility, performance, security, i18n, resilience). Edits code within scope only. Use only after the contract is stable. Front door for /frontend-impl.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write
---

# frontend-implement

Implement the approved frontend scope. **Consume** the contract exactly as published —
never invent API shapes. Start only after the contract is stable.

## When to use / not use
- **Use** after the contract is stable (backend need not be finished — mock to the contract).
- **Don't** ship happy-path-only UI; don't invent fields; don't ignore type errors.
- **Plan mode:** if invoked to plan only, produce the task/UI-state list and stop.

## Consuming Tech Stack Decisions

Before implementing, read `.maestro/<slug>/lld/frontend.md` → **"Tech Stack Decisions"** section.
The design phase has already chosen:

- **State management** library & store structure
- **Data-fetching & caching** approach (library, cache strategy, pagination)
- **Styling & design tokens** approach (Tailwind? CSS Modules? styled-components?)
- **Testing frameworks** (unit, component, E2E, mocking)
- **Form validation** library & schema approach
- **API client** generation strategy (generated from OpenAPI? hand-written?)
- **Error tracking & logging** tool (Sentry? LogRocket? none?)
- **Analytics** tool & events to track
- **Build & bundling** approach (Next.js? Vite? Webpack?)
- **Performance targets** (Lighthouse scores, Core Web Vitals, bundle size)
- **Accessibility testing** approach (automated? manual? WCAG level?)
- **i18n & localization** (languages, library, RTL support)
- **Authentication & authorization** method (JWT? Sessions? Token storage?)
- **Platform-specific considerations** (web only? React Native? Flutter?)

**Do not deviate from these decisions.** If a choice seems suboptimal, escalate to the designer
before implementing — don't improvise or substitute a different library mid-feature.

## Tech Stack Setup Checklist

Complete these **before** implementing features. These are blocking setup tasks, not feature work.

### State Management
- [ ] Store structure created or confirmed from design
- [ ] Async middleware/effects setup (thunks, sagas, effects, or equivalent)
- [ ] Selector/getter patterns defined and tested
- [ ] Store connected to app root
- [ ] DevTools integrated (Redux DevTools, Zustand dev tools, etc.)

### Data-Fetching & Caching
- [ ] API client created or generated from contract
- [ ] Cache keys naming convention established
- [ ] Cache invalidation strategy implemented
- [ ] Retry/backoff logic configured
- [ ] Query/data hooks wired and exported
- [ ] Race condition handling (AbortController, request deduplication)

### Styling & Design Tokens
- [ ] Design token files created and imported
- [ ] Theme provider setup (if using CSS-in-JS or theme system)
- [ ] Dark mode toggle tested (if supported)
- [ ] Responsive breakpoints confirmed in config
- [ ] Component styling patterns established (how to apply styles to components)

### Testing Infrastructure
- [ ] Unit test runner configured (Jest, Vitest)
- [ ] Component testing library setup (React Testing Library)
- [ ] E2E framework initialized (Playwright, Cypress, WebdriverIO)
- [ ] API mocking setup (MSW, Mirage, Prism, or similar)
- [ ] Fixture/factory library for mock data
- [ ] Test utilities (custom render, test helpers) created

### Form Validation
- [ ] Validation library installed (react-hook-form, Formik, etc.)
- [ ] Validation schema created matching contract
- [ ] Form submission handler pattern established
- [ ] Async validation (if any) tested
- [ ] Error message display pattern confirmed

### API Client & Types
- [ ] If generating: generator run, types synced, verified in strict mode
- [ ] If hand-written: client file structure created, types documented
- [ ] Request interceptors in place (auth token injection, request logging)
- [ ] Response interceptors in place (error handling, logging)
- [ ] TypeScript strict mode verified (no `any`, no `@ts-ignore`)

### Build & Environment
- [ ] Build tool configured (.env.local strategy, build cache)
- [ ] Code-splitting points confirmed (which routes lazy-load)
- [ ] Feature flags initialized (if used)
- [ ] Environment variables documented and injected
- [ ] Build output validated (bundle size vs. targets)

### Error Handling & Logging
- [ ] Error tracking service initialized (if used)
- [ ] Error boundaries placed at designed points
- [ ] PII scrubbing configured in logger
- [ ] Error capture tested (throw and verify it's logged)
- [ ] User-facing error messages reviewed

### Analytics & Events
- [ ] Analytics library initialized (if used)
- [ ] Event tracking helper/wrapper created
- [ ] Event structure and naming convention documented
- [ ] Test event captured and verified in analytics dashboard
- [ ] PII handling verified (no user emails, phone numbers, etc. in events)

---

**Do not start feature implementation until ALL setup tasks are complete.** They unblock everything else.

## Before editing
1. Read `CLAUDE.md`, the frontend LLD (`.maestro/<slug>/lld/frontend.md`) — reuse the
   components/patterns it identified before adding new ones — and the contract.
2. List pages affected, components to reuse/add, API hooks, form schema/validation,
   analytics, and tests. List files to change.

## Slice execution (one invocation per slice, from the impl `for_each`)
When called with a `group_id` and `tasks_path`, implement **only that slice**:
1. **Batch-load context once** — `cat` every path in `context_manifest.read_once` +
   `context_manifest.reference` in a SINGLE call, delimited by `=== <path> ===` (not one
   `Read` per file). Keeps the run under ~50 SDK calls.
2. **Run the slice in order** — for each `task_id` in the slice's `task_ids`, batch-read its
   `reads` delta, then build test-first, wiring every required UI state for that task.
3. **Human gates** — stop and ask before any task with `needs_human_gate: true`.
4. **Stay in scope** — edit only files in the slice's tasks' `writes`, in the worktree the
   `for_each` item provides; commit the slice on its worktree branch.

This is distinct from **Plan mode** (produce the task/UI-state list and stop). If no
`tasks.json` exists (standalone run), author it first (plan mode), then proceed over its
slices sequentially in this one session.

### Plan mode / fallback authoring (emit tasks.json)
This is the **fallback** author: the design phase normally emits `tasks.json` via
`/frontend-design`. Run this only when `.maestro/<slug>/frontend/tasks.json` is absent (e.g. a
standalone `/frontend-impl` run with no design phase, or when invoked in plan mode).

When invoked in plan mode with no `tasks.json` present, write
`.maestro/<slug>/frontend/tasks.json` conforming to `workflows/tasks.schema.json`:
`context_manifest` (batched-read files), `tasks[]` (`id`, `group_id`, `title`, `depends_on`
intra-group only, `reads`, `writes`, `test`, `standards`, `needs_human_gate`), and `slices[]`
(one entry per independent group — two tasks share a group iff one depends on the other OR
they write a common file). Validate with
`python3 workflows/validate_tasks.py .maestro/<slug>/frontend/tasks.json` (must print `OK`).
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

## External skills (provision)
Read `skills.config.yaml` → `frontend.external`:
- `tdd` (a skill name or `none`) — if set, drive component work test-first; the tests must
  still cover the UI states and edge cases above. If `none`, implement then test to that bar.
- `a11y` (a skill name or `none`) — if set, run the accessibility pass via it; it must cover
  keyboard, focus, roles/labels, and contrast. If `none`, use the in-pack axe/WCAG-AA check.

## Safety
Never run destructive commands or write prod config/secrets. Stop and ask a human before
auth/permission, prod config, or dependency changes. Nothing auto-blocks this; you are the
backstop.

## Verification
Invoke `/verify` (lint, typecheck, unit/component, build, Playwright E2E, a11y basics). On
failure invoke `/fix` (max 3).

## Definition of done
**Setup phase:** Tech stack setup checklist complete (all boxes checked); no "TBD" setup tasks.

**Feature implementation phase:** All required UI states built and tested; standards addressed;
edge cases handled; no TypeScript errors; reuses existing components; contract consumed exactly.
Outputs: `branch`, `summary`, `tests_passed`. In slice mode, also return `worktree` and `tasks_done`.
