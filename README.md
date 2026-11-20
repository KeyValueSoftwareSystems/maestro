<p align="center"><img src="assets/maestro.svg" alt="Maestro" width="120"></p>

# Maestro

Maestro is a small, readable set of workflows for Claude Code. Each one is a step list that hands
work to specialist agents, runs your checks, and stops for your approval where it matters. It has
no engine and no CLI: just skills, YAML workflows and a run folder.

## Quick start
```bash
git clone https://github.com/KeyValueSoftwareSystems/maestro.git
cd your-project
bash ../maestro/install.sh
```
Then, in Claude Code from your project folder:
```
/maestro-init                         # find repos, stacks and commands; build the knowledge base
/maestro-fix  Login times out after 5 minutes
/maestro-minor Add a CSV export to the orders page
/maestro-feature Multi-currency pricing
```
To resume a run, pass its slug instead of a request, for example `/maestro-fix login-timeout`.

## Commands
| Command | Workflow | What it does |
|---|---|---|
| `/maestro-feature` | major-feature | Brainstorms and designs a plan, has it reviewed and approved, builds in parallel, then tests, reviews and ships |
| `/maestro-minor` | minor-feature | Writes a short plan, then builds, tests, reviews and ships |
| `/maestro-fix` | bug-fix | Finds the root cause, adds a regression test and fixes the bug, then reviews and ships |
| `/maestro-kb` | knowledge | Builds the knowledge base in `docs/` from the code |
| `/maestro-init` | init | Detects repos, stacks and commands, and wires the stack skills |
| `/maestro-sync` | sync | Fast-forwards every repo and refreshes the docs that went stale |

Every feature and fix workflow ends with the same **archive** steps. Socrates updates the docs,
you approve the ship, a pull request is opened for each repo, and the worktrees are removed.

## Agents
| Agent | Role |
|---|---|
| **Keystone** | Planner. Brainstorms (`grill-me`), designs (`system-design`) and writes `plan.md` |
| **Brew** | Implementer. Writes code and tests, then fixes what the checks and reviews find |
| **Birbal** | Reviewer. Reviews plans, code and docs in a findings table that tracks each fix |
| **Litmus** | Tester. Writes tests, or runs them and classifies each failure |
| **Sherlock** | Debugger. Reproduces a bug, finds the root cause and writes `rca.md` |
| **Socrates** | Knowledge keeper. Builds the docs, or updates them after each change |
| **Worker** | Has no skill and does exactly what the step says (worktrees, commits, PRs) |

Agent skills never mention Maestro, so you can also use them on their own, for example
"use the sherlock skill on this crash".

## Workflows
A workflow is a list of steps:
```yaml
name: bug-fix
max_steps: 30                     # total step runs, including retries
steps:
  - id: investigate
    agent: sherlock               # keystone | brew | birbal | litmus | sherlock | socrates | worker
    model: opus
    instructions: Investigate ${run}/request.md. Write the root cause to ${run}/rca.md.
  - id: confirm
    mode: gate                    # ask the person
    prompt: Root cause is in ${run}/rca.md. Approve?
    on_reject: investigate
  - id: checks
    mode: exec                    # run a command
    foreach: repo
    command: [build, lint, test]  # names from .maestro/workspace.yaml, or a shell string
    on_fail: fix                  # loop back; the lead passes the failure along
```
Steps can also be `run: inline` (the agent talks to you in the main conversation), grouped under
`parallel:`, or another workflow (`mode: workflow`). All the step fields are described in
[skills/maestro/SKILL.md](skills/maestro/SKILL.md).

Edit the installed copies in `.maestro/workflows/` freely; upgrades keep them. To change an
agent's output format, put your own template in `.maestro/templates/` and pass it with
`template:` on the step.

## Multi-repo workspaces
Run Maestro from an umbrella folder with each service repo cloned under `codebase/`.
`/maestro-init` lists them in `.maestro/workspace.yaml` with their stack skills and commands.
Steps marked `foreach: repo` then run once per repo the plan touches, each in its own worktree
under `.maestro/worktrees/<slug>/<repo>`.

## Stack skills
React (with Next.js and React Native), Node.js + TypeScript (with NestJS), Python (with Django
and FastAPI) and Java (with Spring Boot). `/maestro-init` copies only the stacks your repos use
into `.claude/skills/`.

## Contributing
Read [AGENTS.md](AGENTS.md) first. Keep every skill within 200 lines, and run
`bash scripts/check.sh` before committing.

## License
MIT. See [LICENSE](LICENSE) and [ATTRIBUTIONS.md](ATTRIBUTIONS.md).
