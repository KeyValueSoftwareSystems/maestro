# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Guidance for working in this repo (`kv-skills` — KeyValue AI-SDLC).

## What this repo is

A **distributable pack**, not an application. It ships:

- **AI skills** (`skills/*/SKILL.md`) — one per SDLC step (plan, design, implement, review, QA…).
  Each is a markdown prompt with YAML frontmatter (`name`, `description`, `allowed-tools`).
  Devs invoke them as slash commands (`/plan`, `/backend-impl`, …).
- **Conductor workflows** (`workflows/*.yaml`) — orchestrate the same skills end-to-end with
  human approval gates. `main.yaml` is the full pipeline; the others run one phase each.
- **`skills.config.yaml`** (repo root) — the single source of truth for *which* skill (and which
  external helper skill) backs each SDLC slot. Read by **both** slash commands and Conductor.
- **`install.sh`** — installs the pack + external Superpowers skills + Conductor into a user's repo,
  and drops the **`bin/maestro`** run wrapper on PATH.
- **`bin/maestro`** — the slug-only front door: `maestro <slug>` reads the PRD from
  `features/<slug>/prd.md`, runs `conductor run` with a deterministic `--web-port` (`KV_WEB_PORT`,
  default 8080), and passes the slug through. Defaults to `workflows/main.yaml`; override with
  `--path=<file>` to run any individual or customised workflow. PRD resolution is done in-workflow
  (design.yaml's `resolve_prd` set step), so a bare `conductor run` with `--input feature_slug=…`
  works too.

There is **no build and no app to run.** The "code" is prompts and YAML; the only executables
are the Python helpers under `workflows/` (`validate_tasks.py`, `validate_open_questions.py`,
`state.py`, `oq_serve.py`, `oq_record.py`) — all stdlib-only, no dependencies to install.

## Running checks

```bash
python3 testdata/test_state.py        # 25 unittest cases for the step ledger (state.py)
bash   testdata/test_design_wiring.sh # end-to-end check of design.yaml guard/mark wiring vs state.py
python3 workflows/validate_tasks.py          testdata/tasks.valid.json
python3 workflows/validate_open_questions.py testdata/open-questions.valid.json
```

Run a single unittest case: `python3 testdata/test_state.py CliTest.<method>`. The `invalid-*`
fixtures in `testdata/` exist to prove the validators *reject* the hard cases — a validator that
accepts one is a regression.

## The two-config model — keep it straight

- `skills.config.yaml` (root) — **WHICH** skill backs each slot; read by commands *and* Conductor.
  Every `external:` value is the bare discovery name of an installed skill (e.g. `brainstorming`,
  not `superpowers:brainstorming`), or `none` to fall back inline. Change behavior here, it changes
  everywhere. Model choice is **not** here — it's per-step `model:` in the workflow YAML.
- `workflows/workflow.config.yaml` — **HOW** Conductor orchestrates/enforces (fix-loop cap,
  coverage gate, env lifecycle). Conductor-only; irrelevant to standalone slash commands.

## The SDLC flow (what the pack produces)

```
feature → HLD (/plan) → [open-questions loop → approve] → per-stack LLDs (backend ∥ frontend) → /api-contract
        → architecture-review → [approve]
        → implement (task DAG → parallel slices → merge → tests → verify → review)
        → QA → review pack → [approve → release]
```

Every producing step writes an artifact to disk; the workflow gates on `test -s <file>` before
advancing ("proof, not promises"). Artifact paths are declared once in `skills.config.yaml`
under `artifacts:` — a skill **resolves its own output path from there** (`<slug>` = `feature_slug`);
the caller does not pass paths in.

## tasks.json — the parallel task DAG

The design phase (or `/backend-tasks` as fallback) emits `.sdlc/<slug>/<stack>/tasks.json`: tasks
grouped into **slices** that run in parallel via the workflow's `for_each`. Invariants beyond the
JSON schema are enforced by `workflows/validate_tasks.py` (run it before trusting a tasks.json):

- every task belongs to exactly one slice; `group_id` on task and slice must match;
- `depends_on` is **intra-group only** (no cross-group deps — that's what makes slices parallel-safe);
- `writes` are **disjoint across groups** (no two groups write the same path);
- per-slice task order respects `depends_on`; graph is acyclic.

Schema: `workflows/tasks.schema.json`. Fixtures: `testdata/tasks.{valid,invalid-*}.json` —
the `invalid-*` ones exist to prove the validator rejects the two hard cases (cross-group dep,
shared write). Validate with:

```bash
python3 workflows/validate_tasks.py testdata/tasks.valid.json
```

## The HLD open-questions loop

The HLD phase surfaces unresolved decisions as a machine-readable loop, mirrored by the HLD's
prose "Open questions" section. State lives at `.sdlc/<slug>/open-questions.json` (schema
`workflows/open-questions.schema.json`, validator `validate_open_questions.py`). `design.yaml`
drives it with two helpers — never re-implement their logic in the YAML:

- `oq_serve.py <path>` — prints the next action as JSON: `{"state":"ask",…}` (a question is open),
  `"refine"` (answers await folding back into the HLD), or `"approve"` (nothing left). The workflow
  routes on `state`; exit 1 (missing/unparseable file) routes to abort.
- `oq_record.py <path> <qid> <choice> [answer]` — folds a gate answer in, then re-validates.
  Choices: `answer` (resolved; a bare integer `N` picks `options[N-1]`, else stored verbatim),
  `you-decide` (resolved; refine step chooses a default), `skip` (deferred).

## Sub-workflow resume — the step ledger

Conductor only checkpoints the top-level run, so a sub-workflow (`design.yaml`, `qa.yaml`, …)
would otherwise re-run from step one. `state.py` makes them re-entrant via a per-feature ledger
at `.sdlc/<slug>/state.json` (fcntl-locked). **Only script steps call it — never an LLM/agent
step.** A step whose artifact is recorded *and still present on disk* is skipped; the run lands
on the first unfinished step. Approval gates are never skipped.

```bash
python3 workflows/state.py check --slug S --step ID [--key K]   # exit 0 done / 1 not-done
python3 workflows/state.py mark  --slug S --step ID --artifact PATH   # exit 1 if artifact missing
python3 workflows/state.py reset --slug S (--step ID … | --all)       # force rebuild
```

The ledger tracks completion, not content: hand-editing an upstream artifact does **not**
invalidate downstream steps — `reset` the step (or delete its artifact) to force a rebuild.

## Conventions when editing

- **Editing a skill = editing its `SKILL.md`.** Keep the frontmatter contract; `allowed-tools`
  scopes what the skill may do (most design/review skills are read-only + `Write` for their
  artifact only). Each editing skill carries a **Standards** and a **Safety** section — preserve
  them: skills must not write secrets/prod config and must stop before destructive actions.
- **`skills/` is the source of truth.** `.claude/skills/` and `.cursor/skills/` are *installed
  copies* (gitignored, regenerated by `install.sh`) — never edit those.
- **Workflow YAML is Conductor + Jinja.** Steps invoke a skill *by name via prompt* — they never
  re-implement behavior. Note the defensive `{% if <step> is defined %}` guards in `output:`
  blocks: the output block renders on *every* termination (including early `abort`), so any
  step-output reference must be guarded or it raises a TemplateError.
- **One global default model.** Every workflow's `default_model:` is
  `${KV_MODEL_DEFAULT:-claude-haiku-4-5}` and no step pins its own model, so all steps run the
  same model. The single knob is `models.default` in `workflows/workflow.config.yaml`: the
  `maestro` wrapper reads it and exports `KV_MODEL_DEFAULT` (Conductor resolves `${VAR:-…}` at
  load; an explicit env var wins; a bare `conductor run` falls back to the baked haiku default).
  For a one-off per-step model, add a literal `model:` to that step's YAML — it wins. Model
  choice is not in `skills.config.yaml`.
- The workflow test/merge/verify shell steps are **POC stubs** (`echo` + exit 0) — a downstream
  user wires them to their real runner. Don't mistake them for working test execution.
- `.sdlc/` and `.kv/` are per-run proof output — gitignored, regenerable, never source.

## Editing this repo's prose

Docs here are dense and deliberately worded (README, config comments, SKILL bodies). Match the
existing terse, precise register; keep the ASCII flow diagrams and tables in sync when the flow
changes. `install.sh` uses `set -uo pipefail` (not `-e`) on purpose — one failed skill install
must not abort the rest.
