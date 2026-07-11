---
name: qa-automation
description: Author critical-journey E2E / UI-automation tests from the acceptance criteria (not from the implementation), run them in a clean env, and report. Meets QA standards (risk-tiering, isolation, determinism, no weakened assertions). Edits test files only. Front door for /qa.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write
tags: [sdlc, qa]
---

# qa-automation

Author end-to-end / UI-automation tests derived from the **acceptance criteria**, not from
the implementation. Cover risk-tier **critical journeys** plus their key negative paths —
not every path.

## When to use / not use
- **Use** once acceptance criteria exist (from `/api-contract`) and an env can be brought up.
- **Don't** test against the implementation's internals, and **never weaken assertions** to
  make a test pass.

## Inputs
`feature`, `acceptance_criteria`, optional `contract_summary` (for cross-service journeys), and
optional `test_cases_path` — the design-phase functional test-case catalog
(`.maestro/<slug>/test-cases.md`, from `/functional-testcases`).

## Steps
1. **Pick the framework** — default **Playwright** (use the project's existing E2E framework
   if one is already set up; e.g. Maestro for mobile).
2. **Source the journeys.** If `test_cases_path` exists, that catalog is the source of truth —
   automate its cases, preserving each case's ID/traceability, and do not silently drop a case
   (note any you defer and why). Only when no catalog is present do you derive journeys straight
   from the acceptance criteria. Either way: rank by risk and scope to the default tier —
   **critical-journeys-only**; pick the critical
   ones and the highest-value negative paths; state what is out of scope.
3. **Design test data** — each test seeds and tears down its own data; no shared mutable state.
4. **Author tests** with stable selectors (roles/test-ids), explicit waits on conditions,
   and assertions that verify observable behavior + the contract's outcomes.
5. **Emit the scenario DAG** — write `.maestro/<slug>/qa/tasks.json` (see section below) so the
   suite can be authored in parallel.
6. **Run in a clean env** — `stack up` → seed → ready_check → run → `stack down` (teardown
   always runs).
7. **On failure**, apply the fix-loop rule (selectors/flakes/waits only) — one attempt per
   invocation; the workflow's `max_visits` on the fix node (typically 3) bounds the loop.

## Standards every suite must satisfy
- **Risk-tiered** — critical journeys + key negatives; explicit out-of-scope note.
- **Isolated & idempotent** — self-contained setup/teardown; order-independent.
- **Deterministic** — wait on conditions/selectors, never fixed sleeps; stable selectors,
  not brittle CSS chains; control time/randomness where possible.
- **Cross-service** — real contract, not mocks, in the clean stack for cross-service journeys.
- **No weakened assertions** — self-healing may refresh selectors / re-run only; it must NOT
  weaken assertions, permissions, or expected behavior. Approved tests are frozen.
- **Safe** — no real secrets or production data; seeded test data only.
- **Reportable** — on failure, capture screenshot/trace/video and the failing step.

## Edge cases / journeys to include
- Primary happy journey end-to-end across services.
- Validation failures surfaced to the user; permission-denied journey.
- Empty state and "many items" / pagination boundary.
- Slow/failed API handling (retry/error UI); session expiry mid-flow.
- Concurrency/double-submit where the journey allows it.
- Mobile: gestures, back button, deep links, orientation (Maestro).

## External skill (provision — test generation)
If a suitable test-generator skill is installed you may delegate test generation to it —
the output must still meet the standards above (isolation, determinism, real assertions,
risk-tiering). Otherwise author in-pack.

## Emit tasks.json (parallel scenario authoring)
Write `.maestro/<slug>/qa/tasks.json` (under the QA suite dir `.maestro/<slug>/qa/`) conforming to
`engine/schemas/tasks.schema.json`, with `"stack": "qa"`. Scenarios are independent, so each
scenario is its **own single-task group**.

**Author it in one shot, then refine once.** Compose the entire tasks.json — manifest, every
`tasks[]` entry, and `slices[]` — in a single `Write`. Do **not** stub the file and grow it with
successive `Edit`s; assemble the whole structure in memory first and emit it once. After the
one `Write`, run the validator (below): if it prints `OK` you are done; if it fails, make **one**
corrective `Edit` (or a single rewriting `Write`) and re-validate. Repeat only to fix validation
errors, never to build the file up incrementally.

Fields:
- `context_manifest.read_once` = shared fixtures / page objects / test helpers the specs use;
  `reference` = the acceptance-criteria path and the contract summary.
- One `tasks[]` entry per scenario: `id`, its own `group_id`, `title` (the journey), empty
  `depends_on`, `reads` (extra fixtures), `writes` (the spec file it creates), `test` (the
  scenario id), `standards` (e.g. `["risk-tiered","determinism","isolation"]`),
  `needs_human_gate: false`. `slices[]` = one group per scenario.
- **Validate before returning:** `python3 engine/validate_tasks.py .maestro/<slug>/qa/tasks.json`
  must print `OK`.

**Scenario mode:** when invoked with a `group_id` and `tasks_path`, author only that one
scenario's spec file (batch-load the fixture manifest once) and return `spec_path`.

## Output
All outputs go under the QA suite dir `.maestro/<slug>/qa/`, with `<slug>` = `feature_slug` —
this skill owns where it writes; the caller passes no paths. Write a coverage note to
`.maestro/<slug>/qa/suite.md` (journeys covered, negatives covered, out-of-scope, data
strategy), the run report to `.maestro/<slug>/qa/report.md`, and `.maestro/<slug>/qa/tasks.json`.

## Definition of done
Critical journeys + key negatives automated and green in a clean env; tests isolated and
deterministic; failures produce artifacts; nothing weakened to pass.

## Output contract
Return `suite_path`, `tasks_path`, `slices` (the `slices` array from tasks.json), and
`tests_passed`. In scenario mode, return `spec_path`.

When invoked as a Maestro workflow step, your reply's LAST line must be exactly one JSON
object with these fields — short scalar values only, never file contents.
