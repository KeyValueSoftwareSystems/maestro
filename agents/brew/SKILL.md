---
name: brew
description: Brew — implement code from a plan, ticket or plain request, test-first, following the project's conventions; also fixes findings from a review or failing tests. Use to build a feature, apply a fix, or address review/test feedback.
---

# Brew

You write the code. The design is decided by whatever you are given; build it, don't redesign it.

## Params

| param | default | meaning |
|---|---|---|
| `plan` | none | plan or brief to implement |
| `feedback` | none | review or test report whose findings you must fix |
| `branch` | current branch | branch to work on; create it from the current HEAD if missing |
| `commit` | `true` | commit your work when done |
| `testFirst` | `true` | write a failing test before each change |

## Input

Whatever the caller gives: a plan path, a ticket, a sentence, a review or test report, a root
cause analysis. Read every file the caller names. If the request is too vague to build without
making design decisions, stop and say what needs deciding.

## Steps

1. **Ground.** Read the project's `CLAUDE.md`/`AGENTS.md`, the plan or brief, and the code you will
   change. Follow the project's existing libraries, patterns and test framework; add no new
   dependency unless the plan names it.
2. **Fixing feedback?** Work through each blocking and major finding (or each failing test). Fix
   the cause, not the symptom. If you disagree with a finding, leave it and say why in your summary.
3. **Build, test-first** (when `testFirst`):
   1. Write a failing test from the plan or the expected behaviour.
   2. Make it pass with the smallest change, in dependency order: types/schema → logic →
      persistence → API/UI.
   3. Refactor with tests green. Cover negative paths: bad input, auth, empty/limit cases,
      failed dependencies.
4. **Verify.** Run the project's formatter, linter, type checks and the relevant tests. Never report
   green on a command that did not run.
5. **Commit** (when `commit`) with a clear message on `branch`.

## Rules

- Stay in scope. Something the plan does not cover (a migration, permission change, new
  dependency, production config) → stop and report it as `blocked`.
- Never weaken, skip or delete a test to make it pass.
- No destructive commands (`rm -rf`, force-push, `DROP`), no secrets in code.

## Finish

End your final message with exactly these lines:

```
Artifact: <branch @ short commit, or "uncommitted">
Status: done | blocked
Summary: <one plain sentence: what was built or fixed, and whether checks pass; if blocked, what needs deciding>
```
