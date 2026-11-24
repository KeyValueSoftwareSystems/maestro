<p align="center"><img src="assets/maestro.svg" alt="Maestro: orchestrate AI, own the outcome. An open AI-SDLC practice with you at the centre of specialist agents." width="100%"></p>

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
/maestro-init                         # find repos and commands; offer the knowledge base
/maestro-fix  Login times out after 5 minutes
/maestro-minor Add a CSV export to the orders page
/maestro-feature Multi-currency pricing
```
To resume a run, pass its slug instead of a request, for example `/maestro-fix login-timeout`.

## Commands
| Command | Workflow | What it does |
|---|---|---|
| `/maestro-feature` | major-feature | Turns the request into requirements, asks the design questions, plans with you, reviews the plan, builds and writes tests in parallel, loops on review and on the tests until both pass, offers a short quiz on the change (skippable), then ships |
| `/maestro-minor` | minor-feature | Writes a short plan, then builds, tests, reviews and ships |
| `/maestro-fix` | bug-fix | Asks your guess at the cause, finds the root cause, adds a regression test and fixes the bug, then reviews and ships |
| `/maestro-kb` | knowledge | Builds the knowledge base in `docs/` from the code |
| `/maestro-init` | init | Detects repos and commands, and offers to build the knowledge base |
| `/maestro-sync` | sync | Fast-forwards every repo and refreshes the docs that went stale |
| `/maestro-ui` | — | Opens a local web page that shows each run live, lets you edit workflows, and shows the agents. Needs Node 20 or later |

Every feature and fix workflow ends with the same **archive** steps. Socrates updates the docs
and saves the plan (or RCA) as `docs/plans/<slug>.md`, you approve the ship, a pull request is
opened for each repo (and one for the docs in a multi-repo workspace), and the worktrees are
removed. A `.ignore` hides `docs/plans/` from search, so agents read an old plan only when named.

## Agents
| Agent | Role |
|---|---|
| **Keystone** | Planner. Brainstorms (`grill-the-idea`), designs (`system-design`) and writes `plan.md` |
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
    instructions: Investigate ${run}/requirements.md. Write the root cause to ${run}/rca.md.
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
`parallel:`, or another workflow (`mode: workflow`). A fix step is reached only through
`on_fail`, and its `next:` names the step to go back to, usually the one that failed. All the step
fields are described in
[skills/maestro/SKILL.md](skills/maestro/SKILL.md).

Edit the installed copies in `.maestro/workflows/` freely; upgrades keep them. To change an
agent's output format, put your own template in `.maestro/templates/` and pass it with
`template:` on the step.

## Multi-repo workspaces
Run Maestro from an umbrella folder with each service repo cloned under `codebase/`.
`/maestro-init` lists them in `.maestro/workspace.yaml` with their commands.
Steps marked `foreach: repo` then run once per repo the plan touches, each in its own worktree
under `.maestro/worktrees/<slug>/<repo>`. The umbrella folder must itself be a git repo: it holds
`docs/`, and doc updates ship from it as their own pull request.

If the workspace has its own tools, `/maestro-init` records them in `workspace.yaml` and runs use
them. Under `worktrees`, they create, find and remove the run's worktrees, such as a sandbox
script. Under `environment`, they start and stop the stack from those worktrees, such as an infra
script. A run renames each worktree's branch to its own `feat/<slug>` or `fix/<slug>`. Litmus then starts the stack itself for integration and e2e tests, and stops it when it
is done:
```yaml
worktrees:
  create: ./scripts/sandbox create {slug} --from api=main --from web=main
  path: sandbox/{slug}/codebase/{repo}
  remove: ./scripts/sandbox rm {slug} -y
environment:
  start: ./scripts/infra up {slug}
  urls: ./scripts/infra ls
  stop: ./scripts/infra down {slug}
```

## Contributing
Read [AGENTS.md](AGENTS.md) first. Keep every skill within 200 lines, and run
`bash scripts/check.sh` before committing.

## License
MIT. See [LICENSE](LICENSE) and [ATTRIBUTIONS.md](ATTRIBUTIONS.md).
