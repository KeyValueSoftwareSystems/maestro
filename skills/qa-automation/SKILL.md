---
name: qa-automation
description: Author critical-journey E2E / UI-automation tests from the acceptance criteria (not from the implementation), run them in a clean env, and report. Meets QA standards (risk-tiering, isolation, determinism, no weakened assertions). Edits test files only. Front door for /qa.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write
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
`feature`, `acceptance_criteria`, optional `contract_summary` (for cross-service journeys).

## Steps
1. **Pick the framework** from `skills.config.yaml` → `qa.framework` (`playwright` web /
   `maestro` mobile).
2. **Derive journeys** from the acceptance criteria; rank by risk; pick the critical ones
   and the highest-value negative paths. State what is out of scope.
3. **Design test data** — each test seeds and tears down its own data; no shared mutable state.
4. **Author tests** with stable selectors (roles/test-ids), explicit waits on conditions,
   and assertions that verify observable behavior + the contract's outcomes.
5. **Emit the scenario DAG** — write `.sdlc/<slug>/qa/tasks.json` (see section below) so the
   suite can be authored in parallel.
6. **Run in a clean env** — `stack up` → seed → ready_check → run → `stack down` (teardown
   always runs).
7. **On failure**, apply the fix-loop rule (selectors/flakes/waits only), bounded to 3.

## Standards every suite must satisfy
- **Risk-tiered** — critical journeys + key negatives; explicit out-of-scope note.
- **Isolated & idempotent** — self-contained setup/teardown; order-independent.
- **Deterministic** — wait on conditions/selectors, never fixed sleeps; stable selectors,
  not brittle CSS chains; control time/randomness where possible.
- **Cross-service** — real contract, not mocks, in the clean stack for cross-service journeys.
- **No weakened assertions** — self-healing may refresh selectors / re-run only; it must NOT
  weaken assertions, permissions, or expected behavior (enforced by
  `workflow.config.yaml` → `gates.freeze_approved_tests`).
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
Read `skills.config.yaml` → `qa.external.generator` (e.g. `anthropics:webapp-testing`, or
`none`). If set, use it to generate tests — the output must still meet the standards above
(isolation, determinism, real assertions, risk-tiering). If `none`, author in-pack.

## Emit tasks.json (parallel scenario authoring)
Write `.sdlc/<slug>/qa/tasks.json` conforming to `workflows/tasks.schema.json`, with
`"stack": "qa"`. Scenarios are independent, so each scenario is its **own single-task group**:
- `context_manifest.read_once` = shared fixtures / page objects / test helpers the specs use;
  `reference` = the acceptance-criteria path and the contract summary.
- One `tasks[]` entry per scenario: `id`, its own `group_id`, `title` (the journey), empty
  `depends_on`, `reads` (extra fixtures), `writes` (the spec file it creates), `test` (the
  scenario id), `standards` (e.g. `["risk-tiered","determinism","isolation"]`),
  `needs_human_gate: false`. `slices[]` = one group per scenario.
- **Validate before returning:** `python3 workflows/validate_tasks.py .sdlc/<slug>/qa/tasks.json`
  must print `OK`.

## Output
Write a coverage note to `.sdlc/<slug>/qa/suite.md` (journeys covered, negatives covered,
out-of-scope, data strategy). Also write `.sdlc/<slug>/qa/tasks.json`. Return `suite_path`,
`tasks_path`, `slices` (the `slices` array from tasks.json), and `tests_passed`.

## Definition of done
Critical journeys + key negatives automated and green in a clean env; tests isolated and
deterministic; failures produce artifacts; nothing weakened to pass.
