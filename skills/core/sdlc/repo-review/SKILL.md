---
name: repo-review
description: Review one repository's exact implementation worktree and commit against its LLD and contract, with evidence-backed findings and a blocking verdict.
allowed-tools: Read, Grep, Glob, Bash, Write, Task
tags: [sdlc, review, repository]
---

# repo-review

Review only the exact `worktree` and `commit` supplied by the workflow. First verify its HEAD
equals the supplied commit and its current branch equals the supplied branch. If either
differs, report a blocking integrity finding instead of reviewing another checkout.

## Method

1. **Scope the diff** — changed files, new endpoints, migrations, pages and components, and
   their blast radius in the codebase map.
2. **Line it up** against the approved LLD, the shared contract and the repository's
   instructions. Where the harness supports it you may spawn one fresh read-only subagent
   following this skill for an independent pass.
3. **Review every dimension below** that applies to this repository's technology. Read-only:
   never edit code.
4. **Consolidate** findings by severity and decide `blocking`.

## Checklist

- **Correctness** — logic matches the LLD and acceptance criteria; concurrency, transactions
  and idempotency for retried writes.
- **Contract** — endpoints, payloads, error shape and status codes match exactly; a consumer
  calls the API as published; breaking changes are flagged, never silent.
- **Security** — authorization on every operation; input validation and bounds; injection;
  output encoding and XSS; secrets and PII in code, logs or analytics; SSRF; tokens in client
  storage.
- **Compatibility and data** — additive changes; migrations expand → migrate → contract,
  reversible, indexed, with a safe backfill.
- **Reliability and performance** — timeouts, retries with backoff, rate limits and payload
  caps; no N+1 or unbounded queries; code-splitting and list virtualization in UIs.
- **UI** — every state reachable (loading, empty, success, validation error, API error,
  permission denied, retry); WCAG AA keyboard, focus, labels and contrast; double-submit and
  optimistic-update rollback; localizable strings.
- **Observability** — structured logs without PII, metrics and traces on new paths.
- **Tests** — branches, error paths and the acceptance-criteria edge cases are tested, and the
  assertions check behavior. Inspect every change to an existing test: when your instructions
  list changed test files, say for each whether the approved design justifies it. A weakened,
  skipped or deleted assertion without that basis is a blocker.

## Findings

Every finding needs `file:line` evidence (quoted code, test or contract clause, or the
absence of one) and the smallest safe recommendation:

```
- severity: blocker | major | minor | suggestion
  area: correctness | contract | security | compatibility | data | reliability | performance | ui | observability | tests
  file: <path:line>
  evidence: <quote or gap>
  recommendation: <smallest safe change>
```

Sort blocker → major → minor → suggestion. Any blocker or major makes `blocking=true`. Write
the report outside the product worktree and record the reviewed commit at its top.

**Re-review.** When your instructions supply a previous review (a re-review after a fix), read it
first and review only the diff from the commit it records to the supplied commit: confirm each
earlier blocker/major is resolved and check the new change for regressions. Do not re-audit
unchanged code or raise new minor findings on it.

## Safety

Read-only. Never edit product code, push, or change the worktree; write only the report.

## Output contract

Return `review_path`, literal boolean `blocking`, and a one-line `summary` (verdict and the
count of blocking findings) as last-line JSON.
