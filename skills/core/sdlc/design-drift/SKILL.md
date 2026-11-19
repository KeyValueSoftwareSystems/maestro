---
name: design-drift
description: Compare the implemented code with the approved plan before release — its interfaces, decisions, data and design changes, infrastructure and repository scope — and report every place the code departs from it, with evidence. Read-only; writes a drift report and findings. Front door for /design-drift.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, review]
---

# design-drift

Confirm the code that is about to ship is the plan that was approved. Code review checked each
repository against the plan while it was being written; this check runs once at the end, across
every repository, against the whole approved plan. Read-only — never edit code or documents.

## Inputs

Your instructions name the approved plan and the implementation manifest with each repository's exact branch, worktree and commit. Read the
diff of each repository from where its branch left the main line to the listed commit. Standalone?
compare the branches the user names against the plan or design documents they name, and write the report
to a path you choose (and tell the user where).

## Checks

- **Interfaces** — every operation, field, type, status code, error shape and event in the plan's
  Interfaces is implemented by its owner and called by its consumers exactly as written; nothing
  extra is exposed that the plan does not define.
- **Decisions** — each decision the plan records is what the code does: ownership, data store,
  sync vs async, caching, retries, failure behaviour.
- **Design and data** — each repository's changes match the plan's Design; migrations and
  schemas match its data model; no unplanned table, column or index; destructive changes only
  where the plan names them.
- **Infrastructure** — every change in the plan's Infrastructure exists in the repository that
  owns it, with the planned values; no unplanned infrastructure.
- **Scope** — only the repositories the plan names changed; no feature, endpoint or behaviour
  beyond the approved scope or its Out of scope; nothing approved left out.

A difference is drift only when the code departs from the approved plan. Equivalent
implementation detail the plan left open is not drift — a short plan leaves much open.

## Findings

Write the report, and the findings file your instructions give, as JSON:
`{"schema_version": 1, "findings": [{"id", "severity": "blocking" | "major" | "minor", "area":
"contract" | "decision" | "data" | "infrastructure" | "scope", "finding", "evidence", "status":
"open"}]}`. Evidence is `repo:path:line` in the diff plus the plan text it contradicts. Use
`blocking` for drift that changes behaviour a consumer, a user or an operator relies on — an
interface mismatch, a missing planned change, an unplanned destructive migration. For each finding
say whether the code or the plan should change.

## Safety

Read-only. Never edit code, branches, documents or run state; write only the report and findings
files your instructions name.

## Output contract

Return `review_path` (the report), `blocking` (true when any blocking drift remains) and `summary`
(one line: how many drift findings, by area, and the headline one).
