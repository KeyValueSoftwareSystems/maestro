---
name: maestro-init
description: One-shot onboarding for a repo — detect-stack installs matching skills, then the project-config skill writes maestro.config.yaml from that result (registry.yaml names when present), then build the living-docs knowledge base only when docs are stale. Run once when adopting Maestro in a codebase. Front door for /maestro-init or $maestro-init.
allowed-tools: Read, Grep, Glob, Bash, Write, Task, AskUserQuestion
tags: [maestro, bootstrap]
---

# maestro-init — set Maestro up for this codebase

Bootstrap a repository for Maestro in one command: safely align its repositories with their
current upstreams, run **detect-stack** (install only — it does not touch
`maestro.config.yaml`), then run **project-config** to write that file from the detect-stack
result and from `registry.yaml` when it exists, then document the exact commits that will
be used — **skipping knowledge authoring when docs are already current**.
Sync facts and provenance come from deterministic engine scripts; detect-stack, project-config,
and build-knowledge each own one job.

## When to use
The first time you adopt Maestro in a repo (or after a big stack change). For a repository
added later, use **`/maestro-sync`** instead — it handles only the new ones. Safe to re-run —
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
2. **Detect stack + install** — load and follow the **`detect-stack`** skill. It installs
   matching skills and returns `repos` (`name`, `stacks`, `evidence`). It must not write
   `maestro.config.yaml`. Capture `stacks`, `installed_count`, and `repos`.
3. **Project config** — load and follow the **`project-config`** skill with that `repos`
   result. It writes `maestro.config.yaml` (registry names when `registry.yaml` exists;
   stack and commands from the detect-stack evidence; the `worktree` commands from a workspace
   sandbox script and the `environment` commands from a workspace infra script when there is
   one; each repo's `e2e` command only after the engine confirmed detect-stack's E2E proposal).
   It does not scan again and does not read the knowledge base. Capture `created`, `updated`
   and its `e2e` map, and show the person any worktree or environment commands it set.
4. **Docs freshness gate** — before authoring, run a **full** (not `--remote-only`) plan:
   `python3 .maestro/engine/workspace_sync.py plan --root . --no-fetch --out .maestro/index/workspace-sync-init-knowledge.json`
   and `python3 .maestro/engine/codebase_scan.py plan --root .`.
   Provenance is `docs/provenance.yaml` (shared with the template workspace-index skill);
   no separate knowledge-state import step.
   **Skip** step 5 (build-knowledge) when `refresh_needed=false`, maps are not stale, and
   `docs/architecture.md` is present — set `domains_written=0` and note “docs already current”.
   Still run step 6b (`ensure-index-state`) so template-written state gets `docs_sha256`.
5. **Build the knowledge base (only if stale / missing)** — first run
   `python3 .maestro/engine/docs_rewrite.py check --root . --plan .maestro/index/workspace-sync-init-knowledge.json`;
   when `needs_approval` is true (verified docs would be rewritten), show its `summary` in ONE
   AskUserQuestion — **Refresh the docs** or **Keep the docs as they are** (set
   `domains_written=0`, skip to step 6b) — and wait for the answer. Then load and follow the
   **`build-knowledge`** skill (or start the `build-knowledge` workflow): read the code and
   write the per-domain technical + functional docs, the architecture diagram, and a
   codebase map per repo under `docs/codebase-maps/`. Capture `domains_written` and `architecture_path`.
6. **Record exact provenance**
   - **6a (after authoring in step 5):** run
     `python3 .maestro/engine/codebase_scan.py record --root .`, then
     `python3 .maestro/engine/workspace_sync.py record-knowledge --root . --evidence <architecture_path>`.
     (The `build-knowledge` workflow already does this when you run it as a workflow.)
   - **6b (always when docs are current, including skip of step 5):** run
     `python3 .maestro/engine/workspace_sync.py ensure-index-state --root . --evidence docs/architecture.md`.
     No-op if `docs_sha256` already present; fills it when template indexed first. Do **not** skip
     this on the “docs already current” path — without it, doc-content drift is invisible.
   This makes later `/maestro` or `$maestro` starts a fast fetch + local SHA comparison with
   zero model call when nothing changed.
7. **Domain rules (optional)** — run `python3 .maestro/engine/living_docs.py status --root .`.
   Invariants that must never break (`<PREFIX>-INV-NNN`) and change scenarios
   (`<PREFIX>-CS-NNN`) are written by the project's people in `docs/technical/<domain>.md`
   (`## Invariants and consistency`, `## Change scenarios`) and `docs/impact/side-effects.yaml`;
   Maestro uses them when they exist and runs fine without them.
   - **`present=true`** — run `python3 .maestro/engine/living_docs.py rules --root .` and report
     its `summary`. When `valid=false`, show its `issues_summary` and say the docs or the code need
     fixing; do not fix them here and do not stop init.
   - **`present=false`** — ask ONE question (AskUserQuestion on Claude Code; a numbered choice on
     Cursor, answered in the next message): Maestro can use domain rules and change scenarios if
     the team adds them under `docs/`. Options: **Create the starter file** (run
     `python3 .maestro/engine/living_docs.py scaffold --root .`, then point them at
     `docs/impact/side-effects.yaml`, the `## Invariants and consistency` / `## Change scenarios`
     sections of each `docs/technical/<domain>.md`, and the proposals build-knowledge left under
     `## Proposed rules and scenarios`, as described in `.maestro/docs/domain-rules.md`) or
     **Skip, no domain rules**. Either answer finishes init.
   Never write or invent rules yourself: the team decides what the rules are.
8. **Summarize + next step.** Report the stacks installed, whether docs were written or
   skipped, whether domain rules were found (and checked), and whether the project-config skill
   created or updated `maestro.config.yaml`.
   Show each repo's `build` and `test` and ask the user to confirm them before a
   feature run. Report each confirmed E2E suite; when none was found, say QA will check the
   test cases directly instead of writing an E2E suite. Then tell them that newly installed skills/agents
   become active after their host reloads the config, and that they can start a feature
   with `/maestro <slug>` or `$maestro <slug>`.

## Standards
- Do not re-implement detection, config writing, or doc-generation here — delegate to
  detect-stack, project-config, and build-knowledge. Remote status, safe update and
  provenance stay engine-owned.
- If step 2 detects no stack, still run step 3 and finish; report that no per-stack skills
  were added.
- Never run a second full `/workspace-index` “to be safe” when Maestro’s gate says current.

## Safety
- Writes are installer output into harness config dirs (`.claude/`, `.cursor/`, `.agents/`), documentation,
  codebase-map markers, `docs/provenance.yaml`, the empty starter
  `docs/impact/side-effects.yaml` only when the person asks for it, and — only via the
  project-config skill — `maestro.config.yaml`. Never edit application code; never touch
  `.maestro/runs/` state.
  Repository updates are explicit-user-approved, verified fast-forwards only.

## Output contract
Return `stacks` (detected stack tokens, comma-separated), `installed_count` (skills + agents
installed), `domains_written` (count from build-knowledge, or `0` if skipped), and `summary`
(one line).
