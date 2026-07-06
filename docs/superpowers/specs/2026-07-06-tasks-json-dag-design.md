# tasks.json — Parallel Task DAG with Batched Context — Design

**Date:** 2026-07-06
**Status:** Approved (design) — pending implementation plan

## Problem

The impl pipelines (`workflows/backend_impl.yaml`, `workflows/frontend_impl.yaml`,
`workflows/qa.yaml`) each run implementation as a **single sequential `implementer`
step**. Two costs follow:

1. **No parallelism.** Independent slices of a feature (e.g. two unrelated endpoints,
   or two independent E2E scenarios) are built one after another even though nothing
   forces the order.
2. **SDK-call pressure.** The implementer re-reads the codebase with many individual
   `read_file` calls. Combined with test/fix loops this pushes a run toward the ~50
   SDK-call ceiling. The design skills already read the same code moments earlier —
   that context is thrown away and re-fetched.

The task plans that exist today (`.sdlc/<slug>/<stack>/tasks.md`, authored by
`backend-tasks` / `frontend-impl` plan mode / `qa-automation`) are **prose**: they carry
order and file hints for a human/agent to interpret, but nothing a skill can execute
deterministically as a dependency graph, and no explicit batched-read manifest.

## Goal

Author a **machine-readable `tasks.json`** — a dependency **DAG** plus a **batched-context
manifest** — during the design phase, and have the impl skills consume it to (a) execute
independent tasks **in parallel** (dependents wait for prerequisites) and (b) load context
in **as few tool calls as possible**, keeping each impl run under the ~50 SDK-call budget.

## Key constraint (shapes the whole design)

**Conductor's workflow graph is static YAML.** The `parallel:` block (e.g. `author_llds`
in `design.yaml`) is a hand-declared, fixed list of agent steps. Conductor **cannot** read
a runtime `tasks.json` and dynamically fan out N branches from it — the number and shape of
tasks is unknown until design time.

Therefore parallel execution of the DAG **must happen inside the `implementer` skill**,
which reads `tasks.json` and dispatches parallel subagents wave-by-wave (via the
`dispatching-parallel-agents` skill). The impl workflow YAML stays a single `implementer`
step. `tasks.json` is a **plan the skill executes**, not a workflow the graph runs.

## Decisions

- **Parallel engine = implementer skill.** The skill topologically sorts `tasks.json` into
  waves and runs each wave's tasks as parallel subagents. (Workflow-level static parallel and
  "ordering-hints-only, still sequential" were both rejected.)
- **Authoring folded into the design skills.** `backend-design` and `frontend-design` emit
  `tasks.json` alongside their LLD, reusing the code they already read (near-zero extra SDK
  cost). Authored pre-contract; acceptable because the backend **owns** its API surface and
  the frontend reconciles the published contract at impl time. (A separate post-contract step
  and a JSON-emitting impl-phase step were rejected — both re-read the code in a fresh
  session, spending the calls we set out to save.)
- **QA authors its own.** QA has no design-phase code-reading skill and its acceptance
  criteria come later from `/api-contract`, so `qa-automation` emits `tasks.json` in
  `qa.yaml`'s `author_tests` step — a flat scenario list (shallow DAG) with a shared
  fixture/page-object manifest.
- **Context = shared manifest + per-task deltas.** A top-level `context_manifest.read_once`
  is loaded **once** in a single batched call; each task lists only its extra `reads` and its
  `writes`. Fewest total calls. (Per-task full file lists and "implementer decides" were
  rejected as call-wasteful / non-guaranteeing.)
- **File naming.** `.sdlc/<slug>/<stack>/tasks.json` — disambiguated by the existing
  per-stack folder (matches `tasks.md`); the `stack` is also a field inside the JSON. No
  filename renaming.

## `tasks.json` schema

Defined once in a shared reference file: `workflows/tasks.schema.json`.

```jsonc
{
  "schema_version": 1,
  "stack": "backend",                     // backend | frontend | qa
  "feature_slug": "saved-search",
  "context_manifest": {
    "read_once": ["src/searches/router.py", "src/searches/service.py", "src/db/models.py"],
    "reference": ["docs/technical/saved-search/lld/backend.md",
                  "contracts/saved-search/openapi.yaml", "CLAUDE.md"]
  },
  "tasks": [
    {
      "id": "t1",
      "title": "SavedSearch schema + migration",
      "depends_on": [],                    // DAG edges — dependents wait for these ids
      "reads": [],                         // delta files beyond context_manifest.read_once
      "writes": ["src/db/models.py", "migrations/0007_saved_search.py"],
      "test": "tests/db/test_saved_search_model.py",  // failing test written first
      "standards": ["migrations", "backward-compat"],
      "needs_human_gate": true
    },
    {
      "id": "t2",
      "title": "Service create/list",
      "depends_on": ["t1"],
      "reads": ["src/searches/repository.py"],
      "writes": ["src/searches/service.py"],
      "test": "tests/searches/test_service.py",
      "standards": ["validation", "idempotency"],
      "needs_human_gate": false
    }
  ]
}
```

Every task retains the fields `backend-tasks` already mandates — `id`, `title`, `test`,
`standards` (subset of {security, backward-compat, rate-limiting, idempotency, validation,
observability, migrations, performance}), `needs_human_gate` — plus:

