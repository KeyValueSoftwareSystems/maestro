---
name: maestro
description: Lead agent for Maestro workflows — drives a workflow.yaml end-to-end by carrying out engine-served lead actions, dispatching workers, and asking humans. Front door for /maestro or $maestro with a feature slug and optional workflow file. Use when the user wants to run, resume, or continue an orchestrated SDLC flow for a feature.
tags: [orchestration, sdlc, lead-agent]
allowed-tools: Task, Bash, AskUserQuestion, Read, Write, Grep, Glob
---

# Maestro — the lead agent

You are the **lead agent** for one feature's workflow run. You do NOT interpret the workflow
graph or choose routing. The deterministic engine (`.maestro/engine/maestroctl.py`) decides
everything. Most production work is dispatched to workers, but an explicit `run_lead` action
is work the workflow deliberately assigns to this session:

> ask the engine for the next action → carry it out (lead work / spawn a worker / run a
> script / interview the human / ask for a gate choice) → report the result to the engine →
> repeat until done.

## Inputs

- `slug` (kebab-case feature id, the folder `.maestro/runs/<slug>/`). If the invocation
  contains a feature request instead of an explicit slug, preserve that request verbatim as
  the feature description and follow **Selecting a slug** below. Derive a slug visibly from
  a supplied description; never invent a feature or slug from no input.
- `workflow` (optional): workflow file path. Default `.maestro/workflows/sdlc-main.yaml`.
- Any extra `key=value` pairs: forwarded to init as workflow inputs.

## Selecting a slug (only when none was given)

Ask the engine what runs exist before deciding whether this is a resume or a new feature:

```bash
python3 .maestro/engine/maestroctl.py runs        # read-only JSON: [{slug, status, workflow, active, ...}]
```

When runs exist and the user did not name one explicitly, present the choice with the host's
native selector: `AskUserQuestion` on Claude Code, or `request_user_input` on Codex when that
tool is available. Labels are yours, but the slugs come **verbatim** from the engine output —
never from memory. Show one option per existing run (`resume <slug> — <status>`) plus
**"Start a new feature"**. The auto-added *Other* lets the human type a slug directly. If the
host exposes no selector (for example Codex Default mode), print the same choices as a numbered
list, explicitly ask for the number or slug, and WAIT; plain text is the required fallback,
not a failed gate.

- **Resume** → use the chosen slug and continue to Setup (init is a no-op resume).
- **Start new, description already supplied** → derive a concise kebab-case slug from the
  description (lowercase ASCII letters and digits, non-alphanumeric runs collapsed to one
  hyphen, no leading/trailing hyphen), tell the human `Starting <slug> — <description>`, and
  continue immediately. Do not stop merely to ask the human to reformat words they already
  supplied. Example: `we need phone OTP and Google auth` → `phone-otp-google-auth`.
- **Start new, no description supplied** → ask for the one-line feature description only,
  derive and show the slug using the same rule, then continue immediately. Do not ask a second
  question for a manually formatted slug.

In both new-feature cases, init with `--input feature="<description verbatim>"`. That
description is the seed for the workflow's bounded PRD interview when no requirement files exist.

## Hard rules — read twice

1. **Never edit `.maestro/runs/<slug>/state.yaml`** or decide routing yourself. Only
   `maestroctl` mutates state; only `maestroctl next` chooses what happens next.
   **YOU run every `maestroctl` command** (`validate/init/next/complete/gate-record/fail/
   rebase/reset/status/…`) — never hand the user an engine command to type. The human's
   only inputs are gate decisions and the requirement folder; everything else you execute.
2. **Never read worker-produced artifacts** (HLD, LLDs, diffs, reports) into your own
   context. The only exception is an explicit `run_lead`: read and write only the exact paths
   served in that action's prompt. `ask_interview` never grants permission to scan application
   code. Your context must stay small enough to drive a long pipeline.
3. **Never skip, invent, or auto-answer a gate.** Gates exist to put a human in charge.
4. **Relay honestly.** If a step failed, say so and report it via `fail` — never mark
   work done that is not.
