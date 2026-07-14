---
name: frontend-design
description: Author the frontend low-level design (LLD) for a feature — read the relevant frontend code to ground the design, then design component/state architecture, routing, the full UI-state matrix, the API it needs to consume, accessibility, performance, i18n, and tests. Writes the LLD doc; never edits app code. Front door for /frontend-design.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, design, lld, frontend]
---

# frontend-design — frontend low-level design

Design the **frontend** for a feature: read enough of the existing UI to ground the design in
real components and patterns, then write a **buildable frontend LLD**. Design artifact, not
code — never edit app code, don't implement, and don't design the backend. Prefer reuse over
reinvention; cite `file:line` for constraints. The **cross-repo contract** is not written
here — you describe the API/data your UI needs to **consume**; the two LLDs are reconciled
into the formal contract separately.

## Inputs
Your instructions name what to read — the approved HLD — and the artifact path to write.
Standalone? read the HLD and write the LLD to a path you choose (and tell the user where).

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
   the contract). This is reconciled with the backend's exposed API in the contract step.
5. **Accessibility strategy** (keyboard, focus, roles/labels, contrast — WCAG AA),
   **performance** (bundle/render, code-splitting on heavy routes), **security** (XSS/CSRF,
   authz in the UI, no secrets in the client), **i18n**, and **resilience** (error boundaries,
   optimistic UI + rollback).
6. **Test plan** — component + E2E coverage, including the negative UI states.
7. **Document tech stack decisions** — see section below.
8. **Write** the frontend LLD; flag anything that forces a backend/contract change.
9. **Emit the task DAG** — write a `tasks.json` (see section below), reusing the code you
   already read. No re-reading.

## Tech stack decisions
Document the technology choices that shape the frontend design. Teams choose based on their
experience and project constraints; record them so the implementer knows exactly what to
build toward. If your team already has established patterns, reference them; if not, make the
choice now (not "later"). Record them in the LLD's **"Tech Stack Decisions"** section:

1. **State Management** — Which library/framework? (e.g., Redux, Zustand, Context API, Jotai,
   native GetX/Provider for mobile). Store structure: normalized or denormalized?
2. **Data-Fetching & Caching** — Which library? (e.g., React Query, SWR, Apollo, Relay, native
   fetch). Cache strategy? Pagination approach (offset/limit or cursor)? Retry/backoff logic?
3. **Styling & Design Tokens** — Approach? (e.g., Tailwind CSS, CSS Modules, styled-components,
   Emotion, vanilla CSS). Where are design tokens defined? Theme system (CSS variables or JS)?
   Dark mode support?
4. **Testing Frameworks** — Unit (Jest or Vitest)? Component (React Testing Library)? E2E
   (Playwright, Cypress, WebdriverIO)? API mocking (MSW, Mirage, Prism)? Coverage targets?
5. **Form Validation** — Library & schema validator? (e.g., react-hook-form + Zod, Formik +
   Yup). Validation timing (real-time, on-blur, on-submit)? Async validation strategy?
6. **API Client & Type Generation** — Generated from OpenAPI/GraphQL schema, or hand-written?
   If generated: which tool and regeneration strategy? Single source of truth for types?
7. **Error Tracking & Logging** — Service (Sentry, LogRocket, Bugsnag) or custom/none? What
   gets logged? PII scrubbing rules? Error boundary placement strategy?
8. **Analytics & Event Tracking** — Tool (Segment, Amplitude, Mixpanel, GA) or none? Events
   to track? Event naming convention? User identification? PII handling in events?
9. **Build & Bundling** — Bundler? (Next.js, Vite, Webpack, esbuild). Code-splitting
   strategy? Environment configuration? Feature flags? Deployment target (Vercel, S3+CDN)?
10. **Performance Metrics & Budgets** — Lighthouse targets? Core Web Vitals targets (LCP, INP,
    CLS)? Bundle size limits? Virtualization thresholds? Memory budgets for mobile?
11. **Accessibility Testing** — Automated (axe, jest-axe)? Manual (keyboard, screen reader)?
    WCAG level (AA or AAA)? CI gates?
12. **i18n & Localization** — Languages supported? Library (i18next, next-i18next, react-intl)?
    Date/time library (date-fns, Day.js)? RTL support? Translation workflow?
13. **Authentication & Authorization** — Method (JWT, sessions, OAuth)? Token storage? Refresh
    strategy? Permission checking (UI-side, backend, or both)? Session expiry handling?
14. **Platform-Specific** — Web only, or multi-platform (React + React Native, Flutter)? Code
    sharing strategy? Native module integration? Platform-specific styling or components?

**Why:** the implementer builds toward these decisions. Without them recorded, they improvise
inconsistently. They don't require team consensus yet; they're recorded here for the
implement and review steps to follow.

## What the frontend LLD must cover (write all)
Context & constraints (grounded in the code, cited) · **tech stack decisions** · component & state design · routing ·
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
If a suitable deep-research skill is installed you may delegate to it to research unfamiliar
libraries or patterns — it must return sourced findings you can cite in the LLD. Otherwise
design from the code + HLD.

## Emit tasks.json (the parallel task DAG)
Write a `tasks.json` (to the path your instructions specify) conforming to
`engine/schemas/tasks.schema.json`. Build it
from the LLD you just wrote, reusing files you already read (do not re-read the codebase).

**Author it in one shot, then refine once.** Compose the entire tasks.json — manifest, every
`tasks[]` entry, and `slices[]` — in a single `Write`. Do **not** stub the file and grow it with
successive `Edit`s; assemble the whole structure in memory first and emit it once. After the
one `Write`, run the validator (below): if it prints `OK` you are done; if it fails, make **one**
corrective `Edit` (or a single rewriting `Write`) and re-validate. If that still fails, fix and
re-validate as needed — but never build the file up incrementally.

Fields:
- `context_manifest.read_once` = the component/state/hook files the tasks edit against;
  `reference` = this LLD path, the (pending) contract path, and `CLAUDE.md`.
- One `tasks[]` entry per ≤1-commit slice (e.g. types/API-client, a component + its UI states,
  form+validation, a route), each with `id`, `group_id`, `title`, `depends_on`
  (**intra-group only**), `reads`, `writes` (exact files), `test`, `standards`,
  `needs_human_gate` (true for auth/permission, prod config, or dependency changes).
- **Grouping:** two tasks share a `group_id` **iff** one depends on the other OR they write a
  common file; otherwise different groups. Fill `slices[]`, `task_ids` in dependency order.
- **Validate before returning:** `python3 engine/validate_tasks.py <tasks.json path>`
  must print `OK`.

## Output
Write your LLD to the given artifact path, with the sections above, each constraint citing
`file:line`. The API-consumed section feeds the contract step.

## Definition of done
Every section present; **tech stack decisions all recorded** (no "TBD" or "decide later");
UI-state matrix complete (no state omitted); API-consumed concrete enough to formalize; edge
cases specified (not "TBD"). Do not implement — this is a design artifact only.

## Output contract
Return `lld_path`, `tasks_path`, and `contract_notes` —
a short list of the **decisions/constraints that shape the contract** (e.g. "data-fetching goes
through hook X — reuse it"; "needs `GET /searches` returning `{items, nextCursor}`").
