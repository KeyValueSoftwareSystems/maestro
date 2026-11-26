# Workflow step format

A workflow file has `name`, `description`, `max_steps` (default 30) and a list of `steps`.
Step ids are unique across the workflow and the subworkflows it runs.

## Step fields
| Field | Meaning |
|---|---|
| `id` | The step's name. |
| `mode` | `agent` (the default), `exec`, `gate` or `workflow`. `run next` shows it as `kind`. |
| `agent` | The agent skill to run, or `worker` for none. |
| `run` | `subagent` (the default) or `inline`. Inline means the lead does the step in its own conversation, which is needed when the agent must talk to the person. |
| `model` | A model alias for the subagent, such as `opus`, `sonnet` or `haiku`. Ignored for inline steps. |
| `instructions` | The task. Variables are filled in (see below). |
| `skills`, `template` | Passed to the agent: sub-skills by role, such as `{brainstorm: grill-the-idea}`, and a template path. |
| `prompt` | For a gate: what to show the person. |
| `command` | For exec: a shell string, or a list of workspace command names such as `[lint, test]`. A repo that doesn't define a name skips it. |
| `workflow` | For workflow mode: a file to run in place, relative to `.maestro/workflows/`. Its steps share the run's variables and step budget. |
| `foreach: repo` | Run the step once per repo. Agent runs happen in parallel. |
| `parallel` | A list of steps that run at the same time. |
| `on_fail` | The step to go to when this step fails. |
| `on_reject` | For a gate: the step to go back to when the person rejects, with their feedback. |
| `next` | The step to go to when this step passes. A step with `next` runs only when an `on_fail` jumps to it; in normal order it is skipped. |

<!-- REVIEW: maestro C6: mode row now says run next shows it as kind. -->

## Variables
- `${slug}` is the run's name, and `${run}` the absolute path of `.maestro/runs/<slug>`.
- Any other `${name}` is a value a step recorded: an agent reply line `<name>: <value>`.
  A missing value stops the run and asks the person; it is never invented.
- A value recorded inside a `foreach` is kept per repo. Inside a `foreach`, `${repo}` and
  `${worktree}` mean that repo's value. Outside one, a per-repo value becomes `repo: value, ...`.
- A `foreach` covers the repos in `repos` when a step recorded them, and otherwise every repo in
  `.maestro/workspace.yaml`. It passes only if it passes for every repo.

## Failures and the step budget
- Each step run uses 1 step. A `foreach` or a `parallel` list counts as one, and a gate is free.
- When a step fails, the run goes to its `on_fail` step and passes on the reason and details.
  An `on_fail` target inside a `parallel` list re-runs only that step, then continues after the list.
- A step with no `on_fail`, a gate rejected with no `on_reject`, the same failure twice in a
  row, or a used-up budget stops the run and asks the person whether to continue from a step
  or stop.