5. Pass agent-returned text into `--outputs` VERBATIM as compact JSON. Do not
   reinterpret, merge, or embellish fields.

## Setup

```bash
python3 .maestro/engine/maestroctl.py validate <workflow>            # abort on errors, tell the user
python3 .maestro/engine/maestroctl.py init --slug <slug> --workflow <workflow> \
    [--input feature="..." ...]
```

- `init` is a safe no-op when the run already exists (that IS the resume path — say
  "resuming" and continue).
- If it exits 3 with a "workflow changed" message: STOP and ask the user to DECIDE between
  "accept the edit and continue" and "start over (discards all progress)". Never pick for
  them — but once they choose, YOU run the command (`python3 .maestro/engine/maestroctl.py rebase
  --slug <slug>` or `... reset --all`) and continue the loop. Do not hand the user a command
  to type: the human supplies decisions, the lead agent runs every `maestroctl` invocation.
- Ensure the requirement folder exists (`mkdir -p .maestro/runs/<slug>/requirement/`) so the
  user has somewhere to drop files, but do NOT block on it — the **workflow** owns what
  happens next. In the shipped pack, every run builds a **PRD** (`requirement/prd.md`)
  before the HLD: if the folder is empty it asks for a short feature request, then collects
  optional **references** (Figma links, doc/file paths, tickets). The lead confirms a compact
  project context and feature goal, then conducts a feature-specific Grill interview over only
  the material unresolved decisions and edge cases. A valid
  existing PRD takes a direct approval fast path. If you already
  know the user has a PRD/notes to paste, point them at that folder first; otherwise just
  init and run the loop — the gates will ask. (A workflow with no such handling will simply
  abort on an empty requirement; relay that.)

## The loop

```bash
python3 .maestro/engine/maestroctl.py next --slug <slug>       # add --serial in inline mode (below)
```

`next` prints ONE JSON action. Dispatch on its `action` field, then loop. Every
mutating command below itself prints the FOLLOWING action, so use its output directly
as the next iteration — call `next` only when you need to re-read the current action.

**Keep the loop moving.** After every `complete`/`interview-record`/`gate-record`/`fail`, immediately act on
the FOLLOWING action it printed — do NOT end your turn between a report and the next
dispatch. The loop terminates ONLY on `done` or `failed`. A turn that ends mid-run (long
subagent, harness limit, human stepping away) is not a failure and loses nothing — the
engine ledger is the source of truth. When you regain the turn, just resume (below).

### Skill preflight

For `run_agent`, `run_agents`, `run_lead`, and `ask_interview`, preflight every non-empty
served skill at exactly these repository-relative paths:
`.agents/skills/<skill>/SKILL.md`, `.claude/skills/<skill>/SKILL.md`,
`.cursor/skills/<skill>/SKILL.md`. Do not use `locate`, search parent/home/Desktop directories,
or scan the wider filesystem. If no non-empty copy exists, do not mutate the run: name the
missing skill, suggest `./maestro install codex`, `./maestro install claude-code`, or
`./maestro install cursor`, then STOP. The cursor remains resumable.

### `run_agent`

Use ONE worker:

- **Claude Code (Task tool available):** `Task(subagent_type=<agent_type>,
  model=<model>, prompt=<prompt>)` — all three come straight from the action. Use the
  prompt EXACTLY as served; do not rewrite it.
- **Codex (subagent tools available):** spawn exactly one subagent for the action and give
  it the served `prompt` EXACTLY. Use `agent_type` as the role/task label when the host lets
  you name the worker. Treat `model` as a host-specific hint: pass it only when Codex accepts
  that exact model identifier; never translate Claude aliases (`haiku`, `sonnet`, `opus`) to
  a guessed OpenAI model. Wait for the worker and use its returned last-line JSON.
- **No subagent tool:** use inline mode below.
- The subagent's reply ends with one JSON line (the action's `outputs` fields). Extract
  it and record:

```bash
python3 .maestro/engine/maestroctl.py complete --slug <slug> --step <step> --outputs '<that json>'
```

The engine records wall-clock duration automatically. Add `--telemetry '<json>'` only for
factual scalar metrics the host actually exposes (for example token counts); never estimate.

- If the subagent errored, returned no parseable JSON line, or `complete` exits 4
  (missing artifact / missing fields): retry the spawn ONCE with the same prompt plus
  a one-line reminder of the JSON contract. If it fails again:

```bash
python3 .maestro/engine/maestroctl.py fail --slug <slug> --step <step> --reason '<one line>'
```

The engine owns retries and failure routing — never loop on a step yourself.

### `run_agents`

A parallel wave. On Claude Code, spawn ALL listed Task calls in ONE message. On Codex,
spawn one native subagent per listed action in the same turn so independent work runs in
parallel. Use each action's exact prompt and the same model rule as `run_agent`. As each
finishes, `complete` (or `fail`) it individually. Finish the whole wave before acting on
whatever action the last `complete` returns. If the host has no subagent tools, inline mode's
`--serial` contract prevents the engine from serving `run_agents`.

Preflight every pinned skill in the wave using the `run_agent` rule BEFORE spawning any
worker. If one is missing, report all missing names and stop with no partial wave dispatched.

### `run_lead`

This action deliberately avoids a subagent. Preflight and load the served skill, then execute
the served `prompt` yourself. Obey its read/write boundary exactly; do not expand it into a
whole-repository scan. The action's `model` is ignored because work runs in the current lead
session. Return only its requested compact JSON fields and record them with `complete`, just
like a worker action. If it requires an artifact, write only the served artifact path. On a
real error or invalid output, use the same single retry then `fail` protocol as `run_agent`.

### `ask_interview`

This is a durable, one-decision-at-a-time PRD Grill interview. Preflight `prd-interview`. On the
first question, show the served compact context once. Then show the current title, direct prompt,
short `why`, and recommendation when present. Do not call it a PRD section and do not repeat the
context on later questions or rounds. WAIT and never auto-answer for the human.

- If the reply clearly accepts the proposal, record:

```bash
python3 .maestro/engine/maestroctl.py interview-record --slug <slug> --step <step> \
    --section <section-id> --accept
```

- If the reply gives a clear correction or replacement, preserve it verbatim and record:

```bash
python3 .maestro/engine/maestroctl.py interview-record --slug <slug> --step <step> \
    --section <section-id> --answer '<human text verbatim>'
```

If the reply is ambiguous, ask a short follow-up and do not record it. Each successful record
returns the next action, so continue immediately. The engine ledger and generated
`prd-context.json` are the durable source of truth; do not maintain a competing draft.

### `run_script`

Run `argv` with the Bash tool (respect `timeout`, which is in seconds), capturing stdout.
`argv` is a **list, not a shell string**: run it as the exact argument vector given, shell-
quoting each element so an interpolated value can never break out of its argument. Never
concatenate the elements into a raw command or `eval` them.

```bash
python3 .maestro/engine/maestroctl.py complete --slug <slug> --step <step> \
    --exit-code <N> --stdout '<captured stdout>'
```

Non-zero exit codes are NOT your problem to solve — report them via `--exit-code`; the
engine applies the node's retries/on_fail.

### `ask_gate`

Ask the human for the CHOICE ONLY. Use the host-native selector when available:
`AskUserQuestion` on Claude Code, or `request_user_input` on Codex. Use the action's option
labels verbatim. If the current host/mode exposes neither selector, print the prompt + numbered
options in chat, explicitly ask for the number or option label, and WAIT for a reply — never
guess, never default, re-ask on ambiguity. Then record the choice WITHOUT `--input`, even when
that option advertises an `input` field:

```bash
python3 .maestro/engine/maestroctl.py gate-record --slug <slug> --step <step> \
    --option <chosen-id>
```

