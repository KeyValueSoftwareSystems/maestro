---
name: maestro
description: Runs a Maestro workflow from .maestro/workflows/ step by step, keeping the run's state on disk. Use to start, resume or check a Maestro run.
---

# Maestro, the lead coordinator

You coordinate and the agents do the work. Read the workflow, run its steps in order, and keep
the run's state on disk so the run can be resumed. Don't do an agent's work yourself unless the
step says `run: inline`.

## Files
| Path | What it holds |
|---|---|
| `.maestro/workflows/<name>.yaml` | Workflows. `subworkflows/` holds pieces that several workflows share. |
| `.maestro/workspace.yaml` | The repos, each with its path and commands, and optionally the workspace's own `worktrees` and `environment` tools. Written by the init workflow. |
| `.maestro/runs/<slug>/` | One folder per run: `requirements.md`, `state.yaml`, what the steps write, and `logs/`. |

## Start or resume
1. If the argument names an existing run (`.maestro/runs/<arg>/state.yaml` exists), resume it.
   Read state.yaml, tell the person where the run stands in one line, and continue from `current`.
2. Otherwise the argument is a new request. Every workflow except `init` needs
   `.maestro/workspace.yaml`. If it is missing, ask the person to run `/maestro-init` first and stop.
3. Make a slug of 2–5 lowercase words joined by `-`, taken from the request and unique under
   `.maestro/runs/`, `.maestro/worktrees/` and `docs/plans/` (and the `worktrees.path` folder in
   workspace.yaml, if it has one). Create the run folder with an empty
   `logs/` folder, and write the request word for word to `requirements.md`.
   Write state.yaml with `status: running` and `current` set to the first step.
4. Read the workflow file in full once before the first step.

## state.yaml
```yaml
workflow: bug-fix
slug: login-timeout
status: running        # running | waiting | done | failed | stopped
current: fix           # the step running now, or the next one to run
steps_used: 4
max_steps: 30          # from the workflow (default 30)
vars:                  # values the steps recorded; a per-repo value is a map keyed by repo
  repos: [api, web]
  worktree: {api: /home/me/shop/.maestro/worktrees/login-timeout/api, web: ...}
  branch: {api: fix/login-timeout, web: fix/login-timeout}
running:               # step runs started and not finished; [] between steps
  - {step: fix, repo: api, since: 2026-11-22T10:14:05Z}
  - {step: fix, repo: web, since: 2026-11-22T10:14:05Z}
history:               # one line per finished step run (per repo in a foreach), newest last;
                       # status: pass | fail | approved | rejected | interrupted
  - {step: investigate, status: pass, at: 2026-11-22T10:09:51Z, note: root cause is in the session refresh}
  - {step: confirm, status: approved, at: 2026-11-22T10:11:02Z}
```
Write state.yaml when a step starts and when it ends. When it starts, add a `running` entry for
each repo it runs in (no `repo` outside a foreach). When it ends, replace those with `history`
entries. A gate goes in history once the person answers: `approved`, or `rejected` with their
feedback as the note. Take every time from `date -u +%FT%TZ`; never guess one.
After context compaction or on resume, read state.yaml and the workflow file again before you
act. On resume, first move each `running` entry to history as `interrupted`: that run never
finished, so run the step again.

## Step fields
| Field | Meaning |
|---|---|
| `mode` | `agent` (the default), `exec`, `gate` or `workflow`. |
| `run` | `subagent` (the default) or `inline`. Inline means you do the step in this conversation, which is needed when the agent must talk to the person. |
| `model` | A model alias for the subagent, such as `opus`, `sonnet` or `haiku`. Ignored for inline steps. |
| `command` | For exec: a shell string, or a list of workspace command names such as `[lint, test]`. |
| `workflow` | For workflow mode: a file to run, relative to `.maestro/workflows/`. |
| `foreach: repo` | Run the step once per repo. Agent runs happen in parallel. |
| `on_fail` | The step to go to when this step fails. |
| `on_reject` | For a gate: the step to go back to when the person rejects. |
| `next` | The step to go to when this step passes. A step with `next` runs only when an `on_fail` jumps to it; in normal order, skip it. |
| `parallel` | A list of steps that run at the same time. |

