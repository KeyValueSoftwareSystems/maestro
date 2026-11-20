<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/maestro.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/maestro-light.svg">
    <img src="assets/maestro.svg" alt="Maestro" width="100%">
  </picture>
</p>

<p align="center">
  <strong>Five focused agents, three workflows, no engine.</strong><br>
  Use any agent on its own, or let the lead chain them into a workflow.
</p>

## The idea

- **Agents know *how*.** Each agent is a plain skill that works with whatever you give it: a
  sentence, a ticket, a file, a folder. It never knows which workflow it is in.
- **Workflows know *what, where and when*.** A small YAML file lists the steps, which agent
  runs each one, with what params and extra instructions, and where to go next.
- **The lead agent is the engine.** `/maestro` reads the YAML and runs the steps, routing on
  the status each agent reports. State is one readable log file per run.

## The agents

| Agent | Does | Ends with `Status:` |
|---|---|---|
| **designer** | brainstorms with you, works out the design, writes a plan from a template | `ready` / `needs-input` |
| **brew** | implements a plan or fixes review/test findings, test-first | `done` / `blocked` |
| **reviewer** | reviews code with `file:line` evidence | `approve` / `changes` |
| **litmus** | derives cases from the spec, writes tests (`phase: write`), runs them (`phase: run`), or both | `written` / `pass` / `fail` |
| **sherlock** | reproduces a bug, finds the root cause, proposes the fix | `found` / `unclear` |

Each one can be used on its own: `/designer add rate limiting to login`, `/reviewer`,
`/sherlock "checkout returns 500 for empty carts"`.

Agents have **params** with sensible defaults (for example the designer's `brainstormSkill`,
`designSkill`, `template`, `output`). Building-block skills live in `skills/`: `brainstorm`,
`grill-me` and `design`. Swap any of them, or use your own skill, by passing its name.

## The workflows

| Workflow | Steps |
|---|---|
| `major` | designer (grill-me, full plan) → approval → [brew implements ‖ litmus writes tests] → merge tests → reviewer ⇄ brew → litmus runs tests ⇄ brew → PR |
| `minor` | designer (brainstorm, short plan) → [brew implements ‖ litmus writes tests] → merge tests → reviewer ⇄ brew → litmus runs tests ⇄ brew → PR |
| `bugfix` | sherlock → brew → litmus ⇄ brew → reviewer ⇄ brew → PR |

```
/maestro major "let admins export audit logs as CSV"
/maestro bugfix "password reset email never arrives"
/maestro resume export-audit-logs
/maestro major export-audit-logs --from review
```

Each run keeps its artifacts and its log in `.maestro/runs/<slug>/` (`plan.md`, `review.md`,
`test-report.md`, `rca.md`, `run.md`).

## Writing a workflow

```yaml
name: major
description: New feature — full design, build, review, test, PR
inputs:
  request: What should be built?
vars:
  run: .maestro/runs/${slug}
steps:
  - id: design
    type: agent              # agent | worker | gate
    agent: designer
    mode: inline             # inline | subagent
    model: opus
    params:
      brainstormSkill: grill-me
      template: plan.md
      output: ${run}/plan.md
    instructions: "Use ${run}/prd.md if it exists, else ${request}."
    next: approve
  - id: approve
    type: gate
    ask: Approve the plan at ${run}/plan.md?
    next: { yes: build, no: design }
  - id: pr
    type: worker             # a one-off step: no agent, just instructions
    instructions: Push the branch and open a PR.
```

- **`type`**: `agent` runs an agent skill; `worker` runs only the `instructions`; `gate` asks
  you a question; `parallel` runs the steps listed in its `steps` at the same time.
- **`mode`**: `subagent` runs the step in its own context. `inline` runs it in the lead's
  conversation, so use it for steps that talk to you. A runtime without subagents runs every
  step inline.
- **`next`**: either a step id, or a map from status to step id. The special targets are
  `done` and `ask-user`. Add `max_loops` to cap a review or test loop.
- **Parallel branches** end with `next: join` when they succeeded. When every branch joins, the
  run follows the parallel step's `next`; otherwise it goes to the first branch's other target:
  ```yaml
  - id: build
    type: parallel
    steps: [implement, write-tests]
    next: review
  - id: implement
    ...
    next: { done: join, blocked: ask-user }
  ```
- **Variables**: `${slug}`, every input (for example `${request}`), every `vars` entry, and
  `${<step>.artifact}` / `${<step>.status}`. Quote values that use `${…}` inside `{ }`.
- **Workflow-specific instructions go in the workflow, never in an agent skill.**

To change a default workflow, copy it from `.maestro/defaults/workflows/` to
`.maestro/workflows/` and edit it there. For your own templates, put `<name>.md` in
`.maestro/templates/`; a bare template name looks there first.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/KeyValueSoftwareSystems/maestro/main/install.sh \
  | bash -s -- claude-code            # also: codex, cursor; --ref <tag>
```

- **Claude Code**: skills go to `.claude/skills/`, and the subagent wrappers to `.claude/agents/`.
- **Codex and Hermes**: `.agents/skills/`.
- **Cursor**: `.cursor/skills/`.
- **Default workflows**: `.maestro/defaults/workflows/`.

When you re-run the installer, any file you edited is kept, and the new version is written
beside it as `*.upstream`.

## Repo layout

```
agents/      designer, brew, reviewer, litmus, sherlock  (SKILL.md + templates/)
skills/      brainstorm, grill-me, design, maestro (the lead)
workflows/   major.yaml, minor.yaml, bugfix.yaml
adapters/    claude-code/agents/*.md — thin subagent wrappers
install.sh
```

## License

MIT
