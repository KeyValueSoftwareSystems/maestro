---
name: fix-loop
description: Make ONE bounded fix attempt at failing deterministic checks — root-cause first, editing only files related to the failure — then report; the workflow re-invokes per attempt and the engine's visit cap ends the loop before escalating to a human. Front door for /fix.
allowed-tools: Read, Grep, Glob, Bash, Edit
tags: [sdlc, fix, debug]
---

# fix-loop

**One invocation = one fix attempt.** Diagnose the failure, apply the smallest safe fix,
re-run the failing checks, and report. Do **NOT** loop internally: the workflow re-invokes
this skill while checks still fail, and the engine owns the loop bound — the workflow's fix
nodes carry `max_visits` (typically 3), and that visit cap ends the loop. Run standalone,
the same rule holds: one attempt, then hand the result back.

**Safety:** never run destructive commands (`rm -rf`, force-push, `DROP`/`TRUNCATE`) or write
prod config/secrets. Nothing auto-blocks this — you are the backstop, and this rule holds
regardless of environment. The escalation triggers below are hard stops. **Never weaken or
delete a failing test** to make a check pass.

## External skill (provision — debugging method)
If the `systematic-debugging` skill (from the Superpowers pack) is installed, use its
four-phase root-cause method — **do not "fix" what you have not
understood.** Whatever the method, it must: reproduce the failure, find the root cause,
predict the fix, and confirm. If it is not installed, follow the same discipline in-pack.

## The attempt (this invocation)
1. **Reproduce** — quote the exact failing command and its real error output.
2. **Diagnose** — find the root cause (read the code/stack trace); distinguish a real bug
   from a flaky test or an environment problem. State the cause before touching code.
3. **Smallest fix** — edit **only** files related to that root cause; no broad refactors,
   no unrelated "drive-by" changes.
4. **Re-run the failing check**; record the result.
5. If green, run full verification (`/verify`). If a new failure appears, report it — the
   workflow's next invocation (a fresh attempt) handles it; do not chain fixes here.

## Classify before you "fix"
- **Flaky test** — fix the test's determinism (waits/selectors/seeding), not the product,
  and never by weakening assertions.
- **Environment issue** (service down, port, missing dep) — fix the env / report it; not a
  code change to force green.
- **Real defect** — fix the code with a regression test that fails before and passes after.
- **Spec/contract ambiguity** — stop and ask; do not invent behavior.

## Stop and ask a human if
- a DB migration is required but not approved · the API contract would change ·
  auth/permission behavior changes · a dependency upgrade is needed · production config
  changes · the same root cause persists from a previous attempt with no new hypothesis ·
  multiple valid designs exist · the fix would weaken a test or a security control.

## Definition of done (per attempt)
Either: the targeted check (and `/verify`, if reached) passes with a root-cause fix (and a
regression test for real defects); or you report the failure honestly — the exact commands,
the root cause (or best hypothesis), files changed, and remaining risk — and let the workflow
decide whether to re-invoke. Escalation is success, not failure.

## Output contract
Return `root_cause` (one line, or the hypothesis), `fix_summary` (files changed + what
changed), `checks_passed` (true/false), and `escalate` (true when a hard-stop trigger above
was hit).

When invoked as a Maestro workflow step, your reply's LAST line must be exactly one JSON
object with these fields — short scalar values only, never file contents.
