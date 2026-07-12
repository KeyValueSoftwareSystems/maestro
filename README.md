# Maestro — a deterministic orchestrator for agentic coding harnesses

Maestro runs a multi-step workflow — agents, human gates, scripts, loops, parallel
forks — **inside your own AI coding session**. No headless runner, no API key, no
per-seat orchestration bill: the *lead agent* is your interactive Claude Code / Cursor
session, and a small stdlib-Python engine decides every step so the LLM never has to
interpret the graph.

**You define the workflow; you bring the skills.** The engine is the product. A
workflow is a YAML file describing what runs in what order; each agent step names a
*skill* (a reusable prompt) — yours, ours, or a third party's (Obra, Superpowers, …).
The workflow owns *where* artifacts land and *when* each step runs; the skill owns only
*how* to do its one job, so any skill can be swapped for another without touching the
graph.

**Shipped as an example: a full AI-SDLC pipeline** (`workflows/sdlc-main.yaml` + the
`skills/` pack) — design → review → implement → QA → release. It's a worked example you
can run today and a template to fork, not a fixed product:

```
requirement → HLD → [open-questions loop → approve] → parallel LLDs → API contract
   → functional test cases → architecture review → [approve]
   → implement per stack (parallel, sliced, reviewed, bounded fix loop)
   → QA → review pack → [approve → release]
```

Core guarantees, whatever workflow you run: every producing step writes an artifact to
disk and the engine refuses to advance without it — **proof, not promises**. Every
irreversible decision goes through a human gate. Kill your session anytime; the run
resumes exactly where it stopped.

## How it works

```
            you: /maestro my-feature
                     │
       ┌─────────────▼──────────────┐    engine/maestroctl.py (stdlib python3)
       │  LEAD AGENT (your session) │───► next → ONE action as JSON
       │  dispatches, never decides │◄─── complete / gate-record / fail
       └──┬─────────┬──────────┬────┘
          ▼         ▼          ▼
      subagents   scripts    you (gates)
      (skill +    (validators,
       model per   stubs)
       step)
```

