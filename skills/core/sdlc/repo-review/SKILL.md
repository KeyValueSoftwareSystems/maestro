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

- **Completeness** — every task in the task list your instructions name is built, and nothing
  outside the LLD's scope is; a task marked as needing a human gate (migrations, permissions,
  payments, production config, dependencies) matches the LLD exactly.
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
- severity: blocking | major | minor
  area: completeness | correctness | contract | security | compatibility | data | reliability | performance | ui | observability | tests
  file: <path:line>
  evidence: <quote or gap>
  recommendation: <smallest safe change>
```

Each finding has one severity, the same in the report and the findings file:

- `blocking` — must change before this code ships: a correctness, security, contract or data-loss
  defect, a missing task, or a weakened test without a design basis;
- `major` — a real problem worth fixing that does not make the change unsafe to ship;
- `minor` — style, naming, a suggestion.

Sort blocking → major → minor. `blocking` is true exactly when a `blocking` finding is open or
upheld. Write the report outside the product worktree and record the reviewed commit at its top.

**Findings file.** When your instructions give a findings path, also write every finding there as
JSON — the workflow decides from this file, not from your prose:
`{"schema_version": 1, "findings": [{"id", "severity": "blocking" | "major" | "minor", "area",
"finding", "evidence", "status": "open" | "upheld" | "withdrawn" | "resolved"}]}`. Keep ids stable
across rounds; new findings get new ids.

**Re-review.** When your instructions supply a previous review (a re-review after a fix), read it
first, with the author's resolutions when your instructions give them, and review only the diff
from the commit it records to the supplied commit. Mark a fixed finding `resolved` (or keep it
`open` if the fix falls short) and answer each contest: `withdrawn` when the author is right,
`upheld` with your reason when not. A contested finding is never silently dropped. Check the new
change for regressions; do not re-audit unchanged code or raise new minor findings on it.

## Safety

Read-only. Never edit product code, push, or change the worktree; write only the report and the
findings file.

## Output contract

Return `review_path`, literal boolean `blocking`, and a one-line `summary` (verdict and the
count of blocking findings) as last-line JSON.
