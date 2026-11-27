---
name: maestro-workflow
description: Creates a custom Maestro workflow from the person's requirements, or updates one in .maestro/workflows/, built from the installed agents. Interviews the person, proposes the steps, then writes the workflow YAML and its /maestro-<name> command. Use when asked to create, design, change or extend a Maestro workflow.
---

# Maestro workflow builder

You write workflows for the Maestro lead to run. You never run one. A workflow is a YAML file in
`.maestro/workflows/`. Its step format is in `.claude/skills/maestro/references/step-format.md`:
read it in full before you write a step.

When the person picks between choices (your recommended answers, approving the outline), ask with
AskUserQuestion: your recommendation first, marked (Recommended), at most 4 options. Print the
outline in chat before the popup. Ask open questions in chat.

## Start
1. Read `.maestro/workspace.yaml` for the repos and the command names each one defines (setup,
   build, lint, test). If it is missing, ask the person to run `/maestro-init` first, and stop.
2. List `.maestro/workflows/`, `.maestro/workflows/templates/`, `.maestro/templates/` and
   `.claude/commands/maestro-*.md`.
3. If the argument names an existing workflow (with or without `.yaml`), go to Update.
   Otherwise go to Create, with the argument as the person's first description of it.

## Building blocks
**Agents.** Use only these. A step with no `agent` is invalid unless it sets `mode`.
| Agent | Use it to | What its step must say |
|---|---|---|
| `keystone` | plan or design a change with the person | `run: inline`, `skills: {brainstorm: grill-the-idea, design: system-design}`, the plan path, and "Record the repos the plan touches as `repos`". |
| `brew` | write code with unit tests, or fix what checks, tests or reviews found | Where (`${worktree}`), the branch, and what to build or fix (the plan, report or review path). Add "Do not commit" when a later step commits. |
| `birbal` | review a plan, a code change or docs | What to review, against which file, and the review path. |
| `litmus` | write tests (Write mode) or run a test plan and report (Run mode) | The mode, the test plan, where, and the report path. |
| `sherlock` | reproduce a bug and find its root cause | The bug, the rca path, and "Record the repos the fix touches as `repos`". |
| `socrates` | build the docs (Build mode) or update them after a change (Update mode) | The mode, and the change: branch, worktree and run files. |
| `worker` | anything else: worktrees, commits, PRs, asking the person fixed questions | Everything. It has no skill, so spell out each action and the file to write. |

**Step kinds.**
- `mode: exec` with workspace command names, such as `command: [build, lint, test]`, to check
  work. Give it `on_fail` pointing at the step that fixes it.
- `mode: gate` wherever the person must approve before work goes on: after a plan or rca, and
  before anything leaves the machine. Give it `on_reject` pointing at the step that redoes it.
- `run: inline` only when the agent must talk to the person (keystone, interview workers).
- `foreach: repo` for steps that work inside each repo's worktree.
- `parallel:` for independent steps, such as build and write-tests.
- A fix step that only `on_fail` reaches: put it at the end with `next:` naming the step to
  return to, so the fix is committed and checked again. See `fix-review` in major-feature.yaml.
- `mode: workflow` to reuse another file, such as `subworkflows/archive.yaml`.

**Copy proven steps** rather than writing new ones. Read the installed workflows and reuse:
- the `worktree` step of minor-feature.yaml (bug-fix.yaml for a `fix/` branch), before any step
  that changes code;
- the `commit` step of major-feature.yaml, when build steps are told not to commit;
- the `checks` step, and the fix loops of major-feature.yaml;
- the `archive` subworkflow to update docs, ask to ship, open PRs and remove worktrees. It needs
  `${worktree}`, `${branch}`, `${run}/review.md`, and `${run}/plan.md` or `${run}/rca.md`.

**Models.** `haiku` for mechanical worker steps (worktrees, commits, cleanup), `sonnet` for
building, tests and PRs, `opus` for reviews, root causes and docs. Leave `model` out on inline steps.

## Create
1. **Play it back.** In two or three lines, say what you understood the workflow is for and
   what starts a run of it (a feature request, a bug, a ticket, a schedule).
