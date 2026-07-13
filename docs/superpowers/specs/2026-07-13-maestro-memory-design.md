# Maestro Memory — design spec

**Date:** 2026-07-13
**Status:** Approved (design); implementation not yet started
**Scope:** Foundation + consolidation (Mode 1 of the improvement roadmap), plus a
codebase-scanning **bootstrap** that creates initial domain knowledge, and a **pre-merge
archival phase** that harvests the finished feature into memory and publishes its docs
before the feature branch merges to master. Self-tuning workflows/skills (Mode 2) and
routing/model learning (Mode 3) are explicitly out of scope and layer on later.

The knowledge lifecycle this build delivers:

```
bootstrap (once/umbrella)  ──►  knowledge/ seeded from the existing codebase
        │
        ▼
feature run inits ──► freezes knowledge snapshot ──► HLD/design/review steps read it
        │
        ▼
release approved ──► ARCHIVAL PHASE (before merge to master):
        retrospect (this run → incoming/<slug>.md)
          → consolidate (incoming/* → knowledge/*)
          → publish curated docs (.maestro/<slug>/ → committed docs/)
        │
        ▼
human merges the feature branch to master
```

## Goal

Give Maestro a durable, file-based, human-readable **memory** so that lessons learned in
one feature run are distilled, accumulated, and injected into future runs — making the
harness improve over time — without breaking the two invariants the engine depends on:

1. **Determinism / reproducibility.** A run is a pure function of its frozen `state.yaml`
   plus the sha256-pinned workflow file. Memory must not make a running run
   non-reproducible or change its behavior mid-flight.
2. **Context discipline.** The lead agent never reads produced content into its own
   context; it routes only on small JSON scalars. Memory is injected into *subagent*
   prompts, never accumulated in the driver.

Memory is stored per umbrella/repo root and shared across every slug in that umbrella.

## Non-goals (YAGNI)

- No vector store / semantic retrieval. File-based only.
- No engine-authored edits to workflows or skills. Any self-tuning (later) is
  proposal-artifact + human-gate.
- No routing/model learning in this build.
- No always-on cost: an unseeded store makes the feature inert and free.

## The store

Root: `.maestro/memory/` (the umbrella/repo root — the same level as `.maestro/<slug>/`).

```
.maestro/memory/
├── knowledge/                # PROMOTED, trusted lessons — the ONLY read surface (injected)
│   ├── codebase.md           # shared facts/conventions — injectable into any step
│   ├── plan.md               # per-consumer: filename == consuming skill name
│   ├── backend-design.md
│   ├── frontend-design.md
│   ├── backend-review.md
│   ├── frontend-review.md
│   └── architecture-review.md
├── candidates/               # STAGING — lessons seen but not yet corroborated (NOT injected)
│   └── <domain>.md           # each lesson carries an observation count + source slugs
├── incoming/                 # per-run retrospective drops (the race-free write surface)
│   └── <slug>.md             # one file per run; never edited by two runs at once
└── index.md                  # one-line-per-file pointer, human-scannable
```

The three tiers implement **corroboration before promotion** — a lesson only becomes
trusted (and starts shaping runs) once *multiple* runs agree on it, never from a single run:

- **`incoming/<slug>.md`** — what one run's retrospective observed. Raw, per-run, race-free.
- **`candidates/<domain>.md`** — lessons accumulating evidence. Each entry tracks an
  observation count and the distinct slugs that produced it. Not read by any step.
- **`knowledge/<domain>.md`** — lessons that reached the corroboration threshold. This is the
  only tier `${memory.knowledge.*}` reads.

Properties:

- **Git-tracked, Markdown, human-editable.** Reviewable in PRs; a bad lesson is a one-line
  revert.
- **Provenance on every lesson.** Each entry records the originating `<slug>`, an absolute
  date, and the source (e.g. which review artifact it came from).
- **map-reduce write model.** Per-run retrospectives write ONLY their own
  `incoming/<slug>.md` — so no two runs ever contend on a shared file. Consolidation is the
  single writer of `candidates/*`, `knowledge/*`, and `index.md`. This is how the shared-store
  concurrency risk is eliminated rather than locked around.
