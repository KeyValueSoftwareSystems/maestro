---
name: maestro-init
description: One-shot onboarding for a repo — detect its tech stack and install the matching skills/agents (detect-stack), then build the living-docs knowledge base (build-knowledge) only when docs are stale. Run once when adopting Maestro in a codebase. Front door for /maestro-init or $maestro-init.
allowed-tools: Read, Grep, Glob, Bash, Write, Task, AskUserQuestion
tags: [maestro, bootstrap]
---

# maestro-init — set Maestro up for this codebase

Bootstrap a repository for Maestro in one command: safely align its repositories with their
current upstreams, install the skills that match the repo's stack, then document the exact
commits that will be used — **skipping knowledge authoring when docs are already current**.
Sync facts and provenance come from deterministic engine scripts; the two existing skills
still own stack detection and knowledge authoring.

## When to use
The first time you adopt Maestro in a repo (or after a big stack change). Safe to re-run —
both underlying skills are idempotent (refresh, don't duplicate). On a template umbrella
that already ran `/workspace-index`, this should usually install stacks and skip docs.

## Steps
Run these **in order**, in this session. On Claude Code or Codex you may dispatch a step to
a subagent when that keeps bulky scanning out of the lead context; otherwise follow it
inline. Never parallelize these steps because each consumes the previous step's result.

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
3. **Docs freshness gate** — before authoring, run a **full** (not `--remote-only`) plan:
   `python3 .maestro/engine/workspace_sync.py plan --root . --no-fetch --out .maestro/index/workspace-sync-init-knowledge.json`
   and `python3 .maestro/engine/codebase_scan.py plan --root .`.
   Also accept a template umbrella that already indexed: if `docs/.index-state.yaml` exists
   and `.maestro/index/knowledge-state.json` does not, run
   `./scripts/docs-drift import-provenance` (when that script exists) once, then re-check.
   **Skip** step 4 (build-knowledge) and step 5 map/knowledge `record` when
   `refresh_needed=false`, maps are not stale, and `docs/architecture.md` is present —
   set `domains_written=0` and note “docs already current”.
4. **Build the knowledge base (only if stale / missing)** — load and follow the
   **`build-knowledge`** skill (or start the `build-knowledge` workflow): read the code and
   write the per-domain technical + functional docs, the architecture diagram, and a
   per-repo `docs/codebase-map.md`. Capture `domains_written` and `architecture_path`.
5. **Record exact provenance** — only after knowledge authoring in step 4 succeeds, run
   `python3 .maestro/engine/codebase_scan.py record --root .`, then
   `python3 .maestro/engine/workspace_sync.py record-knowledge --root . --evidence <architecture_path>`.
   (The `build-knowledge` workflow already does this when you run it as a workflow.)
   This makes later `/maestro` or `$maestro` starts a fast fetch + local SHA comparison with
   zero model call when nothing changed.
6. **Summarize + next step.** Report the stacks installed and whether docs were written or
   skipped, then tell the user that newly installed skills/agents become active after their
   host reloads the config, and that they can start a feature with `/maestro <slug>` or
   `$maestro <slug>`.

## Standards
- Do not re-implement detection or doc-generation here — delegate to the two skills so their
  behaviour stays in one place. Remote status, safe update and provenance stay engine-owned.
- If step 2 detects no stack, still finish; report that no per-stack skills were added.
- Never run a second full `/workspace-index` “to be safe” when Maestro’s gate says current.

## Safety
- Writes are installer output into harness config dirs (`.claude/`, `.cursor/`, `.agents/`), documentation,
  codebase-map markers, and engine-owned `.maestro/index/` provenance. Never edit application
  code; never touch `.maestro/runs/` state. Repository updates are explicit-user-approved,
  verified fast-forwards only.

## Output contract
Return `stacks` (detected stack tokens, comma-separated), `installed_count` (skills + agents
installed), `domains_written` (count from build-knowledge, or `0` if skipped), and `summary`
(one line).