2. **Ask.** Ask what you still need, in one batch, with your recommended answer on each.
   Skip what the person already said or an existing workflow already answers. Ask about:
   - the outcome: a merged PR, a report, docs, a decision;
   - the stages, in order, and which agent does each;
   - where the person approves (gates), and what happens on a rejection;
   - which checks run, and where a failure loops back to;
   - whether it changes code in repos (worktrees, `foreach: repo`) and how it ships;
   - custom instructions: team rules, files to read or write, templates, models, and things a
     step must never do;
   - its name: lowercase words joined by `-`. Refuse a name whose `/maestro-<name>` command
     already exists, unless the person wants to update that workflow.
   Ask follow-ups only when an answer leaves a step unclear. Never invent a requirement.
3. **Propose.** Show the outline as a table: step id, kind (agent and model, exec, gate,
   workflow), what it does, files it reads and writes, `on_fail`/`on_reject`/`next`. Below it,
   list the gates and loops in one line each. Ask the person to approve or change it, and repeat
   until they approve.
4. **Write** the files (see Writing), then **Check**, then **Report**.

## Update
1. Read the workflow file in full. Show its outline as a table, as in Create step 3.
2. Read `.maestro/runs/*/state.yaml`. If a run of this workflow has `status: running`, say which,
   and stop: a workflow must not change during a run. If one has `status: waiting`, warn that
   it will resume with the new version, and keep the step its `current` names.
3. Ask what to change, unless the argument already says. Show the changed outline and get the
   person's approval.
4. Edit only what was agreed. Keep the other steps, their wording and the comments as they are.
   When you rename or remove a step, update every `on_fail`, `on_reject` and `next` that named it.
5. **Check**, then **Report** with a short diff summary.
A file under `subworkflows/` is shared: list the workflows that use it and say they all change.

## Writing
Write `.maestro/workflows/<name>.yaml`:
```yaml
# <What the workflow does and when to use it, in one or two lines.>
name: <name>                 # same as the file name
description: <one line; it becomes the command's description>
max_steps: <about twice the step count, so fix loops have room; 30 is typical>
steps:
  - id: <short-kebab-id>
    agent: <agent>
    instructions: |
      <what to do, the paths to read and write, the values to record>
```
Rules for the steps:
- The workflow owns the what: paths, file names, order, sub-skills, values to record. Leave the
  how to the agent's skill, and don't repeat what its skill already does by default.
- Run files go under `${run}/`. Code changes happen only in `${worktree}`, never in a repo's
  main checkout, and never on the default branch.
- Every `${name}` you use is `slug`, `run`, `repo`, or a value an earlier step records with
  "Record ... as `name`". Every `on_fail`, `on_reject` and `next` names a step in this file.
- Step ids are unique across the workflow, its `parallel` lists and the subworkflows it runs
  (archive uses learn, approve-ship, pr, docs-pr and cleanup).
- Put the person's custom instructions in the steps they apply to, in their words.
- Keep each instruction to a few short sentences. Don't add the safety rules: the lead adds them.
- A new template goes in `.maestro/workflows/templates/<file>.md`, passed with `template:`.

Then write the command `.claude/commands/maestro-<name>.md`, unless it exists:
```markdown
---
disable-model-invocation: true
description: "<the workflow's description>"
argument-hint: <request, or a run slug to resume>
---

Use the `maestro` skill to run the workflow `.maestro/workflows/<name>.yaml` for: $ARGUMENTS
```
On an update, change only the command's description line, and only if the workflow's
description changed. Never write a command for a subworkflow. Never edit a command that doesn't
name this workflow's file.

## Check
Before you report, read the file again and confirm:
1. It parses: run `python3 -c 'import sys, yaml; yaml.safe_load(open(sys.argv[1]))' <file>` when
   PyYAML is installed.
2. Every agent is in the table above, every `workflow:` file exists, every `template:` file
   exists, and every command name in `command: [...]` is defined by at least one repo.
3. Every `${name}`, `on_fail`, `on_reject` and `next` resolves, as in Writing.
4. Every step that changes code or uses `${worktree}` or `${branch}` comes after a worktree step.
5. A gate comes before any push, PR, deploy or message to people outside the run.
Fix what fails before you report.

## Report
Tell the person, in a few lines:
- the workflow file and the command to run it: `/maestro-<name> <request>`;
- the outline in one line per step;
- that `/maestro-ui` shows it as a graph and can edit it;
- that `install.sh` keeps their workflows, but `--force-workflows` overwrites the ones with
  built-in names.
