# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Guidance for working in this repo (`kv-skills` — Maestro, the KeyValue AI-SDLC pack).

## What this repo is

A **distributable pack**, not an application. It ships:

- **AI skills** (`skills/*/SKILL.md`) — one per SDLC step (plan, design, implement,
  review, QA…) plus **`skills/maestro`**, the lead agent. Markdown prompts with YAML
  frontmatter (`name`, `description`, `tags`, `allowed-tools`). Devs invoke them as
  slash commands (`/plan`, `/backend-impl`, …) or Maestro invokes them via subagents.
- **The engine** (`engine/`) — stdlib-only Python. `maestroctl.py` is the CLI the lead
  agent shells out to: `validate · init · next · complete · gate-record · fail · reset
  · rebase · status · graph`. The resolver serves exactly ONE next action as JSON; the
  LLM never interprets the graph and never edits state. No dependencies, ever.
- **Workflows** (`workflows/*.yaml`) — the example pack (`sdlc-main`, `design`, `impl`,
  `qa`) in the custom spec (`docs/workflow-spec.md`, machine contract
  `engine/schemas/workflow.schema.json`).
- **Agents** (`agents/*.md`) — subagent definitions (tools + role prompt) installed
  into `.claude/agents/`.
- **The builder UI** (`ui/builder.html`) — single-file visual workflow editor.
  `ui/embed.py` refreshes its embedded schema + lint-rule blocks.
- **`install.sh`** — the installer. There is deliberately NO runtime CLI and NO config
  file: everything runs through the /maestro skill + engine; skills state their own
  artifact paths and helper-skill names inline.

There is **no headless runner and no API-key dependency** — workflows execute inside
the user's interactive session (Claude Code, Cursor). Conductor is gone.

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
  skill's **Standards**, **Safety** and **`## Output contract`** sections (last-line
  JSON, short scalars only). Skills state their own artifact paths inline
  (`.maestro/<slug>/…`) — callers never pass paths, and there is no config indirection.
- **`skills/` is the source of truth.** `.claude/skills/`, `.cursor/skills/` etc. are
  installed copies (gitignored, regenerated by `install.sh`) — never edit those.
- **`skills/maestro/SKILL.md` is the orchestrator's contract.** Its hard rules (never
  edit state, never read artifacts into context, never skip gates, dispatch verbatim)
  are what keep long runs reliable — change them only deliberately.
- **Workflows name skills directly** (`skill: plan`); placeholders are allowed in the
  skill name (`skill: "${inputs.stack}-implement"` replaces the old dispatch glue).
  Model choice: per-node `model:` → workflow `defaults.model` → `haiku`; values pass to
  the harness as-is (haiku/sonnet/opus).
- The workflow test/merge/contract-check/archive script steps are **POC stubs**
  (`echo` + exit 0) — a downstream user wires them to their real runners.
- `.maestro/<slug>/` holds a feature's requirement input **and** all generated
  artifacts + the state ledger. Git-tracked on purpose.
- `install.sh` uses `set -uo pipefail` (not `-e`) on purpose — one failed skill
  install must not abort the rest.

## Editing this repo's prose

Docs here are dense and deliberately worded (README, config comments, SKILL bodies,
docs/workflow-spec.md). Match the existing terse, precise register; keep the ASCII
flow diagrams and tables in sync when the flow changes.
