---
name: architecture-review
description: Review the per-stack LLDs and the cross-repo contract AFTER design, before implementation — analyze architecture gaps, security, scaling, reliability, data model, and contract soundness. Read-only; writes a review artifact. Front door for /architecture-review.
allowed-tools: Read, Grep, Glob, Bash, Task, Write
tags: [sdlc, review]
---

# architecture-review

Review the drafted design **before any code is written**, so architecture problems are
caught while they are cheap to fix. Read-only — never edit code.

## Inputs
`feature`, `feature_slug`; the per-stack LLDs and contract — resolve their paths from
`maestro.config.yaml` → `artifacts.lld_backend`, `artifacts.lld_frontend`,
`artifacts.contract` (`<slug>` = `feature_slug`) — cross-checked against the HLD
(`artifacts.hld`), acceptance criteria, and architecture rules (`CLAUDE.md`, ADRs).

## Steps
1. **Read** the HLD, both LLDs, the contract, and acceptance criteria; note the stated NFRs.
2. **Trace each acceptance criterion** to a design element — flag anything unmet (a gap).
3. **Deep, evidence-backed pass** over every dimension in the checklist below. For a more
   independent read you MAY spawn a fresh read-only sub-agent (via the Task tool) that follows
   this same skill — do this where your harness supports it (e.g. Claude Code). Otherwise
   perform the pass **inline**. Either way: **read-only — never edit code.** You are the
   read-only backstop; nothing is skipped.
4. **Consolidate** findings; sort by severity; decide `blocking`.
5. **Write** the report and return the verdict.

## What the review must cover (checklist — independent of the external skill)
- **Completeness / gaps** — does the design satisfy every requirement & acceptance
  criterion? Missing flows, unhandled cases, undefined behavior, TBDs.
- **Boundaries & coupling** — correct service/module boundaries; no coupling that bypasses
  the contract; clear ownership.
- **Data model & migrations** — schema soundness; expand→migrate→contract; reversibility;
  indexing; no online long locks; safe backfill.
- **Contract soundness** — versioning/backward-compat; consistent error shape; auth per
  operation; pagination/limits; **idempotency**; concurrency control; breaking changes flagged.
- **Security posture** — authn/authz model, tenant isolation, PII/data protection, threat
  surface of new endpoints/integrations, secrets handling.
- **Scalability & performance** — expected load, hotspots, N+1/fan-out, caching,
  statelessness, rate limits, payload caps, connection pools.
- **Reliability** — failure modes, timeouts, retries/backoff, backpressure, partial-failure
  and rollback behavior, degradation.
- **Observability & cost** — logs/metrics/traces planned for new paths; cost blast radius.

## Edge cases / smells to watch for
- "Happy-path" designs that omit failure and permission paths.
- Breaking contract changes not labeled as such; missing deprecation/migration plan.
- Migrations without rollback or without a backfill plan for existing data.
- New synchronous call in a hot path (latency/coupling); unbounded queries or list endpoints.
- Multi-tenant leakage; PII in logs; secrets in config committed to the repo.
- Cross-service transaction assumed where only eventual consistency is available.

## External skill (provision — review method)
Read `maestro.config.yaml` → `external_skills.review` (default `requesting-code-review`, from the
Superpowers pack, or `none`). If set, apply its review discipline first; it must not narrow the checklist
above.

## Findings format (what the review returns — evidence mandatory)
```
summary: <one paragraph: is the design sound to build? what are the top risks?>
findings:
  - severity: blocker | major | minor | suggestion
    area: gaps | boundaries | data-model | contract | security | scaling | reliability | observability
    location: <lld/*.md section / openapi path / file:line>
    evidence: <quoted design/contract text or its absence>
    recommendation: <the design change>
    safe_for_ai_fix: <true|false>
blocking: <true if any blocker/major remains>
```

## Decide & output
Sort findings blocker → major → minor → suggestion; `blocking = true` if any blocker/major
remains. A contract/auth/data-model change is never `safe_for_ai_fix`. Write the report
(summary + findings table) to the `artifacts.arch_review` path from `maestro.config.yaml`
(`.maestro/<slug>/reviews/architecture.md`). Feeds the contract-approval gate; a blocking
result routes the workflow back to revise the design.

## Output contract
Return `review_path`, `blocking`, `summary`. When invoked as a Maestro workflow step, your
reply's LAST line must be exactly one JSON object with these fields — short scalar values
only, never file contents.
