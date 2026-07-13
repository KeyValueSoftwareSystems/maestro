# Maestro memory — how the harness improves over time

Maestro keeps a durable, file-based, human-readable memory of what it learns about a
codebase. It has **two coexisting surfaces**, both built from the code and kept current by
runs:

1. **The living docs (`docs/`)** — a human-facing knowledge base: per-domain **technical**
   and **functional** documentation plus an **architecture diagram**. `build-knowledge`
   authors it from the codebase; `retrospect` refreshes the touched domains after each
   feature. This is committed documentation the whole team reads, and it is part of the
   workspace every subagent already sees.
2. **The corroborated lessons (`.maestro/memory/`)** — terse learnings **injected** into
   future steps via `${memory.knowledge.*}`, drawn from two things each run reveals: **what
   the user asked to change** (revise/review requests and gate feedback, plus any out-of-band
   instructions captured in the ledger's `notes` — where the run had to be corrected to meet
   the requirement) and **the issues faced while running** (failed/retried steps, loops that
   hit their cap, contract/QA/build breakages). A lesson is only
   trusted once **≥3 distinct runs** corroborate it, and the surface is frozen at `init` so
   runs stay reproducible.

Neither ever makes a running run non-deterministic (see "Reading: frozen at init").

## Surface 1 — the living docs (`docs/`)

Built from the code, organised as a docs tree; committed and human-editable:

```
docs/
├── architecture.md          # Mermaid diagram(s) of every service/component + how they connect
├── technical/
│   ├── auth.md               # per-domain: modules, data model & schemas, APIs, storage, jobs
│   └── order-management.md
└── functional/
    ├── auth.md               # per-domain: what it does, business rules, flows, edge cases
    └── order-management.md
```

- **Domains** are the code's bounded contexts (`auth`, `order-management`, `catalog`, …),
  kebab-case.
- **`docs/architecture.md`** carries one or more ```mermaid diagrams plus a *How services
  connect* section: per edge, the protocol (REST / gRPC / GraphQL / event-queue / shared DB),
  direction, sync vs async, the data that flows, inter-service auth, and which datastore each
  service owns.
- **`build-knowledge`** (`/build-knowledge`) writes the whole tree from the codebase, once
  per workspace, re-runnable (refresh in place). **`retrospect`** updates the touched
  domains + `architecture.md` after a feature. Both are LLM-judgement skills — swap them
  freely; the *structure* is fixed here and in their workflow node instructions, not baked
  into engine code.

## Surface 2 — the corroborated lessons (`.maestro/memory/`)

The injected store lives at `.maestro/memory/` (the repo/umbrella root, alongside
`.maestro/<slug>/`). It is git-tracked and shared across every feature slug in that
workspace.

## The three tiers

```
.maestro/memory/
├── knowledge/                # engine-RENDERED, injected — the ONLY tier runs read
│   ├── codebase.md           # shared facts/conventions — injectable into any step
│   ├── plan.md               # per-consumer: filename == consuming skill name
│   ├── backend-design.md
│   ├── frontend-design.md
│   ├── backend-review.md
│   ├── frontend-review.md
│   └── architecture-review.md
├── candidates/               # engine-owned LEDGER — evidence, not injected
│   └── <domain>.json         # [{key, text, slugs:[...], authoritative}] — count == #slugs
├── incoming/                 # per-run structured drops (race-free write surface)
│   └── <slug>.json           # {"slug","lessons":[{domain,key,text,authoritative?}]}
└── index.md                  # one-line-per-file pointer (engine-rendered)
```

- **`incoming/<slug>.json`** — what one run observed, as structured lessons (a skill's
  output). Raw, per-run.
- **`candidates/<domain>.json`** — the engine's ledger: every lesson, its `text`, the
  DISTINCT slugs that have produced it, and an `authoritative` flag. Read by nothing;
  human-editable if you want to hand-seed or force-promote (set `authoritative: true`).
- **`knowledge/<domain>.md`** — engine-rendered from the ledger: only lessons that qualify
  (authoritative, or seen in ≥ threshold distinct runs). The only tier
  `${memory.knowledge.<domain>}` reads.

### Lesson shape

An incoming drop is structured JSON, keyed so runs corroborate:

```json
{
  "slug": "add-orders",
  "lessons": [
    {"domain": "backend-review", "key": "n-plus-one-list-endpoints",
     "text": "Check for per-row queries in loops before approving."}
  ]
}
```

The engine renders the qualifying lessons into human-readable markdown with provenance:

```markdown
# backend-review — prior lessons