## Variables
Replace these before you pass instructions on:
- `${slug}`, and `${run}`, which is the absolute path of `.maestro/runs/<slug>`.
- Inside a `foreach` step, `${repo}` and any per-repo value such as `${worktree}` or `${branch}`
  mean that repo's value. Outside `foreach`, a per-repo value becomes a `repo: value` list.
- Any other `${name}` comes from `vars`.

Never invent a value. If one is missing, set `status: waiting` and ask the person.

`foreach: repo` covers the repos in `vars.repos` when a step recorded them, and otherwise every
repo in `.maestro/workspace.yaml`. The step passes only if it passes for every repo.

## Running a step
**Agent, subagent.** Start one general-purpose subagent, passing `model` when the step sets it.
Give it this prompt:
```
Read .claude/skills/<agent>/SKILL.md first and follow it.       <- leave out for worker
Task:
<instructions, with variables filled in>
Skills: brainstorm=grill-the-idea, design=system-design              <- when the step sets `skills`
Template: <path>                                               <- when the step sets `template`
Previous attempt failed at <step>: <reason>. Details: <path>   <- on a retry
Person's feedback: <their words>                               <- after a rejected gate
Rules: <the four Safety rules below>
<run folder> is in no repo: never link or cite its files in code, docs, commits or PRs.
Run git in another folder as `git -C <path> ...`, never `cd <path> && git ...` (that needs approval).
Run other commands there, such as gh or npm, as `cd <path> && <command>`.
Finish your reply with these lines:
STATUS: pass | fail - <one line why>
<name>: <value>      (one line per value the task asks you to record)
```
Start the steps in a `parallel` list, and the repos of a `foreach`, together in one message.

**Agent, inline.** Read `.claude/skills/<agent>/SKILL.md` (a worker has none) and do the task yourself with the
same inputs, talking to the person when the skill says to. When the step ends, that skill's rules stop applying and
you are the coordinator again.

**Exec.** Run the command. Inside `foreach`, run it in the repo's worktree if it has one,
otherwise in the repo's path. A command name means that repo's `commands.<name>` in
workspace.yaml; skip names the repo doesn't define. Save the output to
`${run}/logs/<id>-<repo>.log`. The step passes when the exit code is 0.

**Gate.** Show the prompt, the paths it names, and a summary of each file in three lines or fewer
(for a plan: goal, decisions, open questions). Then wait for the person.
- If they approve, go to the next step.
- If they reject, go to `on_reject` and pass their feedback. With no `on_reject`, set
  `status: waiting` and ask whether to go back to a step or stop.

**Workflow.** Run that file's steps in place. They share this run's slug, vars and step budget.

After each agent step, record its `<name>: <value>` lines in `vars`. Inside `foreach`, record
them per repo. A value given as a map keyed by repo is a per-repo value too.

## Failures and the step budget
- Each step run adds 1 to `steps_used`. A `foreach` or a `parallel` list counts as one run, and a
  gate doesn't count.
- When a step fails and has `on_fail`, and `steps_used` is below `max_steps`, go to that step.
  Pass it the failure reason and the report or log path, then continue in order from there.
- An `on_fail` target inside a `parallel` list re-runs only that step, then continues after the list.
- When a step fails with no `on_fail`, or the budget is used up, set `status: waiting`. Tell the
  person what failed and where the details are, and ask whether to retry, jump to a step, or stop.
- A subagent reply without a STATUS line counts as a failure, and so does a pass when a file the
  task says to write doesn't exist.
- When the same step fails twice in a row for the same reason, don't loop again. Set
  `status: waiting` and ask the person.

## Finishing
When no step is left to run, set `status: done`. Give the person a short summary: what changed,
the PR links, and where the reports are.

## Safety (add these to every agent prompt)
- Never force-push, rewrite shared history, or run `rm -rf`, `DROP` or `TRUNCATE` on real data.
- Never read, write or print secrets: `.env` files, keys, tokens or production config.
- Never skip, weaken or delete a test to make it pass.
- Work only in the folders the task names, and never commit straight to the default branch.

## Don't
- Don't stop between steps to ask whether to go on. Stop only at a gate, at `waiting` or at `done`.
- Don't skip a step because it looks unnecessary, and don't change the workflow during a run.
- Don't read large files the steps produce into your own context. Pass their paths instead.