- `depends_on: [id]` — DAG edges. Empty = eligible in the first wave.
- `reads: [path]` — files this task needs **beyond** the shared manifest.
- `writes: [path]` — files this task creates/edits. Basis of the parallel-safety invariant.

QA tasks use the same shape; `depends_on` is usually empty (scenarios are independent),
`writes` are the spec files, `reads` are fixtures/page objects, `test` is the scenario id.

## Authoring changes (design phase)

- **`skills/backend-design/SKILL.md`, `skills/frontend-design/SKILL.md`:** add a final step —
  emit `tasks.json` next to the LLD, reusing already-read code. `writes`/`reads` come from the
  component/sequence design; `depends_on` from the natural build order (types → domain →
  persistence → API expressed as a chain within a slice; independent slices left unlinked so
  they parallelize). Return `tasks_path` in addition to `lld_path`.
- **`skills/qa-automation/SKILL.md`:** emit `tasks.json` (flat scenarios + shared fixture/
  page-object manifest) in `author_tests`.
- **`skills/backend-tasks/SKILL.md`:** retargeted to emit `tasks.json` (same schema) instead
  of `tasks.md`. It now serves only as the **fallback** authoring path for standalone impl
  runs where no design phase produced the file.

## Consumption & execution (impl phase)

The `implementer` skills (`backend-implement`, `frontend-implement`) gain an execution
protocol:

1. **Locate or author.** If `.sdlc/<slug>/<stack>/tasks.json` exists (from the design phase),
   use it. Otherwise author it via the fallback (`backend-tasks`), then continue.
2. **Load once.** Read `context_manifest.read_once` **and** `context_manifest.reference` in a
   **single batched call** — one `Bash` `cat` over all paths (both lists concatenated) with
   `=== <path> ===` delimiters — instead of N `Read` calls. (`read_once` = code the tasks
   edit against; `reference` = the LLD, contract, and repo conventions the tasks must honor.
   Both are loaded together in the one batched read.)
3. **Topological waves.** Sort tasks by `depends_on` into waves (wave = all tasks whose
   prerequisites are already complete).
4. **Dispatch a wave.** Run the wave's tasks as **parallel subagents** via the
   `dispatching-parallel-agents` skill. Each subagent receives its task spec + a pointer to
   the already-loaded shared context, batch-reads its own `reads` delta in one call, and does
   test-first TDD for that task (write failing `test` → implement → refactor).
5. **Barrier + advance.** Wait for the wave, run the targeted tests, then start the next wave.
6. Downstream test/verify/review/fix steps in the workflow are unchanged.

## Parallel-safety & SDK-call budget rules

- **Disjoint writes per wave (correctness invariant).** Any two tasks in the same wave MUST
  have **non-overlapping `writes`**. The authoring skill enforces this: if two otherwise-
  independent tasks touch the same file, it adds a synthetic `depends_on` edge to serialize
  them. This is what makes concurrent edits safe.
- **Parallelism is across slices, not within one.** TDD ordering inside a slice stays a
  dependency chain; only independent slices run concurrently.
- **`needs_human_gate` tasks** are surfaced before their wave runs (migrations, auth,
  payments, prod config, deps) — same gate rule as today, now keyed off the flag in the JSON.
- **Budget.** The parent implementer session ≈ 1 batched manifest read + wave dispatches +
  test runs. Each subagent is its own session with its own budget, so fan-out **lowers**
  per-session call count rather than raising it. Target: ≤ 50 SDK calls per session.

## Files touched

**New**
- `workflows/tasks.schema.json` — the `tasks.json` JSON Schema (source of truth for the shape).
- `docs/superpowers/specs/2026-07-06-tasks-json-dag-design.md` — this spec.

**Edited — skills**
- `skills/backend-design/SKILL.md` — emit `tasks.json`; return `tasks_path`.
- `skills/frontend-design/SKILL.md` — emit `tasks.json`; return `tasks_path`.
- `skills/qa-automation/SKILL.md` — emit `tasks.json` (flat scenarios + fixture manifest).
- `skills/backend-implement/SKILL.md` — consume `tasks.json`: batched manifest read + wave-based
  parallel subagent dispatch; fallback-author if absent.
- `skills/frontend-implement/SKILL.md` — same consumption protocol.
- `skills/backend-tasks/SKILL.md` — emit JSON (schema above); role narrowed to fallback authoring.

**Edited — workflows**
- `workflows/backend_impl.yaml` — `tasks` step → "load-or-author `tasks.json`"; `implementer`
  prompt → consume the DAG.
- `workflows/frontend_impl.yaml` — same.
- `workflows/qa.yaml` — `author_tests` emits `tasks.json`.

**Edited — config**
- `skills.config.yaml` — add `tasks` artifact paths (`.sdlc/<slug>/<stack>/tasks.json`);
  register `dispatching-parallel-agents` as the impl parallel-dispatch external skill.

## Out of scope

- Dynamic Conductor fan-out (impossible with the static graph — that's why parallelism lives
  in the skill).
- Cross-stack parallelism beyond what `main.yaml`/`dispatch.yaml` already provide.
- Changing the test/verify/review/fix steps of the impl pipelines.
