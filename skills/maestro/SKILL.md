---
name: maestro
description: Lead agent for Maestro workflows — drives a workflow.yaml end-to-end by carrying out engine-served lead actions, dispatching workers, and asking humans. Front door for /maestro or $maestro with a feature slug and optional workflow file. Use when the user wants to run, resume, or continue an orchestrated SDLC flow for a feature.
tags: [orchestration, sdlc, lead-agent]
allowed-tools: Task, Bash, AskUserQuestion, Read, Write, Grep, Glob, TodoWrite
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
never from memory. Label `kind: repo-lld` entries as
`<repo> LLD for <parent_slug> — <status>`; label feature entries as
`resume <slug> — <status>`. Show one option per existing run plus
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
   context. Exceptions: an explicit `run_lead` (read and write only the exact paths served in
   that action's prompt) and a design-approval question (see `ask_gate`). Interview
   discussions never happen in your context: they go to an isolated `discussant` subagent or a
   side chat (see `ask_interview_batch`). Your context must stay small enough to drive a long
   pipeline.
3. **Never skip, invent, or auto-answer a gate.** Gates exist to put a human in charge.
4. **Relay honestly.** If a step failed, say so and report it via `fail` — never mark
   work done that is not.
5. Pass agent-returned text into `--outputs` VERBATIM as compact JSON. Do not
   reinterpret, merge, or embellish fields.

## Setup

Before init, inspect an explicitly selected or resumed slug for the one-time current-format
upgrade:

```bash
python3 .maestro/engine/maestroctl.py upgrade-run --slug <slug> --workflow <workflow>
```

When it returns `needed: true`, show its mode and selected repositories. For `legacy-rebuild`, also
show the PRD/HLD validation result and existing LLD drafts; `compatible-rebase` preserves the exact
current cursor and needs no document validation. Ask the human to choose **Upgrade this run once** or **Cancel** using the
normal native-selector fallback rules. Never apply it silently. If approved, YOU run:

```bash
python3 .maestro/engine/maestroctl.py upgrade-run --slug <slug> --workflow <workflow> --apply
```

The engine backs up the old ledger before changing it. After a successful upgrade, continue Setup
normally. Do not offer the upgrade again when `needed: false`; the current run-format marker makes
this a one-time operation. Never use `rebase` as a substitute when `upgrade-run` says an upgrade is
needed.

```bash
python3 .maestro/engine/maestroctl.py validate <workflow>            # abort on errors, tell the user
python3 .maestro/engine/maestroctl.py init --slug <slug> --workflow <workflow> \
    [--input feature="..." ...]
```

- `init` is safe when the run already exists (that IS the resume path — say "resuming" and
  continue); it only releases worker claims left by an interrupted session. Its output carries
  `todo`, the run's stage checklist: put it in your task list now (see **Task list**).
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

### Repository LLD resume selector

After a no-op init of an existing run, ask the engine for its repo workstreams:

```bash
python3 .maestro/engine/maestroctl.py workstreams --slug <slug>
```

When it returns `available: true` and `<slug>` is the returned `parent_slug`, ALWAYS present a
native selector before calling `next`, even when the user explicitly supplied the parent slug.
Offer every returned child as `Work on <repo> LLD — <status> (<active step>)` plus
`Parent coordinator — check whether all LLDs are ready`. Use only returned slugs and statuses.

- Child selected: switch the active slug to that child, validate its returned `workflow`, no-op
  init it, and drive that child normally. Do not mutate the parent.
- Parent coordinator selected: keep the parent slug and continue to its status/refresh gate.
- If the invocation already named a repo LLD child, honour that direct choice without asking a
  second time.

This selector is intentionally repeated on every parent resume while LLD workstreams are pending.
It prevents a returning backend, frontend, or Flutter developer from accidentally driving the
shared parent or another team's ledger.

## The loop

```bash
python3 .maestro/engine/maestroctl.py next --slug <slug>       # add --serial in inline mode (below)
```

`next` prints ONE JSON action. Dispatch on its `action` field, then loop. Every
mutating command below itself prints the FOLLOWING action, so use its output directly
as the next iteration. **Act on every action the engine returns** — serving a worker step
claims it, so a returned action you ignore is never served again until the run is resumed.
To re-read the current action without claiming anything, use `next --peek`.

The engine runs its own helper scripts (`python3 .maestro/engine/*.py`) inside these calls
and completes them before answering; they are listed under `auto_scripts` in the returned
action. Never run or complete those steps yourself — at most mention them in narration.

**Keep the loop moving.** After every mutation command, immediately act on the FOLLOWING action
it printed — do NOT end your turn between a report and the next
dispatch. The loop terminates ONLY on `done` or `failed`. A turn that ends mid-run (long
subagent, harness limit, human stepping away) is not a failure and loses nothing — the
engine ledger is the source of truth. When you regain the turn, just resume (below).

### Skill preflight

For `run_agent`, `run_agents`, `run_lead`, `ask_interview`, and `ask_interview_batch`, preflight
every non-empty served skill at exactly these repository-relative paths:
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
parallel. Use each action's exact prompt and the same model rule as `run_agent`. If the host
has no subagent tools, inline mode's `--serial` contract prevents the engine from serving
`run_agents`.

Served worker steps are claimed: later calls never re-serve them, they return only NEWLY
ready work. Record results in whichever way matches how your workers report back:

- **Workers return together** (parallel Task calls in one message): record the whole wave in
  ONE call, then act on the single action it returns:

```bash
python3 .maestro/engine/maestroctl.py complete-batch --slug <slug> --results \
    '[{"step":"<step>","outputs":{...}},{"step":"<step>","fail":"<one line>"}]'
```

  Each entry applies independently. The output's `batch` list reports each step; an
  `error` entry (exit code 4) was NOT recorded — apply the `run_agent` retry protocol to that
  step alone (re-spawn once, then `complete` or `fail` it), while still acting on the
  returned action for everything else.
- **Workers finish one at a time** (background workers that notify you): `complete` each as it
  arrives and immediately act on the action that call returns — dispatch newly ready
  workers, answer a gate — while the others keep running. A slow worker never holds back
  another branch.

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

This is a durable, one-decision-at-a-time Grill interview. Preflight the served skill. On the
first question, show the served compact context once. Then show the current title, direct prompt,
short `why`, the recommendation, and any served `alternatives` with their trade-offs. Do not call
it a document section and do not repeat the context on later questions or rounds. WAIT and never
auto-answer for the human. If they are unsure or ask something back, run the isolated
**discussion** described under `ask_interview_batch` before recording.

Record exactly one outcome — the response kinds are the same as in a batch:

```bash
python3 .maestro/engine/maestroctl.py interview-record --slug <slug> --step <step> \
    --section <section-id> --accept                       # the recommendation
#   --option <n>                                           # served alternative n (1-based)
#   --answer '<human text verbatim>'                       # their own answer
#   --assume                                               # recommendation as a working assumption
#   --defer '<human note verbatim>'                        # parked, not decided
#   [--discussion '<one-sentence summary>'] [--raise '<point verbatim>' ...]
```

If the reply is ambiguous, ask a short follow-up and do not record it. Each successful record
returns the next action, so continue immediately. The engine ledger and generated
`prd-context.json` are the durable source of truth; do not maintain a competing draft.

Exception: when an LLD interview reply explicitly changes an approved parent decision, record the
answer normally, but before acting on the returned next action follow **Capturing out-of-band
input** and ask how to handle that design change. This does not reinterpret an ordinary repository
answer; it applies only when the human or served question identifies a real upstream correction.

### `ask_interview_batch`

A full Grill round, run as a conversation in three phases. Preflight the served skill (`prd-
interview`, `hld-interview`, or `lld-interview`) and record nothing until all three are done
(the only exception is the partial record before a side-chat handoff).

**1. Collect.** When `presentation` is `popup`, use the host's native question UI
(`AskUserQuestion` on Claude or `request_user_input` on Codex when available). Never print the
question batch into normal chat. Put as many questions in each popup as the host supports, then
immediately open the next popup until the round is covered; do not analyze, run a command, or
record between popups. Each item shows the title, direct prompt, short `why`, and these options:

- the recommendation (`proposal`) labelled as recommended;
- each served `alternative`, its `tradeoff` as the option description;
- **Not sure — let's discuss**;
- the host's free-form option, for the human's own answer or a side question ("btw, how does
  billing handle this today?").

A `kind: direction` item presents the proposed overall design for the human to confirm, challenge,
or discuss — give its summary room (the option description or preview). End the round's last
popup with one extra item, **Anything to add?** (`Nothing to add` / `I want to raise something`),
so the human can lead, not only respond. If `presentation` requires a popup but the host exposes
no native question tool, do not fall back to a chat questionnaire and do not mutate the run;
report the missing capability in one line and stop. When `presentation` is `chat`, use one
numbered chat message as the compatibility fallback, listing the same options.

**2. Discuss — never in your context.** Take each item where the human chose *Not sure*, asked
something back, or left a `must_resolve` fact open, one at a time. The reading and reasoning for a
discussion must never enter your context, so you only relay. Get the engine's brief first:

```bash
python3 .maestro/engine/maestroctl.py interview-brief --slug <slug> --step <step> \
    --section <question-id>                # add --mode side for a side chat
```

*Default — isolated subagent.* Preflight the brief's `skill`, then spawn its `agent_type` with its
`model` (Claude Code `Task`; Codex native subagent). Send the brief's `prompt` VERBATIM followed by
the human's message verbatim. Show the human the subagent's reply verbatim, minus its final JSON
line. Relay each follow-up to the SAME subagent (`SendMessage` on Claude Code); where the host
cannot continue a subagent, start a fresh one with the brief, the last JSON `summary`, and the new
message. Never answer from your own reading, never read the evidence yourself, and never
paraphrase or extend a reply. Keep only each final JSON line (`status`, `candidate`, `summary`);
let the reply text go.

*Side chat — for a deep dive, or the human's choice.* Offer it whenever the human wants room to
dig ("take it to a side chat"), and use it always where there is no subagent support (inline
mode). First record every other clear answer of the round with `interview-record-batch` (a partial
batch is valid and leaves the rest pending). Then run `interview-brief --mode side` and show the
human its `side_chat` command for their harness: open a new chat, run it, come back and say
*continue*. End your turn. On *continue*, call `next`: a question settled in the side chat is gone
from the served round; one still open is served again — ask whether to discuss it again or answer.

Close each subagent discussion with a native selector: the subagent's `candidate` (when present),
the recommendation, any served alternative, *Use the recommendation as a working assumption*,
*Park it as an open item*, *Take it to a side chat*, plus the free-form option. For *I want to raise
something*, take the point in their words and confirm the exact wording to record; route any
question it prompts through the same discussion path.

**3. Record.** Map only answers the human actually gave. Never infer, silently accept, or drop an
answer. Record the whole round, discussed items and raised points included, in ONE command:

```bash
python3 .maestro/engine/maestroctl.py interview-record-batch --slug <slug> --step <step> \
    --responses '{"a":{"accept":true},"b":{"option":2},"c":{"answer":"verbatim","discussion":"…"},
                  "d":{"assume":true},"e":{"defer":"verbatim note"}}' \
    [--raise '<raised point verbatim>' ...]
```

`accept` and `assume` both take the recommendation; `assume` marks it unverified. `defer` parks the
decision — it is never confirmed. `discussion` is the subagent's final JSON `summary`, so the next
queue does not re-ask what was explored; never put the human's answer there. The engine validates the
whole batch before recording anything, so one malformed response cannot partially update the run.
Continue immediately with the returned action.

Exception: after the atomic record, if an LLD response explicitly changes an approved parent
decision, pause before acting on the returned action and follow **Capturing out-of-band input** for
that response. Never analyze or interrupt between popup chunks; correction handling happens only
after the complete batch is durably recorded.

### `wait`

Every unfinished step is a worker already in flight; there is nothing new to dispatch.
Keep waiting for those workers and record each as it finishes. If they are not actually
running (the session restarted and lost them), run `init` again — it releases the claims
and the next call re-serves them.

### `run_script`

Only scripts that are not engine helpers reach you (engine helpers run inside the engine
call). Run `argv` with the Bash tool (respect `timeout`, which is in seconds), capturing stdout.
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

**Questions at a design-approval gate.** If, instead of choosing, the human asks about the PRD,
HLD, or LLD the gate names ("why one service?", "what happens on retry?"), answer it: read only the
artifact the gate prompt names, and only the part the question needs. Explain, do not edit, and do
not record anything. Then present the same gate again. If the conversation produces a change they
want, that is their *revise* option's feedback — never apply it yourself.

### `ask_input`

The human already selected the option named in the action. Show the action's prompt and
WAIT for their free-text reply. Do not dispatch agents, regenerate artifacts, infer feedback,
or submit blank text. Preserve the reply verbatim, then:

```bash
python3 .maestro/engine/maestroctl.py gate-input-record --slug <slug> --step <step> \
    --input '<human text verbatim>'
```

For a design `feedback` action, request the change for that artifact only. Repository LLD feedback
belongs to its `<feature>--lld--<repo>` child run, never the parent or another repo's child. The run
remains durably parked on `ask_input` across turns until non-blank text is recorded.

### `done` / `failed`

Stop looping. Report to the user: the outcome, the `outputs` map (done) or `reason`
(failed), and where the artifacts live (`.maestro/runs/<slug>/`). Suggest
`python3 .maestro/engine/maestroctl.py status --slug <slug>` for the full step table. The
final action carries the finished `todo`; mirror it so the task list ends complete.

## Resuming a run

A run does NOT need to finish in one turn, and an interrupted turn is normal — the engine
ledger holds all progress. To resume after ANY interruption (turn ended, session closed, you
came back later), just re-invoke `/maestro <slug>` (Claude Code / Cursor), `$maestro <slug>`
(Codex), which calls `init` and then `next`, and continue the loop from whatever action it
serves. `init` on an existing run says "resuming" and releases any worker claims left by the
interrupted session, so `next` re-serves workers that were in flight and otherwise returns the
action the run is currently waiting on (often a gate you left open). Always `init` before
`next` when resuming; without it, lost in-flight workers show as `wait`. Never restart from scratch and never re-run completed steps — the state ledger, not
your memory of where you were, decides what happens next. If the user asks "where did we leave
off?", run `todo --slug <slug>` (the stage checklist; `status` has the full step table) and tell
them, then resume.

## Harness degradation — inline mode

No subagent tool (Cursor, or a Codex installation with subagents disabled)? Switch to
**inline mode** and
tell the user once: *"No subagent support here — running steps inline and sequentially;
per-step models are ignored (everything runs on this session's model)."*

- Always call `next`/mutating commands with `--serial` so the engine serves parallel
  branches one step at a time (never expect `run_agents`).
- For `run_agent`: execute the served prompt YOURSELF — load the named skill and do the
  work — then call `complete` exactly as a subagent would have been completed.
- `run_lead`, `ask_interview`, and `ask_interview_batch` behave the same in every harness,
  except that interview discussions always use the side chat: with no subagent, there is no
  other way to keep them out of this context.
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

**A change to an already-approved design needs an explicit handling decision.** If the user asks
in chat—or clearly answers an LLD question—in a way that changes an approved PRD, HLD, LLD,
contract, or verification rule, do not silently edit or ignore the conflict. Record the request as
a `note`, then present exactly these choices with the native selector:

1. **Update the base design now** — use the relevant gate's existing revise route
   (`feature_goal`/PRD, `prepare_hld_questions`/HLD, the repository child's `lld_approval`/LLD,
   `contract_approval`/contract). This deliberately reruns affected design work.
2. **Approve as a correction and continue** — preserve the base approval evidence and record the
   user's decision verbatim with the engine command below. This is the fast path.
3. **Reject or defer this change** — do not put it into the effective design and do not implement it.

For the correction fast path, choose the narrowest factual scope: `product`, `architecture`,
`repository`, `contract`, `verification`, or `cross-cutting`. A repository LLD child automatically
targets its parent and repository. YOU run, never hand the command to the user:

```bash
python3 .maestro/engine/maestroctl.py correction-record --slug <current-slug> \
  --scope <scope> [--repo <repo>] --text '<approved human wording verbatim>'
```

Report the returned correction ID, then continue from the engine's existing cursor without a reset.
The per-correction receipt is the approval record; `approved-corrections.md` and
`effective-design.json` are engine-rendered downstream context. Approved corrections override
conflicting base text in LLD authoring, contract/test generation, architecture review,
implementation, QA, review, and retrospect. Archive folds them once into validated copies under
`final-design/`; it never changes the original hash-bound approvals.

## Task list

`init`, and every action whose stage picture changed, carries `todo`: the run's stage checklist
as `[{content, status}]` (`pending` | `in_progress` | `completed`), built by the engine from the
ledger — stages in order, the running stage's children as `Parent › Child`, and what the run is
doing or waiting on you for. Mirror it into your harness's own task list (Claude Code's todo
list, Codex's plan tool, Cursor's todos) by replacing the whole list, in order and verbatim, so
the human always sees what is done, what is happening, and what comes next. Never add, drop,
reword, reorder, or tick items yourself — the engine owns the list. An action without `todo`
means nothing moved: keep the list as it is. In a harness without a task list, skip mirroring.
When the human asks what is happening, `python3 .maestro/engine/maestroctl.py todo --slug <slug>`
prints the same checklist for the terminal.

## Progress narration

Between dispatches keep the user oriented with one-liners: which step is running, what
a wave contains, what a gate decided. No artifact contents, no subagent transcripts.
