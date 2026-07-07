# KeyValue AI-SDLC

A ready-to-install pack of **AI skills** and a **Conductor workflow** that runs a feature
through the KeyValue software-development lifecycle: high-level design → detailed design →
implementation → review → QA → release — with a human approval at each gate.

## Why

Building a feature well means the same steps every time: design it, review the design,
implement to a contract, test it, review the code, QA it, ship it. This pack encodes those
steps once so every developer runs them the same way.

- **Run it your way.** Let Conductor orchestrate the whole pipeline end-to-end, or run each
  step yourself as a slash command (`/plan`, `/api-contract`, `/backend-impl`, …) in Claude
  Code, Cursor, or Copilot.
- **One place to change behavior.** Every step's behavior lives in its skill; which skill (and
  any helper skill) backs each step is one line in [`skills.config.yaml`](skills.config.yaml).
  Change it there and it changes everywhere.
- **Proof, not promises.** Every step writes an artifact to disk, and the pipeline checks the
  file exists before moving on.

## Install

**Prerequisites:** [Node.js](https://nodejs.org) (for `npx`), plus `curl` + `tar` (standard on
macOS/Linux).

One command from the root of **your** repo:

```bash
curl -fsSL https://raw.githubusercontent.com/KeyValueSoftwareSystems/kv-skills/main/install.sh | bash -s -- claude-code
```

Or for several IDEs at once:

```bash
curl -fsSL https://raw.githubusercontent.com/KeyValueSoftwareSystems/kv-skills/main/install.sh | bash -s -- claude-code cursor
```

The installer:

