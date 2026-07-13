# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Guidance for working in this repo (`kv-skills` — Maestro, the KeyValue AI-SDLC pack).

## What this repo is

A **deterministic workflow orchestrator for agentic coding harnesses** (Claude Code,
Cursor), shipped with an **example** AI-SDLC pack. The engine is the product; the SDLC
skills + workflows are a worked example meant to be forked or replaced. The load-bearing
separation: **the workflow owns *what/where/when*** (instruction, inputs, artifact path,
output fields, ordering) and **a skill owns only *how*** — so any agent step's skill can
be swapped (ours, the user's, or a third party's like Obra/Superpowers) without touching
the graph, and the engine injects the paths/inputs/contract into each subagent prompt at
runtime. It ships:

- **AI skills** (`skills/*/SKILL.md`) — the example pack, one per SDLC step (plan, design,
  implement, review, QA…) plus **`skills/maestro`**, the lead agent. Markdown prompts with
  YAML frontmatter (`name`, `description`, `tags`, `allowed-tools`). Devs invoke them as
  slash commands (`/plan`, `/backend-impl`, …) or Maestro invokes them via subagents.
  Skills are portable: they must NOT hardcode artifact paths or their position in a
  pipeline — that lives in the workflow node.
- **The engine** (`engine/`) — stdlib-only Python. `maestroctl.py` is the CLI the lead
  agent shells out to: `validate · init · next · complete · gate-record · fail · reset
  · rebase · status · graph · note`. The resolver serves exactly ONE next action as JSON; the
  LLM never interprets the graph and never edits state. No dependencies, ever.
- **Workflows** (`workflows/*.yaml`) — the example pack (`sdlc-main`, `design`, `impl`,
  `qa`) in the custom spec (`docs/workflow-spec.md`, machine contract
  `engine/schemas/workflow.schema.json`).
- **Agents** (`agents/*.md`) — subagent definitions (tools + role prompt) installed
  into `.claude/agents/`.
- **The builder UI** (`ui/builder.html`) — single-file visual workflow editor, plus a
  read-only **Runs** view that reads `.maestro/<slug>/state.yaml` and colours each run's
  graph by step status (done/running/failed/pending). Works offline from `file://` (browser
  File System API) OR folder-aware behind `engine/ui_server.py` when served by `maestro ui`
  (probes `/api/health`; then loads runs/workflows over HTTP — see the branch points guarded
  by `window.MAESTRO_SERVER`). `ui/embed.py` refreshes its embedded schema + lint-rule blocks.
- **`bin/maestro`** — a repo-local dev wrapper `install.sh` drops at the consumer repo root
  as `./maestro`. Exactly two subcommands: `maestro ui` (serve the builder via
  `engine/ui_server.py`) and `maestro install` (proxy to `install.sh`). It is dev tooling
  only — it NEVER drives a run or writes run state; the `/maestro` skill + engine stay the
  sole execution path and only state writer.
- **`install.sh`** — the installer. There is deliberately NO **execution** CLI and NO config
  file: workflows only ever run through the /maestro skill + engine (the `maestro` bin above
  is viewer/installer tooling, not an executor). Artifact paths, inputs and the output
  contract are declared on the **workflow node** and injected into the subagent prompt by
  the engine — skills do NOT hardcode paths (that keeps them swappable).

There is **no headless runner and no API-key dependency** — workflows execute inside
the user's interactive session (Claude Code, Cursor). Conductor is gone.

## The engine — module map & the action loop

