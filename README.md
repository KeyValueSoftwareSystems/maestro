# Maestro

A ready-to-install pack of **AI skills** and a **workflow orchestrator** that runs a feature
through the KeyValue software-development lifecycle: high-level design → detailed design →
implementation → review → QA → release — with a human approval at each gate.

## Why

Building a feature well means the same steps every time: design it, review the design,
implement to a contract, test it, review the code, QA it, ship it. This pack encodes those
steps once so every developer runs them the same way.

- **Run it your way.** Let [Conductor](https://github.com/microsoft/conductor) orchestrate the whole pipeline end-to-end, or run each
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
4. installs **Conductor** (installing [`uv`](https://github.com/astral-sh/uv) first if it's missing; skip the whole step with `--no-conductor`).

> Conductor runs the full pipeline; you don't need it if you only use the slash commands.

## How to run

### As an orchestrator (Conductor)

Conductor runs the skills for you, end to end, with automatic approval gates. Same skills,
same artifacts — it just drives the sequence.

**The easy way — by feature slug.** Drop your PRD in a per-feature folder and run one command
from your repo root:

```bash
mkdir -p features/user-authentication
$EDITOR features/user-authentication/prd.md               # write the PRD here
maestro user-authentication                               # run full pipeline
maestro user-authentication --path=workflows/design.yaml  # run design phase only
```

`maestro` (installed by the installer) resolves the PRD at `features/<slug>/prd.md` and runs the
default pipeline at `http://127.0.0.1:8080` (set `web.port` in `maestro.config.yaml`). Use `--path=<file>`
to run a specific workflow. Extra flags go after `--`, e.g. `maestro user-authentication -- --dry-run`.

Run individual workflows for specific phases:

| Workflow | Command | Purpose |
|----------|---------|---------|
| [`design.yaml`](workflows/design.yaml) | `maestro <slug> --path=workflows/design.yaml` | HLD → LLDs → API contract |
| [`backend_impl.yaml`](workflows/backend_impl.yaml) | `maestro <slug> --path=workflows/backend_impl.yaml` | Backend implementation & tests |
| [`frontend_impl.yaml`](workflows/frontend_impl.yaml) | `maestro <slug> --path=workflows/frontend_impl.yaml` | Frontend implementation & tests |
| [`qa.yaml`](workflows/qa.yaml) | `maestro <slug> --path=workflows/qa.yaml` | QA automation |

### Resuming a partially-run workflow

Sub-workflows record completed steps in `.sdlc/<slug>/state.json`. Re-run the same command to
resume from the first incomplete step. To force a rebuild:

```bash
python3 workflows/state.py reset --slug <slug> --step <step-id>   # rebuild one step
python3 workflows/state.py reset --slug <slug> --all              # rebuild everything
```

Human approval gates always re-ask, even on resume.

### As skills (you orchestrate manually)

Run the slash commands yourself, in order, in any IDE (Claude Code, Cursor, Copilot) — you
review each artifact before moving to the next:

```
/plan feature="Add user authentication" feature_slug="user-authentication"   # high-level design, then approve
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

## Customisable flow

This is the basic workflow — a starting point you can customize to fit your process. Each step
captures decision points, produces artifacts, and gates on their existence before advancing.
Completed steps are recorded in `.sdlc/<slug>/state.json` so partial runs resume correctly.

```text
                          feature + PRD
                                │
                                ▼
                     ┌──────────────────────┐
                     │       HLD  /plan      │  ⟲ open-questions loop
                     └──────────┬───────────┘     (refine until resolved)
                                ▼
                          — ✋ approve —
                                │
                 ┌──────────────┴──────────────┐
                 ▼                              ▼
       ┌──────────────────┐          ┌───────────────────┐
       │  backend-design  │          │  frontend-design  │
       └─────────┬────────┘          └─────────┬─────────┘
                 └──────────────┬──────────────┘
                                ▼
                          /api-contract
                                │
                                ▼
                          — ✋ approve —
                                │
                                ▼
                      architecture-review
                                │
                                ▼
                          — ✋ approve —
                                │
                 ┌──────────────┴──────────────┐
                 ▼                              ▼
   ┌──────────────────────────┐   ┌──────────────────────────┐
   │  backend-impl            │   │  frontend-impl           │
   │  DAG→slices→merge→tests  │   │  DAG→slices→merge→tests  │
   │  →verify→review          │   │  →a11y→review            │
   └─────────────┬────────────┘   └─────────────┬────────────┘
                 └──────────────┬───────────────┘
                                ▼
                            integrate
                                │
                                ▼
                                QA
                                │
                                ▼
                            review-pack
                                │
                                ▼
                          — ✋ approve —
                                │
                                ▼
                             release
```

## Configure

### `skills.config.yaml` — Workflow configuration

This file defines which skill backs each SDLC step. Edit once, change everywhere:

| Setting | Purpose |
|---------|---------|
| `skill:` | Which skill runs this step |
| `external:` | Optional helper skill (`none` to use built-in) |
| `reviewer:` | Who reviews the output (backend/frontend stack) |
| `artifacts:` | Where artifacts are saved (`<slug>` is feature slug) |

**Review third-party skills before use.** The default flow requires [Superpowers](https://github.com/obra/superpowers) (installed by the script); all other slots default to `none` (built-in).

### `workflows/maestro.config.yaml` — Orchestration settings

Set Conductor-specific knobs (fix-loop cap, coverage gate, environment lifecycle):

| Setting | Default | Purpose |
|---------|---------|---------|
| `models.default` | `claude-haiku-4-5` | Fallback model for any agent |
| `models.agents.<name>` | `claude-haiku-4-5` | Per-agent model override |
| `web.port` | `8080` | Dashboard port |
| `fix_loop.max_attempts` | `3` | Fix-loop cap before escalating |
| `gates.coverage_threshold` | `80` | Minimum test coverage |

### Model selection

**Per-agent, one place.** Each agent's model is set under `models.agents` in
`maestro.config.yaml`, keyed by agent name:

```yaml
models:
  default: claude-haiku-4-5   # fallback for any agent not listed
  agents:
    author_hld:  claude-sonnet-5   # bump just the HLD author
    arch_review: claude-sonnet-5   # and the architecture review
    # everything else -> claude-haiku-4-5
```

Any agent you don't list runs on `claude-haiku-4-5`.
