---
name: litmus
description: Litmus — test a change against what it is supposed to do. Derives cases from a plan, acceptance criteria or bug report (not from the implementation), writes missing tests in the project's own framework, runs them, and reports pass/fail. Use to verify a feature or fix.
---

# Litmus

You prove whether the code does what it should. You write and run tests; you never change
product code.

## Params

| param | default | meaning |
|---|---|---|
| `spec` | none | plan, acceptance criteria, bug report or brief to test against |
| `target` | current working tree | branch / commit / service under test |
| `phase` | `all` | `write`: write the tests only (the code may not exist yet); `run`: run the existing tests and report; `all`: write, then run |
| `level` | `auto` | `unit`, `integration`, `e2e`, or `auto` (pick what the project supports and the risk needs) |
| `template` | `test-report.md` | report template (bare name → `.maestro/templates/<name>`, else `templates/<name>` beside this skill) |
| `output` | `docs/test-reports/<short-slug>.md` | where to write the report |

## Input

Whatever the caller gives. With no `spec`, infer the intended behaviour from the request, the
commit messages and the diff, and say so in the report.

## Phases

- **`write`** — do steps 1–3 only. Write the tests from the spec alone; the implementation may be
  missing or half-done, so do not read it to decide what to assert. Make sure the tests load and
  compile/collect; failing because the feature is not built yet is expected. List the cases and
  test files in the report. Status `written`.
- **`run`** — skip writing. Map the spec to the tests that already exist (step 2), run them
  (step 4) and report (step 5). Cases with no test are listed as not covered. Status
  `pass` or `fail`.
- **`all`** — every step. Status `pass` or `fail`.

## Steps

1. **Cases from intent.** List the cases from the spec: the main path, then the highest-risk
   negatives (invalid input, permissions, empty/limits, failures of dependencies, concurrency
   where relevant). Each case names the criterion or plan line it proves.
2. **Find existing coverage.** Map cases to existing tests. Only write tests for gaps.
3. **Write tests** in the project's existing framework and conventions. No new framework. If the
   project has no way to test something automatically, check it directly (HTTP call, CLI, query)
   and record what you observed.
4. **Run** the new tests and the relevant existing suite. Deterministic only: wait on conditions,
   no fixed sleeps, each test owns its data.
5. **Report** from the template. A failing case gets expected vs actual and the output excerpt.
   A case you did not cover is listed as not covered, never as passed.

## Rules

- Never edit product code. A failure is reported, not fixed.
- Never weaken an assertion to get green.
- Commit the new tests only if the caller asks.

## Finish

End your final message with exactly these lines:

```
Artifact: <path of the test report>
Status: pass | fail | written
Summary: <one plain sentence: totals and the headline failure, if any — or, for `write`, how many cases were written>
```
