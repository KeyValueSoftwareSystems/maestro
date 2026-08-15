---
name: maestro-init
description: One-shot onboarding for a repo — detect its tech stack and install the matching skills/agents (detect-stack), then build the living-docs knowledge base (build-knowledge). Run once when adopting Maestro in a codebase. Front door for /maestro-init.
allowed-tools: Read, Grep, Glob, Bash, Write, Task, AskUserQuestion
tags: [maestro, bootstrap]
---

# maestro-init — set Maestro up for this codebase

Bootstrap a repository for Maestro in one command: safely align its repositories with their
current upstreams, install the skills that match the repo's stack, then document the exact
commits that will be used. Sync facts and provenance come from deterministic engine scripts;
the two existing skills still own stack detection and knowledge authoring.

## When to use
The first time you adopt Maestro in a repo (or after a big stack change). Safe to re-run —
both underlying skills are idempotent (refresh, don't duplicate).

## Steps
Run these **in order**, in this session. On Claude Code you may dispatch each as a subagent
via Task; otherwise follow them inline.

1. **Fetch + consolidated sync gate** — run
   `python3 .maestro/engine/workspace_sync.py plan --root . --remote-only --out .maestro/index/workspace-sync-init-plan.json`.
   If `needs_attention=false`, continue without asking. Otherwise show its `summary` in ONE
   AskUserQuestion: **Update safe repos before indexing**, **Continue at current local
   commits**, or **Abort**. On update, run `workspace_sync.py apply` with the exact returned
   plan path/hash and `--out .maestro/index/workspace-sync-init-result.json`. It fast-forwards
   only clean, non-diverged current branches; never stash, merge, rebase or update an unsafe
   repo. Do not ask one question per repository.
2. **Detect stack + install** — load and follow the **`detect-stack`** skill: scan the repo,
   determine its stack tokens, and run the installer with `--stack <detected>` so only the
   core SDLC pack + the matching per-stack skills/agents are installed. Capture the detected
   `stacks` and `installed_count`.
3. **Build the knowledge base** — load and follow the **`build-knowledge`** skill: read the
   code and write the per-domain technical + functional docs, the architecture diagram, and a
   per-repo `docs/codebase-map.md` (the standing grounding each HLD reads; the engine records
   the commit each map reflects, so later refreshes only process the diff).
   Capture `domains_written` and `architecture_path`.
4. **Record exact provenance** — after knowledge authoring succeeds, run
   `python3 .maestro/engine/codebase_scan.py record --root .`, then
   `python3 .maestro/engine/workspace_sync.py record-knowledge --root . --evidence <architecture_path>`.
   This makes later `/maestro` starts a fast fetch + local SHA comparison with zero model call
   when nothing changed.
5. **Summarize + next step.** Report the stacks installed and the docs written, then tell the
   user that newly installed skills/agents become active after their IDE reloads the config,
   and that they can start a feature with `/maestro <slug>`.

## Standards
- Do not re-implement detection or doc-generation here — delegate to the two skills so their
  behaviour stays in one place. Remote status, safe update and provenance stay engine-owned.
- If step 1 detects no stack, still run step 2; report that no per-stack skills were added.

## Safety
- Writes are installer output into IDE config dirs (`.claude/`, `.cursor/`), documentation,
  codebase-map markers, and engine-owned `.maestro/index/` provenance. Never edit application
  code; never touch `.maestro/runs/` state. Repository updates are explicit-user-approved,
  verified fast-forwards only.

## Output contract
Return `stacks` (detected stack tokens, comma-separated), `installed_count` (skills + agents
installed), `domains_written` (count from build-knowledge), and `summary` (one line).
