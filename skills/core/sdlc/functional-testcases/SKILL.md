---
name: functional-testcases
description: Author a FUNCTIONAL test-case catalog (human-readable, black-box) for a feature from its requirement alone — one case per behavior a user or client can observe, positive + negative + edge, each traced to the acceptance criterion it verifies and stated in the requirement's own terms. Black-box QA source of truth, NOT automation code. Reads the requirement, never the design; writes the catalog; never edits app code. Front door for /functional-testcases.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, design, qa]
---

# functional-testcases — functional test-case catalog

Turn the approved requirement into a **functional test-case catalog**: black-box cases derived
from **what the requirement says a user or client observes**, never from the design or the
implementation. Each case is a plain-language spec a human can execute by hand and that the QA
step later automates or checks. Write cases only; never edit app code, never write automation
code or framework specs (that is the QA step's job). Every case must be justified by an
acceptance criterion.

The catalog answers *what must be true*, not *how the system says it*: the design (HLD, contract,
LLDs) settles exact status codes, error codes, field names and messages, and the QA step looks
them up there when it runs a case. Keeping the catalog to the requirement means a design change
never rewrites it, and a design that cannot meet a case shows up as a failing case, not as a
case quietly bent to fit.

## Inputs
Your instructions name the requirement to read (its acceptance criteria) and the artifact path
to write the catalog. Do not read the design documents even when they exist. Standalone? read the
requirement and write to a path you choose (and tell the user where).

## Steps
1. **Read** the requirement. List every acceptance criterion — each is a thing a case must cover.
2. **Derive journeys** — group behaviors into user/client journeys. Rank by risk tier
   (critical / high / normal) so the QA step knows what to run first.
3. **Write one case per observable behavior** (template below): the primary happy path for each
   journey, then the negative and edge behaviors the acceptance criteria state or directly imply.
4. **Trace** every case back to the acceptance criterion id(s) it verifies — no untraceable
   case, no uncovered criterion.
5. **State scope** — what is explicitly out of scope (non-functional load/perf, exploratory),
   and any assumption a case depends on.

## Test-case template (every case)
Start each case with a heading whose first word is its ID (`### TC-<slug>-001 — <title>`), so a
checker can find every case and what it traces; journey headings sit one level above the cases.
- **ID** — stable, e.g. `TC-<slug>-001`.
- **Title** — the behavior in one line.
- **Type** — positive | negative | edge.
- **Priority / risk tier** — critical | high | normal.
- **Preconditions** — required state / seeded data / who the user is and what they may do.
- **Steps** — numbered, black-box (what a user/client does), no internals.
- **Expected result** — the observable outcome in the requirement's terms (what the user sees,
  what is refused, what changes, what is kept). Quote a value only when the requirement states
  it (a limit, a wording); never invent a status code, error code or field name.
- **Test data** — the inputs the case seeds (self-contained; no shared mutable state).
- **Traces** — acceptance-criterion id(s) written exactly as the requirement writes them
  (`AC-01`). Never invent or renumber a criterion id.

## Coverage standards (the catalog must satisfy)
- **Every acceptance criterion** has ≥1 case.
- **Negatives & edges the requirement implies** — the refusal or failure each criterion names,
  stated limits and their boundaries (at, just over), empty/missing input, duplicate submission.
- **Who may do it** — when a criterion limits an action to some users, a case for a user who
  may not.
- **Frontend-observable states** — loading, empty, error, and "many items"/pagination where the
  feature has UI and the requirement describes it.
- **No invented scope** — a behavior no acceptance criterion states or implies is not a case
  (it belongs in the requirement first).
- **Deterministic & isolated** — each case seeds and tears down its own data; order-independent;
  no case depends on another's leftovers.
- **Safe** — seeded test data only; never real secrets or production data.

## Output — write this artifact
Write the catalog to the path your instructions specify, containing:
- A short **header**: feature, scope, out-of-scope, data strategy, risk-tier legend.
- A **coverage matrix** mapping each acceptance criterion → the case IDs that cover it (prove
  nothing is uncovered).
- The **cases**, grouped by journey, each following the template above.

When your instructions supply trace feedback (an uncovered criterion, or an id the requirement
does not have), fix exactly that: add or correct the cases named, keep every other case as is.

## Definition of done
Every acceptance criterion is covered by ≥1 traceable case; its negatives and edges are present
(not "TBD"); each case is black-box, in the requirement's terms, self-contained and
deterministic; scope and out-of-scope stated. Do not automate — the QA step turns this catalog
into executable checks.

## Output contract
Return `test_cases_path`, `case_count`, and `coverage_summary` (2–3 sentences: journeys
covered, notable negatives/edges, anything deferred).
