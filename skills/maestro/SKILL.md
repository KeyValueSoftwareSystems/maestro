---
name: maestro
description: Maestro lead — run a workflow (major, minor, bugfix, or a custom one) that chains the designer, brew, reviewer, litmus and sherlock agents. Use for "/maestro major <request>", "/maestro bugfix <bug>", "/maestro resume <slug>", or "/maestro <workflow> --from <step>".
---

# Maestro (lead)

You run a workflow file step by step. You are the engine: read the YAML, run each step, record
what happened, follow `next`. Keep it simple and keep the user informed.

## Commands

- `/maestro <workflow> <request>` — start a run. Workflows: `major`, `minor`, `bugfix`, or any
  name with a YAML file.
- `/maestro resume <slug>` — continue a run from its log.
- `/maestro <workflow> <slug> --from <step>` — start (or restart) a run at a given step. The
  artifacts of earlier steps are expected in the run folder already.
- `/maestro list` — list available workflows (name + description).

If the user does not name a workflow, suggest one in a single line (bug → `bugfix`; small,
contained change → `minor`; otherwise `major`) and confirm.

## Finding a workflow

Look for `<name>.yaml` in `.maestro/workflows/` (project's own, takes precedence), then in the
`workflows/` folder next to this skill's install (e.g. `.maestro/defaults/workflows/`).

## Workflow format

```yaml
name: major
description: one line
inputs: { request: question to ask if not given }
vars: { run: .maestro/runs/${slug} }
steps:
  - id: build               # unique
    type: agent             # agent | worker | gate | parallel
    agent: brew             # agent steps: the agent skill to use
    steps: [a, b]           # parallel steps: ids of the steps to run at the same time
    mode: subagent          # inline | subagent   (default inline)
    model: sonnet           # optional
    params: { plan: "${run}/plan.md" }   # passed to the agent's Params
    instructions: text      # agent and worker steps
    ask: question           # gate steps
    next: review            # or a map { <status>: <step> }; missing → done
    max_loops: 3            # optional cap on how often this step runs
```

Special `next` targets: `done` (finish the run), `ask-user` (stop and ask the user what to
do, showing the last step's summary) and `join` (only in a step run by a `parallel` step: this
branch finished fine).

## Starting a run

1. Load the workflow. If any `inputs` are missing, ask for them (one message).
2. Pick a `slug`: short kebab-case from the request (e.g. `rate-limit-login`). If
   `.maestro/runs/<slug>/` exists, add `-2`, `-3`…
3. Create `.maestro/runs/<slug>/run.md`:

   ```markdown
   # <slug>
   Workflow: <name> · Started: <date>
   Request: <request>

   ## Log
   ```
4. Tell the user in one line: the workflow, the slug, and the steps ahead.

## Variables

Replace `${name}` anywhere in a step's `params`, `instructions` and `ask` with:
`${slug}`, `${request}` (and any other input by name), every key of `vars` (resolved in
order), and `${<step-id>.artifact}` / `${<step-id>.status}` from the latest log entry of that
step. Leave unknown variables as they are and mention it.

## Running a step

**agent** — build this prompt:

```
Use the `<agent>` skill and follow it.
Params:
  <key>: <resolved value>
  ...
Instructions: <resolved instructions>
End with the Artifact / Status / Summary lines your skill defines.
```

- `mode: subagent` → start a subagent with that prompt (pass `model` if the runtime supports
  choosing one). On Claude Code use the subagent of the same name as the agent if one is
  installed, else a general-purpose subagent. If the runtime has no subagents, run it inline.
- `mode: inline` → load the agent skill yourself and do the work in this conversation, with
  the params and instructions above. Use inline for anything that talks to the user.

**worker** — same as agent, but there is no agent skill: the `instructions` are the whole task.
Run inline unless `mode: subagent`. Its status is `done` unless it fails (`failed`).

**gate** — ask the user the resolved `ask` question. Their answer is the status (`yes` / `no`,
or one of the keys in `next`). Never answer a gate yourself.

**parallel** — run every step listed in `steps` at the same time: start all the subagent ones
together (several subagent calls in one turn), then run any inline ones yourself while they
work. Wait for all of them. Log each branch as its own entry, then resolve each branch's own
`next` with its status:
- every branch resolves to `join` → log the parallel step as `done` and follow its `next`;
- otherwise → go to the first branch's non-`join` target (e.g. `ask-user`), naming the
  branch that caused it.
A branch step is only run through its parallel step; never reach it through the normal flow.

## After each step

1. Read the last `Artifact:`, `Status:` and `Summary:` lines of the result.
2. Append one line to the log in `run.md`:
   `- <time> · <step-id> · <status> · <artifact> · <summary>`
3. Tell the user the summary in one line.
4. Pick the next step:
   - `next` is a string → go there.
   - `next` is a map → use the entry for the status.
   - No status line, or a status with no entry → ask the user what to do (retry, pick a step,
     or stop).
5. **Loop cap:** before running a step with `max_loops`, count its entries in the log. At the
   cap, stop and ask the user whether to run it again, skip ahead, or stop.

## Finishing

On `done`, append `Finished: <date>` to `run.md` and give the user a short recap: what was
built, where the artifacts are, and the PR link if there is one.

## Resume and --from

- **Resume:** read `run.md`, take the last log line, and continue with the step that line's
  `next` points to. If the log has no entries, start at the first step.
- **--from <step>:** run that step next, whatever the log says. Warn if an artifact it needs
  (a path in its params) is missing, and ask whether to continue.

## Rules

- The workflow file is the source of truth for order and instructions; agent skills hold the
  "how". Do not add workflow-specific instructions of your own.
- Do not redo or second-guess an agent's work; route on its status. If the result looks
  clearly wrong, tell the user and ask.
- Keep your own context light: read summaries, not whole artifacts, unless the user asks.
- The user can interrupt at any time to skip, repeat or stop a step. Do what they say and log it.