- **Fresh repo = empty store.** No `knowledge/` files → every `${memory.*}` resolves to the
  empty string → prompts are byte-identical to today. Zero cost until lessons accrue.
- **Two ways `knowledge/` gets populated:** the one-time **bootstrap** (below) seeds it
  directly from the existing codebase; thereafter **consolidation** promotes per-run lessons
  into it, but only once they clear the corroboration threshold (below). Both write the same
  files in the same shape.

### `knowledge/<domain>.md` shape

A domain file is a flat list of lessons. Each lesson is short (a claim + why it matters +
provenance). Example:

```markdown
# backend-review — prior lessons

- Reviewers repeatedly flag N+1 queries in list endpoints; check for per-row queries in
  loops before approving. _(seen: 3 — add-orders, list-invoices, export-report)_
- Migrations must be additive-then-backfill, never in-place column renames on the hot table.
  _(seen: 2 — split-users-table, shard-accounts)_
```

A `candidates/<domain>.md` entry is the same shape but still below threshold — it records its
running count and sources so the next run can corroborate it:

```markdown
# backend-review — candidates (not yet trusted)

- Prefer cursor pagination over offset for endpoints returning >1k rows. _(seen: 1 — add-orders)_
```

## Bootstrap — building initial domain knowledge (the prerequisite)

Retrospectives only accumulate lessons *after* runs; a brand-new umbrella would start cold.
The bootstrap creates the initial `knowledge/` by scanning the existing code, so the very
first feature run already has domain context to build its idea on.

- **`skills/build-knowledge/SKILL.md`** — reads the repos under `codebase/` (or the single
  repo), each repo's `CLAUDE.md` / `.cursor/rules`, the centralised `docs/`, and salient
  structure (entry points, build/test commands, house style, recurring patterns), and writes
  the initial `knowledge/codebase.md` plus per-domain seeds (`plan.md`, `backend-design.md`,
  `backend-review.md`, …) with provenance tagged `bootstrap`.
- **`workflows/build-knowledge.yaml`** — a maestro workflow so it can fan out per repo/stack
  and run on a cheap model; also invocable standalone as `/build-knowledge`.
- **Run once per umbrella, re-runnable.** It is a **recommended prerequisite, not a hard
  gate** — an empty store is inert (fresh-repo behavior above), so feature runs still work
  without it; they just get no injected knowledge until it exists. (A hard prerequisite was
  considered and rejected: it would block first use and fight the zero-cost-when-empty
  property.)
- **Write target:** bootstrap writes `knowledge/*` **directly** (it is the initial author,
  run solo as a setup step) — unlike retrospectives, which only stage into `incoming/`.
  Re-running bootstrap on an existing store MERGES (does not clobber) via the same
  consolidation discipline, so human edits and accrued lessons survive.

## Read path — `${memory.knowledge.<domain>}`

A fifth placeholder namespace alongside `${inputs.*}`, `${steps.*.outputs.*}`,
`${steps.*.branches.*.outputs.*}`, `${config.*}`.

Usage in a workflow node:

```yaml
- id: review
  skill: backend-review
  inputs: {lessons: "${memory.knowledge.backend-review}"}
```

`render_agent_prompt` (resolver.py) already injects declared `inputs:` into the subagent
prompt. The subagent receives the lessons; the lead agent does not.

**Resolution is lenient** (same class as agent-instruction / gate-prompt / step-input
substitution today): a missing domain file resolves to the empty string rather than
aborting the run. This keeps unseeded domains and fresh repos working.

**Idea-building reads knowledge from the start.** The snapshot is frozen at feature `init`
(below), so the earliest idea-forming step — the `plan`/HLD step — already has the domain
knowledge available. `plan` consumes `${memory.knowledge.codebase}` (shared domain context)
+ `${memory.knowledge.plan}` (planning lessons), so the feature's idea is grounded in what
the bootstrap and prior runs learned about this codebase. No separate framing step is added;
the HLD step is the grounding point.

### Determinism: freeze at init

The rule: **read memory once at `init`, snapshot it into the run, resolve from the snapshot
thereafter — never re-read the live store mid-run.**

