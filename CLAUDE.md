# CLAUDE.md

Maestro: five agent skills (designer, brew, reviewer, litmus, sherlock), building-block skills, and
YAML workflows run by a lead skill (`skills/maestro`). There is no engine. The lead reads the YAML.

## Rules for changes

- **Agent and building-block skills are workflow-agnostic.** They must not mention workflows, run
  folders (`.maestro/runs`), step ids or other agents' artifacts. They take any input, expose
  **params with defaults**, and end with `Artifact:` / `Status:` / `Summary:` lines.
  Nothing checks this automatically, so keep it in mind when editing.
- **Workflow-specific instructions belong in `workflows/*.yaml`** (`params` + `instructions`).
- **The lead is generic.** It interprets the YAML schema documented in `skills/maestro/SKILL.md`
  and the README. A new schema key means updating both.
- If you change an agent's `Status:` values, update every workflow `next` map that routes on them.
- Templates are bundled in `agents/<agent>/templates/`. A bare template name resolves to
  `.maestro/templates/<name>` first.
- Keep it small. Before adding a validator, gate or state file, ask whether a sentence in a skill
  would do.

## Trying it

Run `./install.sh claude-code` inside a scratch project, then use `/maestro minor "..."` there.
