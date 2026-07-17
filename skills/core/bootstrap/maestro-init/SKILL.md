---
name: maestro-init
description: One-shot onboarding for a repo — detect its tech stack and install the matching skills/agents (detect-stack), then build the living-docs knowledge base (build-knowledge). Run once when adopting Maestro in a codebase. Front door for /maestro-init.
allowed-tools: Read, Grep, Glob, Bash, Write, Task
tags: [maestro, bootstrap]
---

# maestro-init — set Maestro up for this codebase

Bootstrap a repository for Maestro in one command: install the skills that match the
repo's stack, then document the codebase. It orchestrates two existing skills in order —
it adds no logic of its own; each skill owns its "how".

## When to use
The first time you adopt Maestro in a repo (or after a big stack change). Safe to re-run —
both underlying skills are idempotent (refresh, don't duplicate).

## Steps
Run these **in order**, in this session. On Claude Code you may dispatch each as a subagent
via Task; otherwise follow them inline.

1. **Detect stack + install** — load and follow the **`detect-stack`** skill: scan the repo,
   determine its stack tokens, and run the installer with `--stack <detected>` so only the
   core SDLC pack + the matching per-stack skills/agents are installed. Capture the detected
   `stacks` and `installed_count`.
2. **Build the knowledge base** — load and follow the **`build-knowledge`** skill: read the
   code and write the per-domain technical + functional docs, the architecture diagram, and a
   per-repo `docs/codebase-map.md` (the standing grounding each HLD reads; the engine records
   the commit each map reflects, so later refreshes only process the diff).
   Capture `domains_written` and `architecture_path`.
3. **Summarize + next step.** Report the stacks installed and the docs written, then tell the
   user that newly installed skills/agents become active after their IDE reloads the config,
   and that they can start a feature with `/maestro <slug>`.

## Standards
- Do not re-implement detection, install, or doc-generation here — delegate to the two
  skills so their behaviour stays in one place.
- If step 1 detects no stack, still run step 2; report that no per-stack skills were added.

## Safety
- The only writes are those the two skills make: installer output into IDE config dirs
  (`.claude/`, `.cursor/`) and documentation under the docs root. Never edit application
  code; never touch `.maestro/` run state.

## Output contract
Return `stacks` (detected stack tokens, comma-separated), `installed_count` (skills + agents
installed), `domains_written` (count from build-knowledge), and `summary` (one line).
