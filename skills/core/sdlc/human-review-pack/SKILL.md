---
name: human-review-pack
description: Assemble a concise, evidence-backed PR/release review pack — what changed and why, impact, the verification proof, reviewer findings (fixed and deferred), and the exact decision needed. Read-only; writes the pack. Front door for /human-review-pack.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, review, release]
---

# human-review-pack

Assemble everything a human needs to approve a PR or release — **with evidence, not
claims.** Read-only. The pack must let a reviewer decide in minutes and must not overstate
readiness.

## Steps
1. **Collect the diff summary** — changed files/areas per stack; new endpoints/migrations/UI.
2. **Pull the proof** — the verification receipts and per-repository verification status your
   instructions supply (commands run, exit codes, the verified commit, changed tests) and the
   QA suite result. If proof is missing, failed, or verifies a different commit than the one
   being released, say so — do not claim green.
3. **Pull the reviewer findings** — from the architecture review and each stack's review;
   separate what was **fixed** from what is **deferred/accepted**.
4. **Assess risk & release readiness** — migrations, flags, rollout/backout, data impact.
5. **Write** the pack and state the exact decision required.

## The pack must include (with evidence/links)
0. **Unconfirmed decisions — first** — when your instructions supply an assumption log, open
   the pack with it: every assumption and every item left open, as written, and every gate
   answered without a person. These are guesses nobody confirmed; never fold them into
   "what changed" or soften them.
1. **Acceptance-criteria trace** — when your instructions supply one, show it as written: each
   criterion, the cases that cover it, and its result. A criterion that is failing or not run
   makes the recommendation "not-ready" unless the human already accepted it.
2. **Design drift** — when your instructions supply a drift report, list every place the code
   departs from the approved design as written; blocking drift makes the recommendation
   "not-ready" until the code or the design is changed and re-approved.
3. **What changed** — feature summary + per-stack change list.
4. **Why** — link the requirement/HLD; the problem solved.
5. **Files changed** — grouped by area; call out anything security/auth/data-sensitive.
6. **API / DB / UI impact** — contract changes (breaking?), migrations (+ rollback), new UI states.
7. **Tests & proof** — per repository, the commands run and their pass/fail from the
   verification receipt, checks that were skipped, and each existing test the branch changed
   with the reviewer's justification; coverage only where a receipt records it; QA journeys
   covered; screenshots / Playwright traces for frontend.
8. **Review findings fixed** — with the reviewer + severity.
9. **Findings intentionally NOT fixed** — each with a reason and risk acceptance.
10. **Risks & limitations** — known issues, perf/scale caveats, follow-ups.
11. **Rollout & backout** — flag state, phased plan, metrics to watch, how to revert.
12. **Decision needed** — approve / changes requested / reject, and exactly what to approve
    (e.g. merge order backend → frontend).

## Edge cases to represent honestly
- **Partial green** — some checks pass, one is flaky/red → say it plainly; don't average it away.
- **Deferred blockers** — a major finding accepted for later needs explicit sign-off and a ticket.
- **Autopilot run** — assumptions or open items exist → name the ones that change behaviour a
  user will see; an open item that blocks an acceptance criterion makes the pack "not-ready".
- **Missing proof** — no verification receipt, a failed check, or a receipt for a different
  commit than the one released → the pack recommends "not-ready".
- **Changed tests** — an existing test modified or deleted without a stated justification →
  list it under risks; never present it as passing coverage.
- **Breaking contract change** — surface prominently with the consumer migration plan.
- **Risky migration / irreversible step** — flag as requiring extra human attention.

## Output
Write the pack to the artifact path your instructions specify (the orchestrator passes it).
Running standalone? write to a sensible path you choose and tell the user where. Never claim readiness
without the proof to back it — the review pack is a decision aid, not a rubber stamp.

## Output contract
Return `pack_path`, `recommendation` (`ready` | `changes-requested` | `not-ready`,
mirroring the pack's "Decision needed" section), and `summary` (one line the human reads
at the release gate).
