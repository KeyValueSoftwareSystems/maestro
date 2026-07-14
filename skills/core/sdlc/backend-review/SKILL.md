---
name: backend-review
description: Review the backend implementation — security, contract adherence, correctness, backward compatibility, rate-limiting, performance/scaling, migrations, test gaps, observability. Read-only; writes a review artifact. Front door for /backend-review.
allowed-tools: Read, Grep, Glob, Bash, Task, Write
tags: [sdlc, review, backend]
---

# backend-review

Review the backend implementation (diff/branch) against the contract and LLD. Read-only —
never edit code; reviewers return evidence and recommendations, humans decide fixes.

## Steps
1. **Scope the diff** — identify changed files, new endpoints, migrations, and their blast radius.
2. **Line the diff up against the contract** and the LLD — read the inputs your instructions point to.
3. **Deep, evidence-backed pass** over every dimension in the checklist below. For a more
   independent read you MAY spawn a fresh read-only sub-agent (via the Task tool) that follows
   this same skill — do this where your harness supports it (e.g. Claude Code). Otherwise
   perform the pass **inline**. Either way: **read-only — never edit code.** You are the
   read-only backstop; nothing is skipped.
4. **Consolidate** findings by severity; decide `blocking`.
5. **Write** the report and return the verdict.

## What the review must cover (checklist — independent of the external skill)
- **Security** — authz on every endpoint (no client trust); input validation & bounds;
  injection (SQL/command/template); output encoding; secrets in code/logs; PII handling;
  safe deserialization; SSRF.
- **Contract adherence** — endpoints/DTOs/error shape/status codes match exactly; no
  undocumented divergence; breaking changes flagged, not silent.
- **Correctness & concurrency** — logic matches spec; transactions; races/isolation;
  idempotency for mutating/retryable ops.
- **Backward compatibility** — additive; no removed/retyped fields or tightened validation
  without version + migration; defaults for new fields.
- **Rate limiting & abuse** — limits/quotas; page-size & payload caps; timeouts; 429 semantics.
- **Performance & scaling** — no N+1/unbounded queries; indexes for new paths; caching/pooling;
  behavior under load.
- **Data & migrations** — expand→migrate→contract; reversible; no online long locks; backfill.
- **Test gaps** — branches, error paths, and acceptance-criteria edge cases tested;
  assertions verify behavior; not happy-path only.
- **Observability** — structured logs (no PII), metrics/traces on new paths, error taxonomy.

## Edge cases / smells to watch for
- Endpoint added without an authz check or without validation on a field.
- Error paths returning 200, or leaking stack traces / internal messages.
- A migration with no rollback, or a breaking column change done in one step.
- Retry without idempotency (double side effects); missing rate limit on a new public route.
- N+1 introduced in a loop; unbounded list endpoint; missing index for a new query.
- Tests that assert nothing meaningful, or only cover the happy path.

## External skill (provision — review method)
If the `requesting-code-review` skill (from the Superpowers pack) is installed, apply its
discipline first; it must not narrow the checklist above. If it is not installed, review
inline per the checklist.

## Findings format (what the review returns — evidence mandatory)
```
summary: <one paragraph verdict + top risks>
findings:
  - severity: blocker | major | minor | suggestion
    area: security | contract | correctness | backward-compat | rate-limiting | performance | scaling | data-migrations | test-gap | observability
    file: <path:line>
    evidence: <quoted code / test / contract clause, or the gap>
    recommendation: <smallest safe change>
    safe_for_ai_fix: <true|false>
blocking: <true if any blocker/major remains>
```

## Decide & output
Sort blocker → major → minor → suggestion; `blocking = true` if any blocker/major remains.
Auth/permission or contract changes are never `safe_for_ai_fix` — escalate. Write the report
to the artifact path your instructions specify (the orchestrator passes it). Running
standalone? write to a sensible path you choose and tell the user where.

## Output contract
Return `review_path`, `blocking` (true/false), and `summary` (one line: the headline
verdict and the count of blocking findings).