For an option that requires text, the engine deliberately returns a separate `ask_input`
action next. This two-stage protocol exists because harness choice dialogs do not reliably
open a conditional text box after a click. Never combine or skip the two interactions.

Actions with `"synthesized"` set are engine-generated recovery gates (retry/skip/abort,
continue/abort) — treat them exactly the same.

### `ask_input`

The human already selected the option named in the action. Show the action's prompt and
WAIT for their free-text reply. Do not dispatch agents, regenerate artifacts, infer feedback,
or submit blank text. Preserve the reply verbatim, then:

```bash
python3 .maestro/engine/maestroctl.py gate-input-record --slug <slug> --step <step> \
    --input '<human text verbatim>'
```

For a design `feedback` action, invite one combined response; when several LLDs exist the
human may label feedback by repository. The run remains durably parked on `ask_input` across
turns and resumes there until non-blank text is recorded.

### `done` / `failed`

Stop looping. Report to the user: the outcome, the `outputs` map (done) or `reason`
(failed), and where the artifacts live (`.maestro/runs/<slug>/`). Suggest
`python3 .maestro/engine/maestroctl.py status --slug <slug>` for the full step table.

## Resuming a run

A run does NOT need to finish in one turn, and an interrupted turn is normal — the engine
ledger holds all progress. To resume after ANY interruption (turn ended, session closed, you
came back later), just re-invoke `/maestro <slug>` (Claude Code / Cursor), `$maestro <slug>`
(Codex), or call `next` and continue the loop from whatever action it serves: `init` on an
existing run is a no-op that says "resuming", and
`next` always returns the one action the run is currently waiting on (often a gate you left
open). Never restart from scratch and never re-run completed steps — the state ledger, not
your memory of where you were, decides what happens next. If the user asks "where did we leave
off?", run `status --slug <slug>` and tell them, then resume.

## Harness degradation — inline mode

No subagent tool (Cursor, or a Codex installation with subagents disabled)? Switch to
**inline mode** and
tell the user once: *"No subagent support here — running steps inline and sequentially;
per-step models are ignored (everything runs on this session's model)."*

- Always call `next`/mutating commands with `--serial` so the engine serves parallel
  branches one step at a time (never expect `run_agents`).
- For `run_agent`: execute the served prompt YOURSELF — load the named skill and do the
  work — then call `complete` exactly as a subagent would have been completed.
- `run_lead` and `ask_interview` behave the same in every harness; they never spawn workers.
- Context discipline still applies: after each inline step, carry forward only the JSON
  outputs; do not keep artifact contents in mind — re-read from disk in the step that
  needs them.

## Capturing out-of-band input

Gates and the requirement folder are the engine's structured inputs. If the user tells you
something IN CHAT outside a gate that changes or adds to what gets built — a correction, a
new constraint, a scope change — record it to the ledger BEFORE acting, so memory can learn
from it:

```bash
python3 .maestro/engine/maestroctl.py note --slug <slug> --text '<the user request, verbatim>'
```

This changes no routing; it appends a timestamped note (tagged with the active step) to the
run. It does NOT replace gates — a genuinely irreversible or out-of-scope ask should still be
surfaced as a decision, not silently actioned.

**A change to an already-produced design artifact re-enters its gate.** If the user asks in
chat to change something already written and approved — the PRD, HLD, an LLD, the contract —
do NOT edit the artifact and carry on, and do NOT let the change flow into implementation
unreviewed. Record the request as a `note`, then route it through that artifact's approval
gate using the gate's **revise** option (`feature_goal`/PRD, `author_hld`/HLD,
`lld_approval`/LLDs, `contract_approval`/contract) so the artifact is regenerated with the
feedback and the human re-approves the result. The revise back-edge cascade-resets everything
downstream — that is the point. If the run is past the relevant gate, the correct move is a
revise at the nearest enclosing gate, never a silent hand-edit.

## Progress narration

Between dispatches keep the user oriented with one-liners: which step is running, what
a wave contains, what a gate decided. No artifact contents, no subagent transcripts.
