# Sub-workflow step ledger & skip-guards — design

**Date:** 2026-07-07
**Status:** Approved design, pending spec review

## Problem

Conductor has native checkpoint + resume (`runtime.checkpoint.every_agent`, `conductor resume`),
but it only checkpoints the **root engine**. A `type: workflow` step runs as a **black-box step**:

- `WorkflowEngine._periodic_checkpoints_active` gates on `self._subworkflow_depth == 0`
  (`conductor/engine/workflow.py:1885`).
- The engine comment is explicit: *"sub-workflow state is not independently resumable
  (the parent re-runs the child from scratch)"* (`workflow.py:1915`).

Consequence: if a run dies partway through `design.yaml` — e.g. after the HLD is authored
and approved, during `/api-contract` — resuming `main.yaml` restarts **all of `design.yaml`
from its first step**: re-authoring the HLD, re-hitting the human gate, re-running everything.
The expensive AI steps are redone even though their artifacts already exist on disk.

## Goal

Make each sub-workflow **re-entrant**: on re-run (including the parent re-running a child from
scratch), a step whose work is already done skips its expensive body and the workflow lands on
the first genuinely-unfinished step.

### Non-goals

- Replacing Conductor's native root-level checkpoint/resume — this complements it.
- Content-based staleness detection (auto-detecting that an upstream artifact changed and
  invalidating downstream). Explicitly rejected in favor of the ledger (see Known limitations).
- Skipping human approval gates. Gates always re-ask (decision below).

## Decisions (from brainstorming)

1. **Done signal:** an explicit ledger file, not implicit artifact presence.
2. **Human gates:** never skipped — always re-ask. Only expensive producing / AI / sub-workflow
   steps are skippable.
3. **Loops:** guards make forward re-entry cheap; every backward (revise/rework) route must
   `reset` the flags it invalidates before re-entering.

## Architecture

### 1. The ledger

One file per feature slug: `.sdlc/<slug>/state.json`. Persists across runs (so a fresh
`conductor run` for the same slug also skips completed work). Shape:

```json
{
  "version": 1,
  "slug": "saved-search",
  "steps": {
    "hld":          { "done": true,  "at": "2026-07-07T10:12:03Z", "artifact": "docs/technical/saved-search/hld.md" },
    "backend_lld":  { "done": true,  "at": "2026-07-07T10:20:41Z", "artifact": "docs/technical/saved-search/lld/backend.md" },
    "frontend_lld": { "done": false },
    "api_contract": { "done": false }
  }
}
```

For `for_each` / parallel fan-out where the same step id runs per iteration, the key is
suffixed: `impl:backend`, `impl:frontend`, `slice:<slice_id>` — see Concurrency.

### 2. The helper — `workflows/state.py`

A single deterministic Python helper (sits beside the existing `validate_tasks.py`; Python is
already a workflow dependency). **Only script steps touch state** — LLM steps cannot be trusted
to write JSON reliably.

| Command | Behavior | Exit codes | Used by |
|---|---|---|---|
| `state.py check --slug S --step ID [--key K]` | true iff flag `done` **and** recorded `artifact` still exists & non-empty | `0` = done (skip), `1` = not done (run) | guard step routing |
| `state.py mark --slug S --step ID [--key K] --artifact P` | verify `P` exists & non-empty, then set `done=true` + `at` timestamp | `0` = marked, `1` = artifact missing (→ abort) | after each producer; **subsumes today's `assert_*`** |
| `state.py reset --slug S --step ID [--step ID2 ...]` | clear listed flags (or `--all`) | `0` | backward routes; force-rebuild |

Details:
- `check` re-verifies the file on disk → deleting an artifact correctly forces re-run. The
  ledger is authoritative for the boolean; the file check is a sanity guard.
- `mark` refuses to flag a step done if its artifact is missing/empty, so a crashed producer is
  never recorded as complete.
- **Success predicate:** for steps whose real success is more than "a file exists" (e.g. a
  `verify` step gated on tests passing), `mark` is only invoked on the success route, so a
  failed attempt stays `false` and re-entry retries it. Pure producers mark on artifact
  presence alone.
- Writes are atomic: read → modify → write-temp → `os.replace`, guarded by a lockfile
  (`.sdlc/<slug>/state.json.lock`), so concurrent `for_each` slices don't clobber each other.

### 3. The guard / mark pattern

Each skippable producing step is bracketed by two script steps:

```
skip_or_run_hld  (script: state.py check --step hld)
   ├─ exit 0 → route to the NEXT guard        # already done → skip body
   └─ else   → route to hld
hld  (existing producer)               → mark_hld
mark_hld  (script: state.py mark --step hld --artifact docs/technical/<slug>/hld.md)
   ├─ ok   → NEXT guard
   └─ fail → abort                            # replaces the old assert_hld
```

The sub-workflow's `entry_point` becomes the first guard. On a from-scratch re-run, control
threads guard → guard, skipping every set flag and landing on the first unfinished step. Human
gates sit between guards, untouched.

## Loop handling

