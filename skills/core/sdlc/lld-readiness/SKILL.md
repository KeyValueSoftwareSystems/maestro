---
name: lld-readiness
description: Check that a feature's repository LLDs (and test cases, when supplied) are ready to implement — no design decision left to the implementer, every repository consistent with the contract and with each other, every acceptance criterion covered. Read-only; writes a readiness report. Front door for /lld-readiness.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, review, lld]
---

# lld-readiness

An implementation agent builds exactly what an LLD says. This check makes sure it can do so
without guessing. It is not a second architecture review: the architecture was reviewed and
approved with the HLD. Read-only — never edit the designs.

## Inputs

Your instructions name the approved HLD, the contract (when one exists), every repository LLD,
the functional test cases when they exist, and the requirement's acceptance criteria. Standalone? read the
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
- **Acceptance coverage** — every acceptance criterion maps to a section of some LLD (and, when
  your instructions supply test cases, to at least one of them); name any criterion with no home.
- **Verifiable increments** — each implementation sequence step leaves the repository buildable
  and testable, and the verification section names real test seams.
- **Infrastructure ownership** — when the HLD lists infrastructure changes, each one has an LLD in
  the repository that owns that infrastructure, with its per-environment values, and the
  application LLDs consume what it provisions under the same names.

**Confirmed decisions.** Your instructions may supply the decisions the person confirmed. A
confirmed decision is not a finding by itself; raise one only when it breaks a requirement, and
say in the finding that it overrides a confirmed decision so the author escalates it.

## Findings

```
- severity: blocking | major | minor
  area: open-decision | contract | cross-repo | coverage | sequencing | infrastructure
  location: <repository LLD section, or test case>
  evidence: <quote or gap>
  recommendation: <the decision or edit needed>
```

Each finding has one severity, the same in the report and the findings file:

- `blocking` — the implementer would have to make a design decision, or would build something
  that breaks the contract, another repository or an acceptance criterion;
- `major` — a real gap the approver should weigh, but implementation can start without it;
- `minor` — wording or a detail that does not change what gets built.

`blocking` is true exactly when a `blocking` finding is open or upheld; the workflow decides from
the findings file. On a re-check after a revision (your instructions point at the previous
report), confirm each earlier finding is resolved and check only what changed.

**Findings file.** When your instructions give a findings path, also write every finding there as
JSON — the workflow decides from this file, not from your prose:
`{"schema_version": 1, "findings": [{"id", "severity": "blocking" | "major" | "minor", "area",
"finding", "evidence", "status": "open" | "upheld" | "withdrawn" | "resolved"}]}`. Keep ids stable
across rounds; new findings get new ids. On a re-review, read the author's resolutions first: mark a
fixed finding `resolved` (or keep it `open` if the fix falls short), and answer each contest —
`withdrawn` when the author is right, `upheld` with your reason when not. A contested finding is
never silently dropped.

## Safety

Read-only. Write only the readiness report and the findings file.

## Output contract

Return `review_path`, literal boolean `blocking`, and `summary` (one line: ready or not, and the
count of blocking findings).
