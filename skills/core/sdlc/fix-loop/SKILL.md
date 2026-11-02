---
name: fix-loop
description: Make ONE bounded fix attempt at failing deterministic checks — root-cause first, editing only files related to the failure — then report. Front door for /fix-loop.
allowed-tools: Read, Grep, Glob, Bash, Edit
tags: [sdlc, fix, debug]
---

# fix-loop

**One invocation = one fix attempt.** Diagnose the failure, apply the smallest safe fix,
re-run the failing checks, and report. Do **NOT** loop internally: make one attempt, then
hand the result back — the caller re-invokes while checks still fail and owns the loop
bound, so a run never spins here. Run standalone, the same rule holds.

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
1. **Reproduce** — quote the exact failing command and its real error output. When your
   instructions supply a verification receipt or logs, start from the commands and output
   they record instead of guessing which checks failed.
2. **Diagnose** — find the root cause (read the code/stack trace); distinguish a real bug
   from a flaky test or an environment problem. State the cause before touching code.
3. **Smallest fix** — edit **only** files related to that root cause; no broad refactors,
   no unrelated "drive-by" changes.
4. **Re-run the failing check**; record the result.
5. If green, run the project's other checks (build, lint, full tests) — unless your
   instructions say an independent verification or re-run follows this attempt, in which case
   skip it. If a new failure appears, report it — the next invocation (a fresh attempt) handles
   it; do not chain fixes here.

## Classify before you "fix"
- **Flaky test** — fix the test's determinism (waits/selectors/seeding), not the product,
  and never by weakening assertions.
- **Environment issue** (service down, port, missing dep) — fix the env / report it; not a
  code change to force green.
- **Real defect** — fix the code with a regression test that fails before and passes after.
- **Committed secret** (a `secrets` check failure) — remove the credential from the code and from
  the feature branch's commits (amend or rewrite only that unpublished branch), load it from the
  project's configuration or secret store instead, and report that the credential must be rotated.
  Never allowlist or obfuscate it to pass the scan.
- **Spec/contract ambiguity** — stop and ask; do not invent behavior.
- **Product bug found by a test suite you may not change product code for** (a QA run against
  frozen, reviewed commits) — do not touch the product. Report it as a product bug with the
  repositories to fix, and write the diagnosis where your instructions say: per repository, the
  failing case IDs, expected vs actual behaviour, how to reproduce, and the suspected code. The
  caller fixes it in implementation and re-runs the suite.

## Stop and ask a human if
- a DB migration is required but not approved · the API contract would change ·
  auth/permission behavior changes · a dependency upgrade is needed · production config
  changes · the same root cause persists from a previous attempt with no new hypothesis ·
  multiple valid designs exist · the fix would weaken a test or a security control.

## Definition of done (per attempt)
Either: the targeted check (and the full checks, if reached) passes with a root-cause fix (and a
regression test for real defects); or you report the failure honestly — the exact commands,
the root cause (or best hypothesis), files changed, and remaining risk — and let the workflow
decide whether to re-invoke. Escalation is success, not failure.

## Output contract
Return `root_cause` (one line, or the hypothesis), `fix_summary` (files changed + what
changed), `checks_passed`, and `escalate` (true when a hard-stop trigger above was hit). When the
caller asks for them (a suite run against frozen product code), also return `product_bug` (true
when the product, not the test, is wrong) and `bug_repos` (the comma-separated repositories to
fix; empty otherwise).
`checks_passed` MUST be the literal JSON boolean `true` or `false` (true only if the targeted
checks actually ran AND passed after your fix) — never a count or status phrase. It is your
own report; a caller may still re-run the checks independently before trusting it.