**Rule:** guards record forward progress; every backward edge resets what it invalidates.

- **Revision loops** (`hld_approval → revise → author_hld`): splice a `reset` step in front of
  the target. Reset **cascades** — revising the HLD invalidates the LLDs and contract derived
  from it, so the reset clears the revised step *and everything downstream*:
  `state.py reset --step hld --step backend_lld --step frontend_lld --step api_contract`.
  Feedback flow is unchanged: `prompt_for: feedback` lands in context, reset only clears flags,
  the producer re-runs and reads the feedback.
- **Rework loops** (`merge_for_test` fail → `rework_gate → rework → implement`): reset the
  `implement` flags (all `--key` stack entries) before re-entering the fan-out.
- **Bounded internal loops** (`/fix`, ≤3): the fix skill loops *inside itself* — not via
  workflow routes — so the ledger never sees individual attempts. The `verify → fix` cycle is
  one logical unit; `mark` fires only on genuine success (tests green), so a unit that exhausts
  its attempts stays `false` and is retried on re-entry.

## Pilot: `design.yaml`

Chosen as the pilot: expensive AI steps (`/plan` on Opus, `/api-contract` on Opus), a human
gate, a revise loop, and a parallel group — it exercises every part of the design.

Skippable steps and their ledger ids:

| Step id | Producer | Artifact |
|---|---|---|
| `hld` | `author_hld` (`/plan`) | `docs/technical/<slug>/hld.md` |
| `backend_lld` | `backend_design` | `docs/technical/<slug>/lld/backend.md` |
| `frontend_lld` | `frontend_design` | `docs/technical/<slug>/lld/frontend.md` |
| `api_contract` | `contract` (`/api-contract`) | `contracts/<slug>/openapi.yaml` |

Rewritten flow (guards `G_`, marks `M_`):

```
assert_prd                       # precondition (PRD is input, not produced) — unchanged
  → G_hld (check hld)
      done → G_llds
      else → author_hld → M_hld (mark hld | abort) → hld_approval
hld_approval
  approve → G_llds
  revise  → reset_hld_cascade (reset hld,backend_lld,frontend_lld,api_contract) → author_hld
  reject  → abort
G_llds (check backend_lld AND frontend_lld)
  both done → G_contract
  else      → author_llds (parallel) → M_llds (mark backend_lld+frontend_lld for those present) → G_contract
G_contract (check api_contract)
  done → $end
  else → contract → M_contract (mark api_contract | abort) → $end
```

`assert_prd` stays as-is (PRD is a precondition input, gets no flag). The old `assert_hld` is
replaced by `M_hld`, which asserts *and* marks.

### Parallel-group granularity limitation

Conductor parallel groups allow only agent steps, so guards cannot be spliced *inside*
`author_llds`. Skip granularity there is the **whole group**: skip only if *both* LLDs are done;
if either is missing, both members run (a done one is harmlessly re-authored) and `M_llds` marks
whichever artifacts are present. Per-member skip would require the design skills to self-noop
(LLM, unreliable) or restructuring the group — out of scope for the pilot. Documented, not
solved.

## Rollout (after pilot proves out)

Same guard/mark/reset pattern, one shared `state.py`, applied to:
`backend_impl.yaml`, `frontend_impl.yaml`, `qa.yaml`, `dispatch.yaml`. The `for_each` slices in
the impl workflows use `--key <slice_id>`; `main.yaml`'s `implement` for_each uses `--key <stack>`.

## Concurrency

`for_each` / parallel iterations write concurrently to one `state.json`. `state.py` serializes
via a lockfile and atomic `os.replace`. Per-iteration flags are namespaced by `--key`, so
`impl:backend` and `impl:frontend` never collide.

## Escape hatch (force rebuild)

- Targeted: `state.py reset --slug S --step hld` (or delete the artifact — `check` then fails).
- Full: `state.py reset --slug S --all` (or delete `.sdlc/<slug>/state.json`).
- Optional workflow input `force` (default false) that routes through a `reset --all` at entry;
  added during rollout if wanted, not required for the pilot.

## Known limitations

1. **Ledger-only, no content-hash staleness.** If you hand-edit an upstream artifact without
   going through a revise route, downstream flags are *not* auto-invalidated — they'd be skipped
   as done. Mitigation: revise routes cascade-reset; manual edits require a manual `reset`. This
   is the accepted cost of choosing the ledger over content-hashing.
2. **Parallel-group skip is group-level, not member-level** (see pilot section).
3. State is per-slug on local disk under `.sdlc/`; not shared across machines/CI runners.

## Testing

- `state.py` unit tests: check/mark/reset semantics; artifact-missing → not-done; concurrent
  marks under the lock; `--key` namespacing.
- `design.yaml` integration: (a) clean run marks all four flags; (b) kill after `M_hld`, re-run
  → `hld` skipped, lands on LLDs; (c) revise from `hld_approval` → all four flags cleared, HLD
  re-authored; (d) delete `hld.md` between runs → `hld` re-runs.
- `conductor validate design.yaml` passes after the rewrite.
