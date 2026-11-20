# Maestro

Maestro runs software delivery workflows inside a coding agent (Claude Code for now). A **lead**
skill reads a short YAML workflow and handles each step: it hands the step to an **agent** (a
skill), runs a command, or asks a person. There is no engine and no CLI. The workflow file, the
run folder and `state.yaml` are the whole system.

## Layout
| Path | What it holds |
|---|---|
| `skills/maestro/` | The lead coordinator. It is the only skill that knows about Maestro, and it defines the step format. |
| `skills/agents/<agent>/` | One skill per agent, with its default `templates/`. Installed flat, as `.claude/skills/<agent>/`. |
| `skills/grill-me/`, `skills/system-design/` | Sub-skills that agents load when a workflow names them. |
| `stacks/<stack>/` | Stack skills (react, node, python, java). `/maestro-init` wires them to repos. |
| `workflows/` | major-feature, minor-feature, bug-fix, knowledge, init, sync. |
| `workflows/subworkflows/` | Pieces shared by several workflows (archive). |
| `commands/` | One slash command per workflow. |
| `install.sh` | Copies everything above into a project. |
| `scripts/check.sh` | Size and wiring checks. Run it before every commit. |

## Agents
| Agent | Role | Default templates |
|---|---|---|
| Keystone | Planner and designer: brainstorms, designs, writes the plan | `plan.md` |
| Brew | Implementer: code and tests, then fixes from checks and reviews | none |
| Birbal | Reviewer of plans, code and docs; keeps a findings table | `review.md` |
| Litmus | Tester: writes tests, or runs them and reports | `test-report.md` |
| Sherlock | Debugger: reproduces a bug and finds the root cause | `rca.md` |
| Socrates | Knowledge keeper: builds the docs, or updates them after a change | `architecture.md`, `domain.md` |
| Worker | Has no skill and runs the instructions it is given | none |

## How a run works
1. The person types `/maestro-fix <bug>`, and the lead loads `.maestro/workflows/bug-fix.yaml`.
2. The lead creates `.maestro/runs/<slug>/` with `request.md` and `state.yaml`.
3. For each step, the lead fills in `${slug}`, `${run}`, `${repo}` and the other variables. It then
   starts the agent with the step's instructions, runs the command, or asks the person (gate).
4. When a step fails, the lead jumps to its `on_fail` step, up to the workflow's `max_steps`.

## Rules for this repo
1. **Size limits.** This file stays under 100 lines (150 at most). Every `SKILL.md`, reference
   and template is 200 lines at most. Aim to keep each workflow under 80 lines.
2. **The workflow owns the what; the skill owns the how.** Paths, file names, order and which
   sub-skills to use belong in the workflow. A skill never mentions Maestro, run folders,
   workflows or other agents.
3. **Skills work standalone.** Every input an agent skill reads has a default. Its templates live
   in its own `templates/` folder, and a project can override one from `.maestro/templates/`.
4. **Sub-skills are swappable.** An agent skill names its sub-skills by role (brainstorm, design)
   and takes the actual skill from its instructions.
5. **No engine.** Don't add scripts for the lead to call. If the lead keeps getting something
   wrong, fix the wording first, and discuss before adding code.
6. **Subworkflows only after discussion**, and only for steps that several workflows share.
7. Write plainly: short sentences, rules rather than explanations.

## Writing stack skills
- Write one skill per stack: a `SKILL.md` with Build, Test, Review and Verify sections. Use
  `references/` only for sub-frameworks such as Django or Next.js.
- Include only what a strong model gets wrong or what the team decided. No textbook material.
- Write rules, not tutorials: "do X / never Y, because Z". Add code only when a rule is unclear
  without it.
- Make every rule checkable from a diff, and name the versions the skill covers.
- Repo-specific conventions belong in that repo's own AGENTS.md, not in a stack skill.

## Safety (the lead adds these to every agent prompt)
- Never force-push, rewrite shared history, or run `rm -rf`, `DROP` or `TRUNCATE` on real data.
- Never read, write or print secrets: `.env` files, keys, tokens or production config.
- Never skip, weaken or delete a test to make it pass.
- Work only in the folders the task names, and never commit straight to the default branch.

## Checks
Run `bash scripts/check.sh` before committing. It checks the size limits, that agent skills don't
mention Maestro, and that every agent and workflow a workflow names exists.