- **`workflow.yaml`** — the graph: 5 node types (`agent`, `gate`, `script`, `parallel`,
  `subworkflow`), per-node routes with tiny conditions, and **back-edges for loops**
  (an arrow to any earlier step; the engine cascade-resets downstream work and enforces
  a per-node visit cap so loops can't run away). Spec: [docs/workflow-spec.md](docs/workflow-spec.md).
- **`.maestro/<slug>/state.yaml`** — the run ledger. Only the engine writes it. Resume,
  revise-cascades, gate history, parallel-join bookkeeping all live here.
- **The lead agent never interprets the graph.** The deterministic resolver serves one
  fully-rendered action at a time; the LLM just dispatches it. That is what makes an
  LLM-driven orchestrator reliable — and it's all plain, tested Python
  (`python3 engine/tests/run_all.py`, no LLM in the loop).
- **Agent steps are instruction-first**: write what the step should do; optionally pin
  a skill (the shipped workflows pin everything for reproducibility) and a model.
  Subagents run in parallel where the harness supports it (Claude Code); elsewhere the
  same workflow runs inline and sequential — same engine, same state.

## The visual builder

Run **`./maestro ui`** from your repo — it serves the builder on a local port (default
`8422`, override with `--port`) and, because it knows which repo it's in, the **Runs** view
loads automatically in *any* browser and **Open**/**Save** work over HTTP. Or double-click
`ui/builder.html` — the same page runs fully offline from `file://` (Runs/Open/Save then
fall back to the browser File System API). Either way:

- **New** gives you a blank canvas; **Open** (server mode) lists every workflow in the
  repo — recursively, tagged so maestro workflows stand out — with a filter box; **Paste**
  loads YAML text;
- **Save** (the toolbar button, `⌘S`) writes to a path you choose under the repo —
  defaults to `workflows/<name>.yaml` for a new file, or the file you opened. The workflow's
  **name/description/inputs** live in the **Workflow settings** panel (click empty canvas
  to deselect a node and it appears in the inspector);
- **instruction-first node editing** — describe the step; skill defaults to *Auto*
  (pin one under Advanced), model/agent are dropdowns;
- drag arrows between nodes — **arrows pointing back create loops**, shown dashed with
  their repeat-limit badge;
- gates' options *are* their outgoing edges; parallel branches edit via drill-in;
- live validation with friendly messages; one-click export that the engine accepts
  (positions persist in a `ui:` key the engine ignores);
- **Runs** (top-right) — reads every `.maestro/<slug>/state.yaml` and shows each run as a
  live status board: pick a slug and the graph colours in as it progresses — **green** done,
  **orange** in progress, **red** failed, grey pending. Read-only. Under `./maestro ui` it
  loads straight from your repo in any browser; opened as `file://` the folder view needs
  Chrome/Edge (Firefox/Safari get a per-run step table via *Load state.yaml…*).

`./maestro ui` and `./maestro install` are dev tooling only — the wrapper never drives a
run or writes `.maestro/**/state.yaml` (that stays the `/maestro` skill + engine's job). The
`maestro` script is dropped at your repo root by the installer.

Workflows are deliberately minimal to write by hand too — this is a complete one:

```yaml
nodes:
  - id: implement
    instruction: Implement the fix described in the requirement, with tests.
    next: review
  - id: review
    instruction: Review the changes; set blocking=true for must-fix issues.
    outputs: [blocking]
    max_visits: 3
    routes:
      - {when: "${steps.review.outputs.blocking} == true", to: implement}
      - {to: end}
```

(`type:` defaults to agent, `start:` to the first node, omitted routing to `end`.)

## Prerequisites

- **python3 ≥ 3.8** (stdlib only — nothing to `pip install`). Check: `python3 --version`.
- **git** and, to install, **bash** + **curl**. Your project must be an initialized git
  repository with at least one commit before the implementation phase — the per-stack
  implement steps run in isolated `git worktree`s, which a non-repo can't provide (`git init
  && git add -A && git commit` once if it isn't one yet).
- An AI coding harness that supports skills — **Claude Code** (full: parallel subagents,
  per-step models) or **Cursor** (inline sequential fallback).
- Optional: **node/npx**, only for auto-installing the six external Superpowers helper
  skills. Without it the flow still runs (skills fall back to inline behavior).
- **OS:** macOS and Linux are first-class. On **Windows use WSL** — the installer is bash
  and the engine's file lock uses `fcntl` (a `msvcrt` fallback exists, but WSL is the
  tested path).

## Install

From the root of your project repo:

```bash
curl -fsSL https://raw.githubusercontent.com/KeyValueSoftwareSystems/kv-skills/main/install.sh \
  | bash -s -- claude-code cursor        # pick your IDE(s)
```

Installs: our skills/commands/agents into `.claude/` / `.cursor/`, the six external
Superpowers skills the flow delegates to, and `engine/` + `workflows/` + `ui/` into your
repo. The engine is stdlib-only python3 — no CLI, no config file, nothing else to install.
The installer prints a recommended `.gitignore` and what to commit; **upgrade** by re-running
the same command (it re-fetches and overwrites `engine/`/`ui/`). *(Private-repo fork? The
piped `curl` can't authenticate — clone it and run `./install.sh` from the checkout.)*

## Run

Everything happens inside your IDE — no CLI:

```
/maestro my-feature                          # full pipeline (workflows/sdlc-main.yaml)
/maestro my-feature workflows/design.yaml    # just one phase
```

On first run the lead agent scaffolds `.maestro/my-feature/requirement/` and asks you to
drop requirement files in (PRDs, tickets, notes — every file is read). Then it validates,
starts or resumes the run, spawns a subagent per step, asks you at gates, and reports
where every artifact landed. Under the hood it drives the engine, which you can also poke
directly:

```bash
python3 engine/maestroctl.py status --slug my-feature      # step table, gates, active steps
python3 engine/maestroctl.py validate workflows/my.yaml    # lint any workflow
python3 engine/maestroctl.py reset --slug my-feature --step review --cascade
```

Prefer manual control? Every step is also a skill you can invoke on its own — the slash
command is the skill's own name: `/plan`, `/backend-design`, `/backend-implement`,
`/qa-automation`, … — same skills, no orchestration.

## Working as a team

The run ledger `.maestro/<slug>/state.yaml` is written **only by the engine** and is
git-tracked on purpose (so a run resumes on any machine). Two consequences for a team:

- **One owner per slug at a time.** Two people driving the same `<slug>` in parallel will
  produce conflicting edits to an engine-owned file. Pick distinct slugs, or hand a run off
  by committing/pushing `.maestro/<slug>/` and letting the next person resume it.
- **Resolving a state conflict:** never hand-merge `state.yaml`. Take one side, then run
  `python3 engine/maestroctl.py status --slug <slug>` to see where it stands and continue,
  or `reset --slug <slug> --step <id> --cascade` to redo from a known-good step.
- If you edit a **workflow file** mid-run, the engine halts on the next command with a hash
  mismatch. Accept the edit with `maestroctl rebase --slug <slug>` (it re-validates first)
  or start over with `reset --slug <slug> --all`.

## Upgrade / uninstall / troubleshooting

- **Upgrade:** re-run the install one-liner. It overwrites `engine/` and `ui/`; your
  `workflows/` and `.maestro/` are left alone.
- **Uninstall:** delete the installed dirs (`.claude/skills|commands|agents`,
  `.cursor/…`, `engine/`, `ui/`). Keep `.maestro/<slug>/` — that's your work.
- **"workflow changed" halt:** see *Working as a team* above (`rebase` or `reset`).
- **A step won't complete (exit 4):** the engine refuses to advance without the declared
  artifact (non-empty) and output fields — re-run the step or `maestroctl fail` it.
- **`status` any time:** `python3 engine/maestroctl.py status --slug <slug>` prints the
  step table, visit counts, and gate history.

## Layout

```
skills/      one SKILL.md per SDLC step + skills/maestro (the lead agent)
agents/      subagent definitions (planner, implementer, reviewer, qa, analyst, general)
commands/    the /maestro slash-command shim (individual steps are invoked as skills)
workflows/   the example pack: sdlc-main / design / impl / qa  — customize or replace
engine/      the deterministic engine (validate · init · next · complete · gate-record
             · fail · reset · rebase · status · graph) + ui_server.py + schemas + validators
ui/          builder.html (single-file visual editor) + embed.py
maestro      repo-local dev wrapper: `maestro ui` (serve the builder) + `maestro install`
.maestro/<slug>/      everything for one feature: requirement/ + all artifacts + state.yaml
```

## Customizing / bring your own

The engine is generic; the SDLC pack is just one workflow. To make it yours:

- **Write your own workflow** — a YAML file with `nodes:` (agent / gate / script /
  parallel / subworkflow), routes, and back-edges for loops. The builder writes it for
  you. Spec: [docs/workflow-spec.md](docs/workflow-spec.md). Run it with
  `/maestro <slug> path/to/your.yaml`.
- **Bring your own skills** — an agent node names a skill; that can be one of ours, one
  you author (`skills/<name>/SKILL.md`), or a third-party pack (Obra, Superpowers, …).
  Because the *workflow node* supplies the instruction, inputs, artifact path and output
  fields at runtime, a skill only has to describe *how* to do its job — so swapping one
  for another is a one-line `skill:` change, or omit `skill:` entirely and let the
  harness auto-pick from installed skills by description.
- **Change a shipped step's behaviour** — edit its skill (`skills/*/SKILL.md`); the flow
  is untouched.
- **Models** — per node (`model: sonnet`) or per workflow (`defaults.model`); values are
  passed to the harness as-is (`haiku` / `sonnet` / `opus` work in Claude Code).
- **Loop bounds** — per node `max_visits` (+ `on_exhausted`), backstopped by
  `defaults.max_visits` (default 10).
- The merge/contract-check/archive scripts in the example pack are **POC stubs** —
  wire them to your real runners.

## Checks

These run in the **pack repo** (the installer strips `engine/tests` from consumer repos):

```bash
python3 engine/tests/run_all.py                    # engine: parser, validator, ledger,
                                                   # resolver sims, full-SDLC e2e (no LLM)
python3 testdata/test_ui_schema_sync.py            # UI ↔ engine anti-drift (+ cross-parser)
python3 testdata/test_workflow_skill_contracts.py  # every node output ↔ its skill contract
open ui/builder.html#selftest                      # in-browser round-trip suite
```