`maestroctl.py` is a thin CLI; the logic lives in modules it imports. Where things are
(so you don't grep blind):

- **`resolver.py`** (by far the largest — the centerpiece) — computes the ONE next action,
  and owns nearly all state mutation: frontier/`cursors`, resume rules, `when` evaluation,
  visit counting + cap enforcement, **back-edge cascade reset** (`_cascade_reset` /
  `_ancestors` — deliberate *under*-reset; read the docstring before touching it), parallel
  branch joins, subworkflow entry, placeholder substitution (`resolve_text/ref/value`,
  `missing_ok=True` for prompt / route-condition / step-input rendering so an unset step
  ref renders empty rather than aborting — but `model:`/`max_visits:` and typed init inputs
  resolve strictly), and
  **`render_agent_prompt`** (assembles instruction + inputs + skill pin + artifact list +
  the last-line-JSON output contract into the subagent prompt). `complete_step`,
  `record_gate`, `init` live here too.
- **`state.py`** — the ledger: load/save with `fcntl` lock + atomic tmp/rename, `step_entry`,
  `sha256_file`, `new_state`. The ONLY writer of `.maestro/<slug>/state.yaml`.
- **`validate.py`** — schema check + graph lint (start/route-target existence, reachability,
  default-route-on-branches, placeholder resolvability, subworkflow depth, cycle lint).
- **`condctl.py`** — the ~4-form route-condition grammar (`==`, `!=`, `in […]`, truthy);
  parses BEFORE substitution so values can't inject operators. `norm()` canonicalises
  bools/numbers; guards use `== true`/`== false`, never `!= true` (prose would slip through).
- **`wf.py`** — the zero-dep YAML-subset loader/emitter (see its own section below).
- **`oq_serve.py` / `oq_record.py`** — the open-questions `script`-node helpers (the
  stdout-JSON-becomes-routable-outputs pattern); `validate_tasks.py` /
  `validate_open_questions.py` — standalone artifact-format validators.
- **`ui_server.py`** — the stdlib `http.server` behind `maestro ui`: serves `builder.html`
  and exposes the repo (`/api/workflows` recursively lists every YAML, tagging maestro
  workflows; `/api/workflow` GET+PUT; `/api/runs`; `/api/health`) so the builder is
  folder-aware. Reuses `state.load` + `wf.load_file`; binds 127.0.0.1 only; path-traversal
  guarded (`_safe_repo_yaml`); reads any YAML under root except `.git`; writes any `.yaml`
  under root EXCEPT `.git`/`.maestro` (run state stays engine-only) — workflow SOURCE only.

**The action loop** (engine ↔ lead agent): `maestroctl next` prints exactly ONE action as
JSON — `run_agent`, `run_agents` (a parallel wave), `run_script`, `ask_gate`, `done`, or
`failed`. The lead agent (`skills/maestro`) dispatches it (spawn subagent / run argv / ask
human), then reports back via `complete`, `gate-record`, or `fail` — each of which itself
prints the FOLLOWING action. The LLM never interprets the graph and never writes state.

## Running checks

```bash
python3 engine/tests/run_all.py            # the whole engine suite, incl. the no-LLM
                                           # full-SDLC simulation (the correctness proof)
python3 testdata/test_ui_schema_sync.py    # UI <-> engine anti-drift + cross-parser test
python3 engine/maestroctl.py validate workflows/sdlc-main.yaml   # recursive lint
python3 engine/validate_tasks.py testdata/tasks.valid.json
python3 engine/validate_open_questions.py testdata/open-questions.valid.json
```

Run one test: `python3 engine/tests/test_resolver.py BackEdgeTest.test_happy_path_no_loop`.
The `invalid-*` fixtures in `testdata/` and `testdata/workflows/` exist to prove the
validators *reject* the hard cases — a validator that accepts one is a regression.
After editing `engine/schemas/workflow.schema.json` or any `workflows/*.yaml`, run
`python3 ui/embed.py` (the sync test fails otherwise).

## The workflow spec — the invariants that matter

Full spec: `docs/workflow-spec.md`. The load-bearing rules:

- **Minimal authoring defaults**: only `nodes:` is required — `version` defaults to 1,
  `start` to the first node, node `type` to `agent`, omitted routing to `next: end`.
  Keep these defaults working; they are the "simple workflow creation" promise.
- **5 node types**: `agent` (instruction required, `skill:` optional pin — omitted =
  harness auto-discovery), `gate` (options ARE the edges; never skipped on resume),
  `script` (stdout JSON becomes routable outputs — the `oq_serve` pattern), `parallel`
  (branches may contain agent/gate/script/subworkflow, never nested parallel),
  `subworkflow` (child steps namespaced `parent/child` in state; depth ≤ 4).
- **Loops are back-edges**, not a construct: any route may target an earlier node.
  Entering a `done` node cascade-resets it plus reachable done steps. Every node has a
  visit cap (`max_visits` → `defaults.max_visits` → 10); exceeding it routes to
  `on_exhausted` (default: a synthesized ask-gate). A route taken through a REAL gate
  option bypasses the cap — the human is the loop bound.
- **Placeholders** are pure text substitution (`${inputs.x}`, `${steps.id.outputs.f}`,
  `${steps.id.branches.k.outputs.f}`; `${config.path}` reads an optional user-created
  maestro.config.yaml — the pack ships none) — no templating engine. `when:` conditions
  support only `==`, `!=`, truthy, `in [a, b]` (`engine/condctl.py`).
- **Artifacts gate completion**: `complete` refuses to mark an agent step done unless
  its `artifact:` files exist non-empty ("proof, not promises").
- **Only the engine writes `.maestro/<slug>/state.yaml`** (fcntl-locked, atomic). The
  workflow file's sha256 is recorded; edits mid-run halt until `rebase` or `reset`.

## The YAML subset — engine/wf.py

Zero-dep hand-rolled loader/emitter. Supported: block maps/lists, one-line flow
collections, plain/quoted scalars, `|`/`|-` literals, comments. Rejected by design:
anchors, tags, folded scalars (`>`), multi-doc. The UI's vendored js-yaml must emit
only this subset (`lineWidth: -1` prevents folding); the cross-parser test in
`testdata/test_ui_schema_sync.py` enforces agreement. If you touch `wf.py`, run the
whole suite — the parser underpins everything.

## Conventions when editing

- **Editing a skill = editing its `SKILL.md`.** Keep the frontmatter contract and each
  skill's **Standards**, **Safety** and **`## Output contract`** sections. Skills describe
  only *how* to do the job — they must NOT hardcode artifact paths or pipeline sequencing
  ("runs after X", "in parallel with Y"). The workflow node supplies the artifact path,
  inputs and output fields; the engine renders them into the prompt (`render_agent_prompt`
  in `resolver.py`). A step skill must NOT name Maestro's `.maestro/<slug>/…` layout at all
  (not even as a fallback — that couples a swappable skill to this orchestrator); when a
  standalone `/skill` run has no path from its instructions, tell it to write to "a sensible
  path you choose (and tell the user where)". A step skill also must NOT restate the engine's
  dispatch contract (the "last-line JSON, short scalars" instruction) — `render_agent_prompt`
  injects that into every subagent prompt at runtime; the skill's `## Output contract` states
  only the conceptual output FIELD NAMES. Those field names ARE a machine contract —
  `testdata/test_workflow_skill_contracts.py` checks every workflow node's declared outputs
  appear in its pinned skill. (`skills/maestro` is exempt from all of this — it IS the
  Maestro lead agent, not a swappable step.)
- **A skill is never the source of truth for workflow functionality.** Skills are
  swappable (ours, the user's, a third party's), so any *logic a workflow's guarantees
  depend on* — counting, thresholds, promotion/gating rules, dedup, state transitions,
  anything deterministic and load-bearing — must live in the **engine** (a stdlib module
  invoked as a `script` node, e.g. `engine/mem_consolidate.py` / `engine/oq_serve.py`), NOT
  inside a `SKILL.md`. The skill supplies only *judgement* (what to write), emitting a
  structured artifact the engine consumes; swapping the skill must not be able to change the
  functionality. Litmus test before putting behaviour in a skill: *if someone replaced this
  skill with their own, would a guarantee the workflow relies on break?* If yes, it belongs
  in the engine. (This is why memory consolidation is `engine/mem_consolidate.py`, not the
  retired `consolidate-memory` skill.)
- **`skills/` is the source of truth for skill prose.** `.claude/skills/`, `.cursor/skills/`
  etc. are installed copies (gitignored, regenerated by `install.sh`) — never edit those.
- **`skills/maestro/SKILL.md` is the orchestrator's contract.** Its hard rules (never
  edit state, never read artifacts into context, never skip gates, dispatch verbatim)
  are what keep long runs reliable — change them only deliberately.
