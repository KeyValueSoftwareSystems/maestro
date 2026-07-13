---
name: build-knowledge
description: Bootstrap Maestro domain knowledge by scanning the codebase — emits authoritative structured lessons for the engine to render. Front door for /build-knowledge.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [maestro, memory, bootstrap]
---

# build-knowledge — seed domain knowledge from the codebase

Create the initial domain knowledge Maestro injects into future runs, by reading the existing
code. You produce a structured drop of **authoritative** lessons; the **engine**
(`mem_consolidate.py`) renders them into the injected `knowledge/*.md`. Run once per
workspace; re-runnable.

## Inputs
Your instruction names the incoming JSON file to write and the code surface to read (the
`codebase/` repos or the single repo, their `CLAUDE.md`/`.cursor/rules`, and `docs/`).
Standalone? Write to a sensible path and tell the user.

## Method
1. **Survey the code.** Per repo: entry points, build/test/run commands, directory layout,
   house style, cross-cutting conventions, recurring gotchas. Read each repo's
   `CLAUDE.md`/rules first — they state the team's norms.
2. **Emit a structured drop** as JSON to the incoming file named in your instruction:

   ```json
   {
     "slug": "bootstrap",
     "lessons": [
       {"domain": "codebase", "key": "postgres-16-everywhere",
        "text": "All services run Postgres 16; prefer its features.", "authoritative": true},
       {"domain": "backend-review", "key": "additive-migrations-only",
        "text": "Migrations must be additive-then-backfill on hot tables.", "authoritative": true}
     ]
   }
   ```

   - Bucket by consuming role: `codebase` (shared) plus `plan`, `backend-design`,
     `frontend-design`, `backend-review`, `frontend-review`, `architecture-review`.
   - `key` — short stable kebab-case identifier for the pattern.
   - Set **`authoritative: true`** on every bootstrap lesson — bootstrap seeds from real code,
     so these render into knowledge immediately (no corroboration threshold).
   - Do NOT write `knowledge/` or `candidates/` — the engine renders those.
3. **Short and actionable.** A claim + why. Bloat costs tokens on every future run.

## Standards
- Prefer few high-signal lessons over exhaustive dumps. Contradicting the actual code is
  worse than saying nothing.
- Do not invent conventions the code does not exhibit.

## Safety
- Read-only against the code; write only the incoming JSON file named in your instruction.
  Never edit application code here.

## Output contract
Return `domains_written` (count of distinct domains in the drop) and `summary` (one line:
what was seeded and from where).
