---
name: architecture-review
description: Review a high-level design before it is approved, as a reviewer who did not write it — architecture style, boundaries, interfaces, security, failure, scale, operations, and over- or under-engineering — with evidence-backed findings and a blocking verdict. Read-only; writes a review artifact. Front door for /architecture-review.
allowed-tools: Read, Grep, Glob, Bash, Task, Write
tags: [sdlc, review]
---

# architecture-review

Catch architecture problems while they cost one document edit, before detailed designs and code
are built on them. You review the HLD as someone who did not write it: judge the design, not the
prose. Read-only — never edit the design or code.

## Inputs

Your instructions name the HLD, the approved requirement, and the maintained architecture
summaries and codebase maps. Read source only to check a specific claim. Standalone? review the
HLD the user names and write the report to a path you choose (and tell the user where).

## Checklist

- **Fit to the requirement** — every acceptance criterion and stated constraint has a place in the
  design; nothing important is left undefined.
- **Architecture style** — the chosen shape (modular monolith, separate services, event-driven,
  serverless) is justified by the requirement's load, independence or ownership needs. Flag both
  under-engineering (no plan for the stated peak, a single point of failure on a critical path)
  and over-engineering (new services, queues or caches with no requirement that needs them).
- **Boundaries and data** — clear ownership, one source of truth per piece of state, no hidden
  coupling between repositories.
- **Interfaces** — every cross-repository call or event is listed with owner, caller, sync or
  async; nothing in the design crosses a boundary without appearing there.
- **Security and privacy** — authentication and authorization model, tenant isolation, sensitive
  data, new trust boundaries.
- **Failure and recovery** — timeouts, retries, idempotency, partial failure, backpressure,
  degradation, data consistency where only eventual consistency is available.
- **Scale and performance** — expected load against the design's mechanisms (caching,
  partitioning, async work, rate limits); unbounded work on hot paths. When the requirement
  states non-functional targets (volume, response time, availability, retention), each one needs
  a mechanism in the design that meets it; a target the design cannot meet or ignores is
  blocking.
- **Operations** — deployment and rollout, backout, migration safety, observability, cost.
- **Infrastructure** — only when the workspace defines it (your instructions supply the level):
  the Infrastructure and operations section against the infrastructure repositories and the
  detected platforms — capacity and autoscaling bounds against the targets and downstream limits
  (database connections at max replicas), failure domains, secrets handling, network exposure,
  stateful changes that would replace or destroy data, and rollout order across repositories.
  In a workspace without infrastructure definitions, raise no infrastructure findings beyond
  what the requirement's targets need.

Use the `architecture-patterns` skill and the matching infrastructure pack as the reference for
what a sound choice looks like.
- **Alternatives** — material choices name the alternative they rejected and why.

## Findings

Each finding needs evidence — the quoted design text, or the requirement it fails — and the
smallest design change that fixes it:

```
- severity: blocker | major | minor | suggestion
  area: fit | style | boundaries | interfaces | security | failure | scale | operations | alternatives
  location: <HLD section>
  evidence: <quote or gap>
  recommendation: <design change>
```

Sort blocker → major → minor → suggestion. `blocking=true` when any blocker or major remains.

**Re-review.** When your instructions point at a previous review (a re-review after a revision),
read it first: confirm each earlier blocking finding is resolved and check only what changed and
its consistency with the rest. Do not re-audit unchanged sections or raise new minor findings on
them.

**Findings file.** When your instructions give a findings path, also write every finding there as
JSON — the workflow decides from this file, not from your prose:
`{"schema_version": 1, "findings": [{"id", "severity": "blocking" | "major" | "minor", "area",
"finding", "evidence", "status": "open" | "upheld" | "withdrawn" | "resolved"}]}`. Use `blocking`
for what must change before approval (a blocker, or a major that cannot wait). Keep ids stable
across rounds; new findings get new ids. On a re-review, read the author's resolutions first: mark a
fixed finding `resolved` (or keep it `open` if the fix falls short), and answer each contest —
`withdrawn` when the author is right, `upheld` with your reason when not. A contested finding is
never silently dropped.

## Safety

Read-only. Write only the review report.

## Output contract

Return `review_path`, literal boolean `blocking`, and `summary` (one line: the verdict and the
count of blocking findings).
