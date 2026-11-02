---
name: lld-readiness
description: Check that a feature's repository LLDs and test cases are ready to implement — no design decision left to the implementer, every repository consistent with the contract and with each other, every acceptance criterion covered. Read-only; writes a readiness report. Front door for /lld-readiness.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, review, lld]
---

# lld-readiness

An implementation agent builds exactly what an LLD says. This check makes sure it can do so
without guessing. It is not a second architecture review: the architecture was reviewed and
approved with the HLD. Read-only — never edit the designs.

## Inputs

Your instructions name the approved HLD, the contract (when one exists), every repository LLD,
the functional test cases, and the requirement's acceptance criteria. Standalone? read the
documents the user names and write the report to a path you choose (and tell the user where).

## Checks

- **Zero decisions left** — a competent engineer who does not know this codebase could implement
  each LLD without choosing a schema, an API shape, a library, an error-handling strategy or an
  edge-case behavior. Every such choice already made in the LLD is fine; every choice still open
  is a finding.
- **Contract consistency** — each LLD implements or calls the contract exactly as written: same
  operations, fields, types, errors and pagination. An LLD never redefines the contract.
- **Cross-repository consistency** — a producer's LLD and its consumers' LLDs agree on ordering,
  states, retries and error handling for every interface they share.
- **Acceptance coverage** — every acceptance criterion maps to a section of some LLD and to at
  least one test case; name any criterion with no home.
- **Verifiable increments** — each implementation sequence step leaves the repository buildable
  and testable, and the verification section names real test seams.

## Findings

```
- severity: blocker | major | minor
  area: open-decision | contract | cross-repo | coverage | sequencing
  location: <repository LLD section, or test case>
  evidence: <quote or gap>
  recommendation: <the decision or edit needed>
```

`blocking=true` when any blocker or major remains. On a re-check after a revision (your
instructions point at the previous report), confirm each earlier finding is resolved and check only
what changed.

## Safety

Read-only. Write only the readiness report.

## Output contract

Return `review_path`, literal boolean `blocking`, and `summary` (one line: ready or not, and the
count of blocking findings).
