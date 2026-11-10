---
name: retrospect
description: Distill a finished Maestro run into structured, keyed lessons staged for the engine to consolidate. Front door for /retrospect.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [maestro, memory, retrospective]
---

# retrospect — turn one run's outcomes into staged lessons

Read a finished feature run and extract what future runs should know. You produce ONLY a
structured per-run drop; the **engine** (`mem_consolidate.py`) owns counting, corroboration,
promotion and rendering — none of that is your concern, so a replacement skill only has to
emit the same drop for the memory system to keep working.

## Inputs
Your instruction names the run to read (its ledger + artifacts) and the single incoming JSON
file to write. Standalone? Write to a path you choose and tell the user.

The two things worth remembering are **what the user asked to change** and **what went
wrong while running** — because both are where a future run can do better from the start.

## Method
1. **Capture the user's requested changes.** This is the primary signal. Walk the gate
   history in `state.yaml` (`gates`): every revise/rework request and review finding the
   human raised, the `feedback`/`guidance` text they gave, and anything they had to correct
   so the output finally matched the requirement. Also read `state.yaml`'s `notes` — the
   out-of-band instructions the user gave mid-run — they are requested changes too. Read the
   requirement itself (under `.maestro/<slug>/requirement/`) to frame each as the gap it
   closed. Turn each into forward-looking guidance so the NEXT run gets it right the first
   time — e.g. "list endpoints must paginate — requested at contract review on add-orders".
2. **Capture the issues faced while running.** Operational problems during the run: steps
   that failed or retried, loops that hit their visit cap, contract-check / QA / build
   breakages, worktree or merge trouble — anything (from `visits`/`attempts`/`status`,
   failure reasons, and the artifacts) that made the run stumble. Turn each into a lesson
   that helps a future run avoid it.
3. **Add to / refresh the living docs — functional, technical, AND architectural.** Keep every
   file in the shared living-docs format ([docs-format.md](../build-knowledge/docs-format.md)).
   For every domain the feature touched:
   - **Functional** (`docs/functional/<domain>.md`) — the rules the feature added or changed
     (from the approved PRD's acceptance criteria and the gate feedback) as `BR` rows with their
     edge and source; new states, flows, terms and open questions.
   - **Technical** (`docs/technical/<domain>.md`) — new failure and concurrency behaviour and
     the gotchas the reviews raised. The invariants the design relied on and the change
     scenarios the run discovered (what else broke or had to change, which tests verify it) go
     under `## Proposed rules and scenarios`, without an ID, for the team to accept.
   - **Architectural** (`docs/architecture.md`) — a new repo or provider, a new or changed
     cross-repo flow, a new domain (a Domain map row linking both of its files).
   - **Never the team's rules.** `## Invariants and consistency`, `## Change scenarios`,
     `## Platform-wide invariants` and `docs/impact/side-effects.yaml` belong to the project's
     people: leave them exactly as they are. The engine restores any change to them.
   - **Per-repo codebase map** (`docs/codebase-maps/<name>.md` for each affected repo) — run
     `python3 .maestro/engine/codebase_scan.py plan` to get, per repo, the files changed since
     the map was last recorded; update ONLY those areas (new/changed flows, execution modes,
     APIs, conventions). A repo reported `current` is unchanged — skip it. Do NOT touch the
     `<!-- maestro-codebase-map commit=… -->` marker — the engine restamps it after you write.
   IDs: a new business rule takes the next free number in its doc; never renumber or reuse one; a
   rule the feature made untrue keeps its row as `Retired YYYY-MM-DD: <why>`. Cite existing IDs instead of
   restating them. Never write what the code lists (endpoints, events, jobs, tables, config, calls
   between repos) and never edit generated output (`docs/_generated/`, `docs/_index/`, any
   `generated:` block, `verified_at`): a tool regenerates them. A new domain gets both files and a
   Domain map row. Skip a surface only when the feature genuinely did not affect it.
4. **Emit a structured lessons drop.** Write the incoming file named in your instruction as JSON:

   ```json
   {
     "slug": "<this run's slug>",
     "lessons": [
       {"domain": "backend-review", "key": "n-plus-one-list-endpoints",
        "text": "Check for per-row queries in loops before approving."}
     ]
   }
   ```

   - `domain` — the consuming SDLC role the lesson helps (`plan`, `backend-design`,
     `backend-review`, `architecture-review`, or `codebase` for cross-cutting facts).
   - `key` — a short, stable, kebab-case identifier for the *pattern*. Pick it so a DIFFERENT
     run observing the same pattern would choose the SAME key — that is how the engine
     corroborates across runs. Do not encode the slug or a date in the key.
   - `text` — one short, actionable sentence.
   - Do NOT set `authoritative` (that is for bootstrap). Do NOT write `knowledge/` or
     `candidates/` — the engine renders those.

## Standards
- A lesson is a repeatable pattern, not a one-off event narration. If it only makes sense for
  this feature, leave it out.
- Keep `text` short; injected knowledge is paid for in tokens on every future run.

## Safety
- Read-only against application code; writes are limited to the incoming JSON drop named in
  your instruction and the living docs it refreshes (the central `docs/` tree, including
  `docs/codebase-maps/`). Never edit application code or run state.

## Output contract
Return `incoming_path` (the JSON file written), `lessons_count` (integer), and `summary`
(one line).
