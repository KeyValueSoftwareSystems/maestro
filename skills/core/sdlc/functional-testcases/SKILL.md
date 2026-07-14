---
name: functional-testcases
description: Author a FUNCTIONAL test-case catalog (human-readable, black-box) for a feature by deriving cases from the acceptance criteria, the HLD, and the cross-repo contract — one case per behavior a user or client can observe, positive + negative + edge, each traceable to the criterion/operation it verifies. Black-box QA source of truth, NOT automation code. Reads the design artifacts; writes the catalog; never edits app code. Front door for /functional-testcases.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, design, qa]
---

# functional-testcases — functional test-case catalog

Turn the approved design into a **functional test-case catalog**: black-box cases derived from
**observable behavior** (the acceptance criteria + the contract's operations), not from the
implementation. Each case is a plain-language spec a human can execute by hand and that the QA
automation step later automates. Write cases only; never edit app code, never write automation
code or framework specs (that is the automation step's job). Every case must be justified by an
acceptance criterion or a contract operation — never derive cases from internals.

## Inputs
Your instructions name what to read — the HLD, the cross-repo contract, and the acceptance
criteria — and the artifact path to write the catalog. Standalone? read them and write to a
path you choose (and tell the user where).

## Steps
1. **Read** the acceptance criteria, HLD, and contract. List every acceptance criterion and
   every contract operation (method/path or event) — these are the things a case must cover.
2. **Derive journeys** — group behaviors into user/client journeys. Rank by risk tier
   (critical / high / normal) so the automation step knows what to automate first.
3. **Write one case per observable behavior** (template below): the primary happy path for each
   journey, then the negative and edge behaviors the contract and acceptance criteria define.
4. **Trace** every case back to the acceptance criterion id and/or contract operation it
   verifies — no untraceable case, no uncovered criterion.
5. **State scope** — what is explicitly out of scope (non-functional load/perf, exploratory),
   and any assumption a case depends on.

## Test-case template (every case)
- **ID** — stable, e.g. `TC-<slug>-001`.
- **Title** — the behavior in one line.
- **Type** — positive | negative | edge.
- **Priority / risk tier** — critical | high | normal.
- **Preconditions** — required state / seeded data / auth & permission.
- **Steps** — numbered, black-box (what a user/client does), no internals.
- **Expected result** — observable outcome + the contract outcome it must match (status,
  error envelope, side effect).
- **Test data** — the inputs the case seeds (self-contained; no shared mutable state).
- **Traces** — acceptance-criterion id(s) and/or contract operation(s) covered.

## Coverage standards (the catalog must satisfy)
- **Every acceptance criterion** has ≥1 case; **every contract operation** has a happy case
  and its defined error cases.
- **Negatives & edges from the contract** — empty/missing/null inputs, oversized payloads,
  duplicate submissions, pagination boundaries (first/last/empty page), unstable ordering.
- **Authz** — permission-denied, expired/insufficient-scope token, cross-tenant attempt.
- **Limits & resilience** — rate-limit exhaustion (429 + retry-after), downstream error
  surfaced to the client, session expiry mid-flow, concurrent/double-submit where allowed.
- **Frontend-observable states** — loading, empty, error, and "many items"/pagination where the
  feature has UI.
- **Deterministic & isolated** — each case seeds and tears down its own data; order-independent;
  no case depends on another's leftovers.
- **Safe** — seeded test data only; never real secrets or production data.

## Output — write this artifact
Write the catalog to the path your instructions specify, containing:
- A short **header**: feature, scope, out-of-scope, data strategy, risk-tier legend.
- A **coverage matrix** mapping each acceptance criterion / contract operation → the case IDs
  that cover it (prove nothing is uncovered).
- The **cases**, grouped by journey, each following the template above.

## Definition of done
Every acceptance criterion and contract operation is covered by ≥1 traceable case; negatives,
edges, and authz paths are present (not "TBD"); each case is black-box, self-contained, and
deterministic; scope and out-of-scope stated. Do not automate — the automation step turns this
catalog into the executable E2E suite.

## Output contract
Return `test_cases_path`, `case_count`, and `coverage_summary` (2–3 sentences: journeys
covered, notable negatives/edges, anything deferred).
