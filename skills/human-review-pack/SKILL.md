---
name: human-review-pack
description: Assemble a concise, evidence-backed PR/release review pack before approval — what changed and why, impact, the verify proof, reviewer findings (fixed and deferred), and the exact decision needed. Read-only; writes the pack. Front door for /review-pack.
allowed-tools: Read, Grep, Glob, Bash, Write
---

# human-review-pack

Assemble everything a human needs to approve a PR or release — **with evidence, not
claims.** Read-only. The pack must let a reviewer decide in minutes and must not overstate
readiness.

## Steps
1. **Collect the diff summary** — changed files/areas per stack; new endpoints/migrations/UI.
2. **Pull the proof** — the `/verify` reports and `.maestro/<slug>/<stack>/last-verify.json` markers per stack;
   the QA suite result. If proof is missing or `status:"fail"`, say so — do not claim green.
3. **Pull the reviewer findings** — `.maestro/<slug>/architecture-review.md` and each stack's
   `reviews/summary.md`; separate what was **fixed** from what is **deferred/accepted**.
4. **Assess risk & release readiness** — migrations, flags, rollout/backout, data impact.
5. **Write** the pack and state the exact decision required.

## The pack must include (with evidence/links)
1. **What changed** — feature summary + per-stack change list.
2. **Why** — link the requirement/HLD; the problem solved.
3. **Files changed** — grouped by area; call out anything security/auth/data-sensitive.
4. **API / DB / UI impact** — contract changes (breaking?), migrations (+ rollback), new UI states.
5. **Tests & proof** — commands run and pass/fail (from `/verify`); coverage vs threshold;
   QA journeys covered; screenshots / Playwright traces for frontend.
6. **Review findings fixed** — with the reviewer + severity.
7. **Findings intentionally NOT fixed** — each with a reason and risk acceptance.
8. **Risks & limitations** — known issues, perf/scale caveats, follow-ups.
9. **Rollout & backout** — flag state, phased plan, metrics to watch, how to revert.
10. **Decision needed** — approve / changes requested / reject, and exactly what to approve
    (e.g. merge order backend → frontend).

## Edge cases to represent honestly
- **Partial green** — some checks pass, one is flaky/red → say it plainly; don't average it away.
- **Deferred blockers** — a major finding accepted for later needs explicit sign-off and a ticket.
- **Missing proof** — no verify marker, or `status:"fail"` → the pack recommends "not ready".
- **Breaking contract change** — surface prominently with the consumer migration plan.
- **Risky migration / irreversible step** — flag as requiring extra human attention.

## Output
Write `.maestro/<slug>/review-pack.md`. Return `pack_path`. Never claim readiness without the
proof to back it — the review pack is a decision aid, not a rubber stamp.
