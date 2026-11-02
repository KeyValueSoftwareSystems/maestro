---
name: design-drift
description: Compare the implemented code with the approved design before release — HLD decisions, the API contract, each repository's LLD and the infrastructure changes — and report every place the code departs from it, with evidence. Read-only; writes a drift report and findings. Front door for /design-drift.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, review]
---

# design-drift

Confirm the code that is about to ship is the design that was approved. Code review checked each
repository against its LLD while it was being written; this check runs once at the end, across
every repository, against the whole approved design. Read-only — never edit code or documents.

## Inputs

Your instructions name the approved HLD, the contract (when one exists), each repository's LLD,
and the implementation manifest with each repository's exact branch, worktree and commit. Read the
diff of each repository from where its branch left the main line to the listed commit. Standalone?
compare the branches the user names against the design documents they name, and write the report
to a path you choose (and tell the user where).

## Checks

- **Contract** — every operation, field, type, status code, error shape and event in the contract
  is implemented by its owner and called by its consumers exactly as written; nothing extra is
  exposed that the contract does not define.
- **Design decisions** — each HLD key decision and each LLD's proposed changes are what the code
  does: ownership, data store, sync vs async, caching, retries, failure behaviour.
- **Data** — migrations and schemas match the LLD's data model; no unplanned table, column or
  index; destructive changes only where the LLD planned them.
- **Infrastructure** — every change in the HLD's Infrastructure and operations section exists in
  the repository that owns it, with the planned values; no unplanned infrastructure.
- **Scope** — no feature, endpoint or behaviour beyond the approved scope; nothing approved left
  out.

A difference is drift only when the code departs from the approved design. Equivalent
implementation detail the design left open is not drift.

## Findings

Write the report, and the findings file your instructions give, as JSON:
`{"schema_version": 1, "findings": [{"id", "severity": "blocking" | "major" | "minor", "area":
"contract" | "decision" | "data" | "infrastructure" | "scope", "finding", "evidence", "status":
"open"}]}`. Evidence is `repo:path:line` in the diff plus the design text it contradicts. Use
`blocking` for drift that changes behaviour a consumer, a user or an operator relies on — a
contract mismatch, a missing planned change, an unplanned destructive migration. For each finding
say whether the code or the design should change.

## Safety

Read-only. Never edit code, branches, documents or run state; write only the report and findings
files your instructions name.

## Output contract

Return `review_path` (the report), `blocking` (true when any blocking drift remains) and `summary`
(one line: how many drift findings, by area, and the headline one).