- **Workflows name skills directly** (`skill: plan`); placeholders are allowed in the
  skill name (`skill: "${inputs.stack}-implement"` replaces the old dispatch glue).
  Model choice: per-node `model:` → workflow `defaults.model` → `haiku`; values pass to
  the harness as-is (haiku/sonnet/opus).
- The workflow merge-for-test / contract-check / archive script steps are **POC stubs**
  (`echo` + exit 0) — a downstream user wires them to their real runners.
- `.maestro/<slug>/` holds a feature's requirement input **and** all generated
  artifacts + the state ledger. Git-tracked on purpose.
- `install.sh` uses `set -uo pipefail` (not `-e`) on purpose — one failed skill
  install must not abort the rest.

## The memory store — `.maestro/memory/`

Repo/umbrella-level, git-tracked, shared across slugs. Three tiers: `incoming/<slug>.json`
(per-run structured drops, race-free), `candidates/<domain>.json` (the engine-owned ledger:
lessons + distinct source slugs, NOT injected), `knowledge/<domain>.md` (engine-RENDERED,
injected via `${memory.knowledge.<domain>}`). A lesson promotes into knowledge only after
**≥3 distinct runs** corroborate it (bootstrap lessons are `authoritative` and render
immediately).

There is a **second knowledge surface**: the committed living docs under `docs/` —
per-domain `docs/technical/<domain>.md` + `docs/functional/<domain>.md`, and
`docs/architecture.md` (Mermaid + how services connect). `build-knowledge` authors it from
the codebase; `retrospect` refreshes touched domains after a feature. Human-facing, read by
subagents as ordinary workspace context. It coexists with the injected lessons store.

**The load-bearing separation (swappable skills):** the consolidation *functionality* —
counting distinct runs, the threshold, promotion, pruning, rendering — is deterministic
engine code in `engine/mem_consolidate.py`, invoked as a **`script` node**. Skills
(`build-knowledge`, `retrospect`) only PRODUCE judgement outputs — the `docs/` knowledge base
and the structured `incoming/*.json` lessons; swapping a skill cannot change how corroboration
works. Reads: the resolver only READS the lessons knowledge tier, once, at `init`, freezing a
per-run `memory-snapshot.json` (`engine/memory.py`). The pre-merge `archive` phase of
`sdlc-main.yaml` runs the harvest by default. Full conventions: `docs/memory.md`.

## Editing this repo's prose

Docs here are dense and deliberately worded (README, config comments, SKILL bodies,
docs/workflow-spec.md). Match the existing terse, precise register; keep the ASCII
flow diagrams and tables in sync when the flow changes.
