---
name: maestro-sync
description: Bring Maestro up to date after a repository is added to the workspace — the engine adds a maestro.config.yaml entry for each newly cloned repo, then detect-stack and project-config fill only those repos' stack and commands, matching stack skills are installed, and build-knowledge writes the new repos' docs (codebase map, domain pages, architecture.md). Front door for /maestro-sync or $maestro-sync.
allowed-tools: Read, Grep, Glob, Bash, Write, Task, AskUserQuestion
tags: [maestro, bootstrap]
---

# maestro-sync — onboard repositories added after `/maestro-init`

`/maestro-init` configures the repositories present when Maestro is adopted. When one is added
later (for example `./scripts/repository add <url>` in the workspace template), preflight fails
until `maestro.config.yaml` has an entry for it with `build` and `test` commands, and design
steps know nothing about it until it is in the living docs. This skill does both for the new
repositories only, leaving every existing entry and every other repo's docs as they are.

The config diff, which repos count as new, and the provenance records are deterministic engine
work (`project_config.py sync`, `codebase_scan.py`, `workspace_sync.py`); this skill supplies
only the judgement steps, by delegating to detect-stack, project-config and build-knowledge.

## When to use
Only after a new repository is added to the workspace (cloned into `codebase/`, usually after
registering it in `registry.yaml`), including after `./maestro sync` already added its config
entry. Not for removals or other changes. Safe to re-run: when nothing is new, step 2 finds
no targets and the skill stops.

## Steps
Run these **in order**, in this session. Each step consumes the previous step's result.

1. **Config diff.** Run
   `python3 .maestro/engine/project_config.py sync --root . --dry-run` and read its JSON:
   - `missing_clones` — registered but not cloned. Tell the person to clone them first
     (`./scripts/repository refresh` in the template); they are not configured until cloned.
   - `unregistered` — cloned but missing from `registry.yaml`. Report it; they are still
     configured, since Maestro works on every repo on disk. Suggest registering them.

   Then run the same command without `--dry-run`. Capture `added` and `needs_commands`.
2. **Pick the targets.** Run `python3 .maestro/engine/codebase_scan.py plan --root .`.
   - **Config targets** = `needs_commands` (it includes every added repo).
   - **Docs targets** = every repo whose entry has `prev_commit: null` (no codebase map yet —
     never documented), plus `added`, minus any whose `mode` is `current` (already documented
     at its HEAD). An entry with an older `prev_commit` is an existing repo whose map is merely
     out of date; it is not a target.

   Both empty: stop and report that nothing new needs setting up.
3. **Detect stack for the config targets only.** Skip when there are none. Load and follow the
   **`detect-stack`** skill, scanning only `codebase/<name>/` for each target. When it runs the
   installer, pass `--stack` as the union of the targets' tokens, the `stack` values already
   in `maestro.config.yaml`, and the `stacks` recorded in `.maestro/install.json` — never just
   the new tokens, so the recorded install stays complete. Skip the install when the targets
   add no token beyond that set.
4. **Project config.** Load and follow the **`project-config`** skill with the config targets'
   detect-stack `repos` result only. Its `apply` fills empty `stack` / `commands` and never
   overwrites a value already set. Do not report a `worktree` or `environment` section; the
   existing ones cover new repos.
5. **Write the new repos' docs** with **`build-knowledge`**. Skip when there are no docs targets.
   When `docs/architecture.md` does not exist, the workspace has never been documented: run
   build-knowledge for the whole workspace exactly as `/maestro-init` does (its steps 5–6) and
   go to step 6. Otherwise, with `<targets>` the docs targets comma-separated:
   1. `python3 .maestro/engine/codebase_scan.py snapshot --root . --repos <targets> --out .maestro/index/maestro-sync-map-snapshot.json`
      — capture `snapshot_sha256`. Then
      `python3 .maestro/engine/living_docs.py snapshot --root . --out .maestro/index/maestro-sync-docs-snapshot.json`.
   2. Load and follow **`build-knowledge`**, scoped to the targets. Its instruction to you:
      read only `codebase/<target>/` (plus its `AGENTS.md` / `CLAUDE.md` / `.cursor/rules`) and
      the existing `docs/`; then
      - write each target's **full** codebase map at `docs/codebase-maps/<name>.md` (without
        the marker line);
      - for each domain a target implements: a domain with no page yet gets new
        `docs/technical/<domain>.md` and `docs/functional/<domain>.md`; an existing domain
        page the target takes part in is extended in place to cover it. Never rewrite what a
        page says about other repos; never edit the team's invariants and change scenarios
        (`## Invariants and consistency`, `## Change scenarios`, `## Platform-wide invariants`,
        `docs/impact/side-effects.yaml`) — write what you find under
        `## Proposed rules and scenarios`;
      - update `docs/architecture.md`: the target's row in System context and repos, each of its
        connections in Cross-repo flows and contracts, and its domains in the Domain map —
        within budget;
      - do not seed review lessons.
      Then run `python3 .maestro/engine/living_docs.py check --root . --write --locked-from .maestro/index/maestro-sync-docs-snapshot.json --report`
      and fix every error it reports in the docs you wrote, until `valid` is true; then
      `python3 .maestro/engine/living_docs.py stamp --root . --snapshot .maestro/index/maestro-sync-docs-snapshot.json`.
   3. `python3 .maestro/engine/codebase_scan.py record --root . --snapshot .maestro/index/maestro-sync-map-snapshot.json --snapshot-sha256 <snapshot_sha256>`
      — stamps only the targets. If it refuses because a target's map was not written or did
      not change, go back to 5.2 for that repo.
   4. `python3 .maestro/engine/workspace_sync.py record-knowledge --root . --evidence docs/architecture.md --repos <targets>`
      — records the docs as describing the targets' current commits. Other repos keep their
      recorded commits, so one whose docs were already out of date stays flagged; name those
      in the summary (`/build-knowledge` refreshes them) rather than refreshing them here.
6. **Preflight.** Run `python3 .maestro/engine/maestroctl.py preflight`. Report every error
   verbatim; a missing `build` / `test` the evidence could not supply is for the person to fill
   by hand in `maestro.config.yaml`.
7. **Summarize.** Report the repos added and still needing commands, the stacks installed, the
   docs written (codebase maps, new and extended domain pages, architecture.md), any other
   repo whose docs are out of date, and the preflight result. Ask the person to review and
   commit `docs/` in the workspace. Newly installed skills become active after the host reloads its config. A
   feature run already in progress keeps the repositories its workspace lock pinned; the new
   repo joins the next feature.

## Standards
- Never re-implement the config diff, detection, config writing or doc generation here —
  delegate to `project_config.py sync`, detect-stack, project-config and build-knowledge.
- Only target repos are scanned, and only empty fields are filled; an existing repo's entry
  is never changed. Docs are written for the docs targets only; other repos' docs change only
  where a page they share gains the new repo.
- Only adds. An entry for a repository that is no longer in the workspace is left for the
  person to remove by hand (preflight warns about it).

## Safety
- Writes are `maestro.config.yaml` (via the engine and project-config), installer output in
  harness config dirs, documentation, codebase-map markers and `docs/provenance.yaml`.
- Never clone, register or remove a repository; never edit application code; never touch
  `.maestro/runs/` state or a run's workspace lock.

## Output contract
Return `added` (repo names, comma-separated), `needs_commands` (repos preflight still fails
on), `documented` (repos whose docs were written, comma-separated), `domains_written` (domain
pages created or extended), and `summary` (one line).
