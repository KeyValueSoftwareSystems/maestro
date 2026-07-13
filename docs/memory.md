# Maestro memory — how the harness improves over time

Maestro keeps a durable, file-based, human-readable **memory** of what it learns about a
codebase. Lessons distilled from finished runs are accumulated and injected into future runs
— so design and review get sharper over time — without ever making a running run
non-deterministic.

The store lives at `.maestro/memory/` (the repo/umbrella root, alongside `.maestro/<slug>/`).
It is git-tracked and shared across every feature slug in that workspace.

## The three tiers

```
.maestro/memory/
├── knowledge/                # PROMOTED, trusted lessons — the ONLY tier injected into runs
│   ├── codebase.md           # shared facts/conventions — injectable into any step
│   ├── plan.md               # per-consumer: filename == consuming skill name
│   ├── backend-design.md
│   ├── frontend-design.md
│   ├── backend-review.md
│   ├── frontend-review.md
│   └── architecture-review.md
├── candidates/               # STAGING — lessons seen but not yet corroborated (NOT injected)
│   └── <domain>.md           # each lesson carries an observation count + source slugs
├── incoming/                 # per-run retrospective drops (race-free write surface)
│   └── <slug>.md             # one file per run; never edited by two runs at once
└── index.md                  # one-line-per-file pointer, human-scannable
```

- **`incoming/<slug>.md`** — what one run's retrospective observed. Raw, per-run.
- **`candidates/<domain>.md`** — lessons accumulating evidence (an observation count + the
  distinct slugs that produced each). Read by nothing.
- **`knowledge/<domain>.md`** — lessons that reached the corroboration threshold. The only
  tier `${memory.knowledge.<domain>}` reads.

### Lesson shape

A domain file is a flat list of short, actionable lessons, each with provenance:

```markdown
# backend-review — prior lessons

- Reviewers repeatedly flag N+1 queries in list endpoints; check for per-row queries in
  loops before approving. _(seen: 3 — add-orders, list-invoices, export-report)_
- Migrations must be additive-then-backfill, never in-place column renames on the hot table.
  _(seen: 2 — split-users-table, shard-accounts)_
```

A `candidates/<domain>.md` entry is the same shape but still below threshold — it records its
running count and sources so the next run can corroborate it.

## Corroboration before promotion

A lesson does **not** become trusted (and start shaping runs) on the strength of a single
run. Consolidation folds each incoming lesson into `candidates/`, counting **distinct** runs
(a lesson repeated within one run counts once). A candidate promotes into `knowledge/` only
once it has been seen in **≥ 3 distinct runs** (the default; override with
`memory.promote_threshold` in an optional `maestro.config.yaml`, read by the consolidate
skill — not the engine). Candidates that never reach the threshold age out.

Two deliberate bypasses: **bootstrap** (`/build-knowledge`) writes `knowledge/` directly —
it is authoritative seeding from the real code, not anecdote — and a **human** may
hand-promote or hand-write a `knowledge/` lesson. The threshold governs only the automatic
retrospect → candidate → knowledge path.

Why the threshold matters: without it, a single run's idiosyncrasy (a reviewer's one-off nit,
a flake specific to one feature) would immediately start steering every future run. Requiring
independent corroboration keeps `knowledge/` to patterns the codebase actually exhibits
repeatedly — the difference between a lesson and an anecdote.

## Reading: frozen at init

Workflow steps pull their slice of memory via a placeholder, e.g.
`inputs: {lessons: "${memory.knowledge.backend-review}"}`. The engine injects it into the
**subagent** prompt — the lead agent's context stays empty.

The rule that keeps runs reproducible: **memory is read once, at `init`, snapshotted into the
run (`.maestro/<slug>/memory-snapshot.json`, hash recorded in `state.memory`), and resolved
from that snapshot for the whole run — never re-read from the live store mid-run.** So a run
is a pure function of its `state.yaml` + the pinned workflow + the frozen snapshot, and a
concurrent run consolidating the shared store cannot perturb a run already in flight. Learning
influences the *next* run, at its own init.

Resolution is lenient: a missing domain resolves to the empty string, so a fresh repo with no
store behaves exactly as before — the feature is inert and free until lessons accrue.
Placeholders may nest (`${memory.knowledge.${inputs.stack}-review}`) for stack-parameterized
steps.

## Writing: the map-reduce model

Per-run retrospectives write ONLY their own `incoming/<slug>.md`, so two runs never contend
on a shared file. **Consolidation is the single writer of `candidates/` and `knowledge/`.**
Run consolidation solo (do not overlap two consolidations). All tiers are git-tracked, so a
bad lesson or a bad merge is reviewable and revertible.

## The lifecycle

```
bootstrap (once/umbrella)  ──►  knowledge/ seeded from the existing codebase   (/build-knowledge)
        │
        ▼
feature run inits ──► freezes knowledge snapshot ──► HLD/design/review steps read it
        │
        ▼
release approved ──► ARCHIVAL PHASE (before merge to master):
        retrospect (this run → incoming/<slug>.md)
          → consolidate (incoming/* → candidates/*, promote ≥3 → knowledge/*)
          → publish curated docs (.maestro/<slug>/ → committed docs/)
        │
        ▼
human merges the feature branch to master
```

- **Bootstrap** — `/build-knowledge` (workflow `workflows/build-knowledge.yaml`, skill
  `build-knowledge`). Recommended once per workspace; re-runnable and merges.
- **Harvest** — the `retrospect` → `consolidate-memory` skills, run by
  `workflows/retrospect.yaml` (standalone/off-cycle) and inside the archival phase.
- **Archival** — `workflows/archive.yaml` (harvest + publish), wired as the pre-merge
  `archive` phase of `sdlc-main.yaml`. Maestro does not perform the merge to master itself;
  archival is the gate that guarantees the harvest and doc-publish happen first.

## Token posture

Injecting lessons costs tokens, bounded four ways: (1) per-domain targeting — a step gets
only its slice, not the whole store; (2) a per-file size cap enforced by consolidation;
(3) the snapshot is frozen once per run; (4) bootstrap/retrospect/consolidate run on `haiku`.
Keep lessons short and high-signal — every promoted lesson is paid for on every future run
that reads it.