- Check for per-row queries in loops before approving. _(seen: 3 — add-orders, list-invoices, export-report)_
- Migrations must be additive-then-backfill on hot tables. _(authoritative)_
```

The `key` is a stable kebab-case identifier for the *pattern* — a different run seeing the
same pattern should pick the same key; that is how the engine counts corroboration. Bootstrap
lessons carry `"authoritative": true` and render immediately (no threshold).

## Corroboration before promotion

A lesson does **not** become trusted (and start shaping runs) on the strength of a single
run. `engine/mem_consolidate.py` folds each incoming lesson into the `candidates/` ledger,
counting **distinct** runs (a lesson re-observed by the same slug counts once). A candidate
renders into `knowledge/` only once it has been seen in **≥ 3 distinct runs** (the default;
override with `memory.promote_threshold` in an optional `maestro.config.yaml`). Candidates
below threshold stay in the ledger and keep accruing.

Two deliberate bypasses: **bootstrap** (`/build-knowledge`) emits `authoritative: true`
lessons — authoritative seeding from the real code, not anecdote, so they render immediately —
and a **human** may force-promote by setting `authoritative: true` on a ledger entry (or add
one directly). The threshold governs only the automatic retrospect → candidate → knowledge
path.

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

## Writing: functionality in the engine, judgement in the skills

This is the load-bearing separation. Skills are swappable, so **workflow-critical
functionality must not live in a skill.**

- **Skills produce structured observations only.** `retrospect` and `build-knowledge` read a
  run (or the codebase) and emit `incoming/<slug>.json`. That is LLM judgement — what the
  lessons are. Swap either skill for your own or a third party's; as long as it emits the
  same JSON, the memory system is unaffected.
- **The engine owns the mechanics.** `engine/mem_consolidate.py` (a stdlib, tested `script`
  node — the same pattern as `oq_serve.py`) does the counting, corroboration threshold,
  promotion, pruning, and rendering of `knowledge/*.md` + `index.md`. It is the single writer
  of `candidates/` and `knowledge/`. None of this can be broken by replacing a skill.

Per-run drops write ONLY their own `incoming/<slug>.json`, so two runs never contend on a
shared file; consolidation is the single writer of the shared tiers (run it solo). All tiers
are git-tracked, so a bad lesson or merge is reviewable and revertible.

## The lifecycle

```
bootstrap (once/umbrella)  ──►  docs/{technical,functional}/<domain>.md + docs/architecture.md
        │                       (+ seed cross-cutting lessons)            (/build-knowledge)
        ▼
feature run inits ──► freezes lessons snapshot ──► HLD/design/review steps read docs/ + lessons
        │
        ▼
release approved ──► ARCHIVAL PHASE (before merge to master):
        retrospect skill (refresh docs/ for touched domains + architecture.md;
                          this run → incoming/<slug>.json)
          → mem_consolidate.py (incoming/* → candidates/*, promote ≥3 → knowledge/*.md)
          → publish curated docs (.maestro/<slug>/ → committed docs/)
        │
        ▼
human merges the feature branch to master
```

- **Bootstrap** — `/build-knowledge` (workflow `workflows/build-knowledge.yaml`, skill
  `build-knowledge`). Builds the `docs/` knowledge base (Surface 1) and seeds any
  cross-cutting review lessons (Surface 2). Recommended once per workspace; re-runnable.
- **Harvest** — the `retrospect` skill refreshes the touched `docs/` domains + architecture,
  then distills lessons → `incoming/`, and the engine's `mem_consolidate.py` script folds
  them; run by `workflows/retrospect.yaml` (standalone/off-cycle) and inside the archival
  phase.
- **Archival** — `workflows/archive.yaml` (harvest + publish), wired as the pre-merge
  `archive` phase of `sdlc-main.yaml`. Maestro does not perform the merge to master itself;
  archival is the gate that guarantees the harvest and doc-publish happen first.

## Token posture

Injecting lessons costs tokens, bounded four ways: (1) per-domain targeting — a step gets
only its slice, not the whole store; (2) a per-file size cap enforced by `mem_consolidate.py`;
(3) the snapshot is frozen once per run; (4) the bootstrap/retrospect skills run on `haiku`,
and consolidation is a cheap deterministic script (no model).
Keep lessons short and high-signal — every promoted lesson is paid for on every future run
that reads it.