1. installs **our skills** (`npx skills add KeyValueSoftwareSystems/kv-skills`);
2. installs the **external helper skills** the flow uses ([Superpowers](https://github.com/obra/superpowers) — brainstorming, planning, TDD, code review, debugging, worktrees);
3. copies the **Conductor workflows** + `skills.config.yaml` into your repo (fetched from the repo tarball when run piped);
4. installs **Conductor** if [`uv`](https://github.com/astral-sh/uv) is available (skip with `--no-conductor`).

> Conductor runs the full pipeline; you don't need it if you only use the slash commands.

## How to run

### As an orchestrator (Conductor)

Conductor runs the skills for you, end to end, with automatic approval gates. Same skills,
same artifacts — it just drives the sequence:

```bash
cd workflows
conductor validate main.yaml
conductor run main.yaml --web \
  --input feature="Add saved-search" --input feature_slug="saved-search"
```

Any workflow below also runs on its own — useful for re-running just one phase:

| Workflow | Run it | What it does |
|----------|--------|---------------|
| [`main.yaml`](workflows/main.yaml) | `conductor run main.yaml --web --input feature="…" --input feature_slug="…"` | Full pipeline: design → architecture review → implement (backend ∥ frontend) → QA → review pack, with a human gate at each approval point |
| [`design.yaml`](workflows/design.yaml) | `conductor run workflows/design.yaml --web --input feature="…" --input feature_slug="…"` | HLD (`/plan`) → human approve → per-stack LLDs (backend ∥ frontend) → `/api-contract` |
| [`backend_impl.yaml`](workflows/backend_impl.yaml) | `conductor run backend_impl.yaml --input feature="…" --input feature_slug="…" --input contract_summary="…"` | Backend: build the task DAG → fan out over independent slices (parallel, test-first) → merge → unit/integration → contract verification → backend review |
| [`frontend_impl.yaml`](workflows/frontend_impl.yaml) | `conductor run frontend_impl.yaml --input feature="…" --input feature_slug="…" --input contract_summary="…"` | Frontend: build the task DAG → fan out over independent slices (parallel) → merge → component + E2E tests → a11y gate → frontend review |
| [`qa.yaml`](workflows/qa.yaml) | `conductor run qa.yaml --input feature="…" --input feature_slug="…"` | QA automation: author acceptance-criteria E2E tests, run in a clean env |
| [`dispatch.yaml`](workflows/dispatch.yaml) | (internal — used by `main.yaml`'s `for_each`) | Routes a build to `backend_impl.yaml` or `frontend_impl.yaml` by stack |

`design.yaml` and `main.yaml` contain a human approval gate, so run them with `--web`.

> The test / merge / verify shell steps in the workflows are **POC stubs** (`echo` + exit 0).
> Wire them to your real test runner and `kv up` / `kv down` before relying on the pipeline's
> green/red result. Conductor also needs the `claude-agent-sdk` provider — the installer sets
> this up when `uv` is present. The per-stack parallel fan-out (`for_each` over task-DAG
> slices) is new — validate it against your Conductor runtime before relying on it.

### As skills (you orchestrate manually)

Run the slash commands yourself, in order, in any IDE (Claude Code, Cursor, Copilot) — you
review each artifact before moving to the next:

```
/plan feature="Add saved-search" feature_slug="saved-search"   # high-level design, then approve
/backend-design  ∥  /frontend-design   # author the per-stack LLDs
/api-contract          # reconcile the LLDs → the cross-repo contract
/architecture-review → /backend-impl → /backend-review
/frontend-impl → /frontend-review → /qa → /verify → /fix → /review-pack
```

| Skill | Command | Edits code? | Purpose |
|-------|---------|:-----------:|---------|
| `plan` | `/plan` | no | High-level design (HLD): options, choice, risks |
| `backend-design` / `frontend-design` | `/backend-design` · `/frontend-design` | no | Author the per-stack low-level design (LLD) — how the feature fits each stack |
| `api-contract` | `/api-contract` | no | Reconcile the LLDs into the OpenAPI contract + acceptance criteria |
| `backend-tasks` | `/backend-tasks` | no | Author the task DAG (`tasks.json`) — ordered tasks grouped into independent slices (fallback when the design phase didn't emit it) |
| `backend-implement` | `/backend-impl` | yes | Implement to the contract, test-first, to backend standards |
| `frontend-implement` | `/frontend-impl` | yes | Implement UI states + tests to frontend standards |
| `qa-automation` | `/qa` | tests | Critical-journey E2E from acceptance criteria |
| `architecture-review` | `/architecture-review` | no | Review the design: gaps, security, scaling |
| `backend-review` / `frontend-review` | `/backend-review` · `/frontend-review` | no | Review the implementation |
| `verify` | `/verify` | no | Run deterministic checks → proof report |
| `fix-loop` | `/fix` | bounded | Fix failing checks (≤3 attempts), then escalate |
| `human-review-pack` | `/review-pack` | no | Assemble the PR/release pack |

Each editing skill carries the **standards** a change must meet (security, backward
compatibility, migrations, accessibility, performance, …) and a **Safety** section: it will
not write secrets or production config, and it stops to ask a human before anything
destructive.

## The flow

```
feature → design phase ─ HLD → [approve]
                         → per-stack LLDs (backend ∥ frontend) → /api-contract
        → architecture-review → [approve]
        → implement (backend ∥ frontend: task DAG → parallel slices → merge → tests → verify → review)
        → integrate → QA → review pack → [approve → release]
```

The whole design phase is one workflow ([workflows/design.yaml](workflows/design.yaml)): it
authors the HLD, then runs an **open-question loop** — each open question is presented one at
a time (Claude `AskUserQuestion`-style: suggested answers + Other, plus "You decide" and
"Skip / defer"), the HLD is refined from the answers, and the loop repeats until no blocking
questions remain. Questions live in a machine-readable
`.sdlc/<slug>/open-questions.json` (validated against
[`workflows/open-questions.schema.json`](workflows/open-questions.schema.json) by
[`workflows/validate_open_questions.py`](workflows/validate_open_questions.py)); the HLD's
"Open questions" section is its human mirror. Run standalone via `/plan`, the same loop is
driven by Claude Code's native `AskUserQuestion`. After the loop it pauses for human approval,
then `backend-design` and `frontend-design` each
author one LLD for their stack (`docs/technical/<slug>/lld/`), and `/api-contract` reconciles
them into the cross-repo contract (`contracts/<slug>/`). A human reviews the LLDs + contract
at the next gate. The design skills also emit a machine-readable **task DAG**
(`.sdlc/<slug>/<stack>/tasks.json`, validated against
[`workflows/tasks.schema.json`](workflows/tasks.schema.json) by
[`workflows/validate_tasks.py`](workflows/validate_tasks.py)) that the implementation phase
fans out over — independent slices run in parallel, dependent tasks in order. Per-run proof
lands under `.sdlc/`; exact paths are in `skills.config.yaml` under `artifacts:`.

## Configure

[`skills.config.yaml`](skills.config.yaml) is the one file you edit. It selects, per step:

- which skill runs it;
- which **helper skill** (if any) it delegates part of the work to — a bare skill name, or
  `none` to keep everything in-pack;
- the reviewer per stack and the artifact paths.

The default flow needs exactly one external pack (Superpowers, installed by the script). Every
other helper slot ships as `none`. **Review any third-party skill before wiring it in** — treat
marketplace skills as untrusted code.

Conductor-only knobs (fix-loop cap, coverage gate, environment lifecycle) live in
[`workflows/workflow.config.yaml`](workflows/workflow.config.yaml). Per-step model choices are
set directly on each workflow step (`model:` field).