Rationale: `${config.*}` is re-read on every CLI invocation (`Run.__init__` →
`_load_config`), which would make a run's behavior drift whenever the shared store changes
(e.g. another slug's consolidation). Memory must NOT behave that way. Freezing at init
means:

- A run remains a pure function of `state.yaml` + pinned workflow + the frozen snapshot.
- Concurrent runs writing the shared store cannot perturb a run already in flight.
- Learning influences the *next* run (at its own init), never a running one.

**Mechanism (recommended):** at `init`, copy the current `knowledge/*` into a per-run
snapshot file `.maestro/<slug>/memory.snapshot.<ext>` and record its sha256 under
`state["memory"]`. `${memory.knowledge.<domain>}` resolves by reading that frozen snapshot
(cached on the `Run` object). This keeps the hot-path `state.yaml` writes small.
**Alternative** considered: store the consumed content inline under `state["memory"]` in the
ledger (fully self-contained, but bloats every state write). The implementation plan will
settle which; both satisfy the freeze rule.

Unlike the workflow-file hash (which HALTS the run on mid-run change), the memory snapshot
does NOT halt on live-store changes — it simply ignores them, because the store is expected
to change between runs and is shared. The recorded hash is for audit/reproducibility, not a
gate.

## Write path — the retrospective

Shipped forms:

1. **`skills/retrospect/SKILL.md`** — standalone `/retrospect <slug>`.
2. **`workflows/retrospect.yaml`** — a two-node maestro workflow: `retrospect → consolidate`
   (harvest without publishing; for manual/off-cycle use).
3. **Inside the pre-merge archival phase** (below) — the primary, default integration: the
   `archive` phase of `sdlc-main.yaml` runs `retrospect → consolidate` as its first steps.

What the retrospective skill does:

- **Inputs it reads** (as a subagent, so reading is allowed): the finished run's
  `.maestro/<slug>/state.yaml` — specifically the `gates:` list (human decisions +
  `feedback`/`guidance` free text), per-step `visits`/`attempts`/`status` (loop escalations,
  retries), and the run's review/QA artifacts under `.maestro/<slug>/`.
- **What it distills:** recurring human overrides, blocking findings that keep recurring,
  loops that repeatedly hit their cap, tests that flaked — turned into short, actionable,
  provenance-tagged lessons, bucketed by consuming domain (which skill would benefit).
- **Output:** writes `.maestro/memory/incoming/<slug>.md` (a declared artifact, so the
  engine's non-empty completion guarantee applies) and returns a short scalar summary.

The retrospective NEVER writes `knowledge/*` directly — only `incoming/`.

## Consolidation — `skills/consolidate-memory`

The reduce step, the token-budget guardrail, and the enforcer of **corroboration before
promotion**.

- **Inputs:** all `incoming/*` files + existing `candidates/*` + existing `knowledge/*`.
- **Step 1 — fold incoming into candidates.** For each lesson in `incoming/*`, match it
  against existing `candidates/<domain>.md` entries (near-duplicate / same-claim match). If it
  matches, **increment the observation count and append the new source slug** (counting
  DISTINCT slugs — a lesson repeated within one run does not self-corroborate). If it is new,
  add it as a candidate with count = 1. Then clear `incoming/`.
- **Step 2 — promote corroborated candidates.** Any candidate whose distinct-slug count
  reaches the **promotion threshold** (default **3** — i.e. seen in ≥3 separate runs;
  configurable, see below) graduates into `knowledge/<domain>.md`. Sub-threshold candidates
  stay in `candidates/` and keep accumulating. A promoted lesson is removed from
  `candidates/`.
- **Step 3 — prune & cap.** Dedup within `knowledge/*`; prune stale/superseded/contradicted
  lessons; **enforce a per-file size cap** (bounded lesson count / char budget) so injection
  stays cheap; age out candidates that never corroborate (a max candidate age/count-0 policy);
  rewrite `index.md`.
- **Threshold config & overrides.** The threshold defaults to 3 and is tunable (a
  `memory.promote_threshold` in the optional `maestro.config.yaml`, read by the consolidation
  skill — not by the engine). Two bypasses are legitimate and documented: **bootstrap** writes
  `knowledge/*` directly (authoritative seeding from real code, not anecdote), and a **human**
  may hand-promote or hand-write a `knowledge/*` lesson. The threshold governs only the
  automatic retrospect→candidate→knowledge path.
- **Single writer:** consolidation is the only writer of `candidates/*` and `knowledge/*`, so
  runs should not overlap two consolidations; run it solo (documented) or guard it. All tiers
  are git-tracked, so a bad consolidation is reviewable and revertible.
- **Runs on a cheap model** (`haiku`).

**Why the threshold matters:** without it, a single run's idiosyncrasy (a reviewer's one-off
nit, a flake specific to one feature) would immediately start steering every future run.
Requiring ≥3 independent observations keeps `knowledge/*` to patterns the codebase actually
exhibits repeatedly — the difference between a lesson and an anecdote.

`workflows/retrospect.yaml` chains `retrospect → consolidate`; each is also invocable
standalone (`/retrospect`, `/consolidate-memory`).

## Archival phase — harvest + publish, before merge to master

The feature must be archived **before its branch merges to master**. This build turns the
existing `archive` stub in `sdlc-main.yaml` (currently an `echo` script node at the tail,
after `release_approval`) into a real archival phase — a subworkflow
**`workflows/archive.yaml`** with three steps:

1. **retrospect** — distill this run → `incoming/<slug>.md` (the `retrospect` skill).
2. **consolidate** — fold `incoming/*` into `knowledge/*` (the `consolidate-memory` skill),
   so the lessons from this feature are captured into durable domain knowledge.
3. **publish** — curate the feature's docs from `.maestro/<slug>/` into the committed
   `docs/technical|functional/` tree (this is the archive stub's originally reserved purpose;
   remains a POC stub the downstream user wires to their doc-publishing convention).

Positioning: it is the **last automated phase**, running after `release_approval` approves
the release and before the human/external **merge of the feature branch to master**. The
pack does not itself perform the merge to master (that stays a human/CI action); archival is
the gate that guarantees the memory harvest and doc publish happen first. `docs/memory.md`
and the umbrella-workspace doc state the ordering contract explicitly: *approve release →
archival (harvest + publish) → merge to master*.

Because archival now performs the memory harvest by default, there is **no separate opt-in
`retrospect` node** — harvesting is built into every full `sdlc-main` run. (Users running
partial workflows, or wanting an off-cycle harvest, use standalone `/retrospect` or
`workflows/retrospect.yaml`.)

## Wiring into the shipped pack

Add `${memory.knowledge.<domain>}` inputs to the high-value steps in the shipped workflows:

- `workflows/design.yaml`: `plan` (→ `${memory.knowledge.plan}` + `${memory.knowledge.codebase}`),
  `backend-design`, `frontend-design` (static skill names → static memory keys).
- `workflows/sdlc-main.yaml`: `arch_review` (→ `${memory.knowledge.architecture-review}`).
- `workflows/impl.yaml`: the `review` node, keyed per stack →
  `${memory.knowledge.${inputs.stack}-review}` (a nested placeholder — see below).

Each targeted skill gets a short **"Prior lessons"** subsection instructing it to weigh
injected lessons as heuristics (not hard rules) and NOT to hardcode the store path — the
workflow node supplies the value at runtime (swappable-skill rule preserved).

### Nested placeholder resolution (enabler for stack-parameterized keys)

`impl.yaml` is parameterized by `${inputs.stack}`; its review skill is already
`skill: "${inputs.stack}-review"`. To inject the matching per-stack memory domain we need
`${memory.knowledge.${inputs.stack}-review}` — a placeholder nested inside another. The
current `_PLACEHOLDER_RE` (`\$\{([^}]+)\}`) does a single non-recursive pass and would
mis-parse this (it stops at the first `}`), producing garbage.

Fix, scoped to the lenient text-substitution path (`resolve_text`): match the **innermost**
placeholder (`\$\{([^{}]+)\}`) and substitute in a **bounded loop** (resolve inner refs
first, repeat until no `${...}` remains or a small fixed cap, e.g. 5 passes, is hit — the cap
prevents pathological loops). This is behavior-preserving for every existing string (none
contain `{`/`}` inside a ref today, so the innermost regex matches them identically and the
second pass is a no-op) and is a generally useful primitive beyond memory (e.g. nested
`${steps.…}` keys). It gets its own unit test. The strict resolution path (`skill:`,
`artifact:`, `max_visits:`, typed init inputs) inherits the same innermost-match so nested
keys resolve consistently, but keeps its strict missing-ref behavior.

## Engine touchpoints

- **`engine/resolver.py`**
  - `resolve_ref`: new `parts[0] == "memory"` branch (`memory.knowledge.<domain>`),
    resolving from the frozen snapshot; lenient (empty when absent).
  - `init_run`: snapshot `knowledge/*`, write per-run snapshot + record sha256 in
    `state["memory"]`.
  - `Run`: a cached loader for the snapshot content used by `resolve_ref`.
  - `_PLACEHOLDER_RE` + `resolve_text`: innermost-match (`\$\{([^{}]+)\}`) + bounded
    iterative substitution to support nested placeholders (see the wiring section). Verify
    `condctl` still parses conditions BEFORE substitution (unchanged) so this cannot enable
    operator injection.
- **`engine/state.py`**: `new_state` gains a `memory` key (`{snapshot, sha256}`); a small
  snapshot helper.
- **`engine/validate.py`**: teach the placeholder-resolvability lint the `memory` namespace
  so `${memory.knowledge.*}` is not flagged unresolvable; keep flagging malformed refs.
- **`engine/schemas/workflow.schema.json` + `ui/embed.py`**: check whether placeholder
  namespaces are enumerated; if touched, run `python3 ui/embed.py` and keep the UI-sync test
  green.

## Docs

- `docs/workflow-spec.md`: add the `${memory.*}` row to the placeholder table + a strictness
  note (lenient, frozen-at-init).
- `CLAUDE.md`: document the `.maestro/memory/` store, the map-reduce write model, the
  freeze-at-init rule, and the bootstrap + archival lifecycle.
- `README.md`: a short mention under "improves over time" / customizing, including
  `/build-knowledge` as a recommended setup step.
- `docs/memory.md`: the memory-conventions doc — store layout (the three tiers), lesson
  shape, provenance, the map-reduce write model, the **corroboration threshold** (why lessons
  stage in `candidates/` before promotion, the default of 3, how to tune it, and the
  bootstrap/human bypasses), the bootstrap step, and the retrospect→consolidate→publish cycle.
  The store ships only a seed `index.md` (created by bootstrap/first consolidation); no
  README template inside `.maestro/`.
- `docs/umbrella-workspace.md`: add `/build-knowledge` to the per-umbrella setup order, and
  state the release-ordering contract: *approve release → archival (harvest + publish) →
  merge to master*.

## Data flow (end to end)

0. **Bootstrap (once per umbrella)** → `/build-knowledge` scans `codebase/` + docs and writes
   the initial `knowledge/*`. Re-runnable; merges on re-run.
1. **Run N** inits → snapshots `knowledge/*` into the run, hash recorded. The `plan`/HLD
   (idea-building) step and the design/review steps render prompts with
   `${memory.knowledge.<domain>}` filled from the frozen snapshot.
2. **Run N reaches release approval** → human approves → **archival phase** runs (before
   merge to master): `retrospect` writes `incoming/N.md` → `consolidate` folds `incoming/*`
   into `candidates/*` (incrementing counts), **promotes any candidate corroborated by ≥3
   distinct runs into `knowledge/*`**, prunes/caps, rewrites `index.md`, clears `incoming/`
   → `publish` curates docs into committed `docs/`. A first-time observation lands in
   `candidates/`, not `knowledge/`, so it does not yet influence runs.
3. **Human merges** the feature branch to master.
4. **Run N+1** picks up the enriched `knowledge/*` at its own init snapshot.

## Error handling & edge cases

- **No store yet:** snapshot empty → `${memory.*}` empty → prompts unchanged. Inert & free.
- **Concurrent runs:** `incoming/<slug>.md` is per-slug → retrospective writes never race.
  Consolidation is the single `knowledge/*` writer → run solo / guarded.
- **Bad lesson / bad merge:** git-tracked → reviewable and revertible.
- **Missing domain file referenced by a node:** lenient resolve → empty string.
- **Mid-run store change:** ignored (frozen snapshot); does not halt, does not perturb.
- **One-off observation:** stays in `candidates/`, never injected, until it has been seen in 3
  distinct runs. A candidate that never reaches the threshold is aged out — noise never reaches
  runs.
- **Same lesson twice in one run:** counts as one (distinct-slug counting), so a run cannot
  self-promote its own observation.

## Token posture (Goal 3)

Injection adds tokens by nature; four levers bound it: (1) per-domain targeting — a step
gets only its slice, not the whole store; (2) consolidation size cap per domain file;
(3) snapshot frozen once per run, not re-assembled per step beyond substitution;
(4) retrospect/consolidate run on `haiku`.

## Testing

- **Resolver unit tests:** `${memory.knowledge.<domain>}` resolves from the snapshot;
  reproducibility (same snapshot → identical rendered prompt); empty-string when the domain
  file is absent; mid-run live-store change does not affect an in-flight run.
- **Nested-placeholder test:** `${memory.knowledge.${inputs.stack}-review}` resolves to the
  `backend-review` / `frontend-review` domain per stack; existing single-level refs and
  `skill: "${inputs.stack}-review"` remain byte-identical; the iteration cap terminates a
  self-referential placeholder without hanging.
- **init snapshot test:** snapshot file created, sha256 recorded in `state["memory"]`.
- **Validator test:** `${memory.knowledge.*}` accepted; malformed memory refs still flagged.
- **Contract test:** `testdata/test_workflow_skill_contracts.py` green for `build-knowledge`,
  `retrospect`, and `consolidate-memory` (declared node outputs present in the skills'
  `## Output contract`), and for the new `archive.yaml` nodes.
- **Workflow validation:** `maestroctl validate workflows/build-knowledge.yaml`,
  `workflows/retrospect.yaml`, and `workflows/sdlc-main.yaml` (now recursing into
  `archive.yaml`) all lint clean.
- **Regression:** `engine/tests/run_all.py` (incl. the full-SDLC no-LLM sim, which now walks
  the archival subworkflow) stays green; `python3 ui/embed.py` +
  `testdata/test_ui_schema_sync.py` green if schema/UI touched.
- **Corroboration-threshold test:** the same lesson observed from 1 then 2 distinct slugs →
  stays in `candidates/` (count 1, then 2), NOT in `knowledge/`, and is not injected; the
  THIRD distinct-slug observation → promoted into `knowledge/` and now injected. Multiple
  observations of the same lesson from ONE slug → count stays 1 (distinct-slug counting).
  Threshold override (e.g. set to 2) respected.
- **Small e2e:** seed a `knowledge/backend-review.md`; init a run; assert the rendered
  review prompt contains the seeded lesson; run the archival phase → `incoming/<slug>.md`
  written by retrospect, then consolidate folds it into `candidates/` (or promotes on second
  corroboration) and clears `incoming/`.

## Deliverables checklist

- [ ] `${memory.*}` namespace in resolver + freeze-at-init snapshot + state key
- [ ] nested (innermost-first, bounded) placeholder resolution in `resolve_text`
- [ ] validator support for the namespace
- [ ] `skills/build-knowledge/SKILL.md` + `workflows/build-knowledge.yaml` (bootstrap)
- [ ] `skills/retrospect/SKILL.md`
- [ ] `skills/consolidate-memory/SKILL.md` — incoming→candidates→knowledge with the
      corroboration threshold (default 3 distinct runs, configurable) + prune/cap
- [ ] `workflows/retrospect.yaml` (retrospect → consolidate, standalone harvest)
- [ ] `workflows/archive.yaml` (retrospect → consolidate → publish) + `sdlc-main.yaml`
      `archive` node converted from script stub to this subworkflow
- [ ] `${memory.knowledge.*}` inputs wired into plan (idea-building) / designs / reviews +
      "Prior lessons" subsections in those skills
- [ ] `docs/memory.md` conventions doc + seed `index.md` behavior
- [ ] docs: workflow-spec, CLAUDE.md, README, umbrella-workspace (setup + release ordering)
- [ ] tests (resolver, nested-placeholder, validator, contract, workflow-validate, e2e) +
      full suite green
