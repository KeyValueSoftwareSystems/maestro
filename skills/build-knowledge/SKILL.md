---
name: build-knowledge
description: Bootstrap Maestro domain knowledge by scanning the codebase — writes initial knowledge files under the memory store. Front door for /build-knowledge.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [maestro, memory, bootstrap]
---

# build-knowledge — seed domain knowledge from the codebase

Create the initial domain-knowledge files Maestro injects into future runs, by reading the
existing code. Run once per workspace; re-runnable (it MERGES, never clobbers).

## Inputs
Your instruction names the memory store paths to write and the code surface to read (the
`codebase/` repos or the single repo, their `CLAUDE.md`/`.cursor/rules`, and `docs/`).
Standalone with no paths given? Write to a sensible memory location and tell the user where.

## Method
1. **Survey the code.** Per repo: entry points, build/test/run commands, directory layout,
   house style, cross-cutting conventions, recurring gotchas. Read each repo's
   `CLAUDE.md`/rules first — they state the team's norms.
2. **Bucket by consumer.** Write one knowledge file per consuming SDLC role, plus a shared
   `codebase.md`: `plan`, `backend-design`, `frontend-design`, `backend-review`,
   `frontend-review`, `architecture-review` — each holding the standards/pitfalls a step in
   that role should know before it starts.
3. **Short and actionable** — a claim + why it matters. This text is injected into prompts;
   bloat costs tokens on every future run.
4. **Provenance.** Tag each entry `_(bootstrap)_`.
5. **Merge, don't clobber.** If a knowledge file exists, integrate new observations and keep
   human edits and accrued lessons.
6. **Index.** Write/refresh the store's `index.md` (one line per knowledge file).

## Standards
- Prefer few high-signal lessons over exhaustive dumps. Contradicting the actual code is
  worse than saying nothing.
- Do not invent conventions the code does not exhibit.

## Safety
- Read-only against the code; write only the memory store files named in your instruction.
  Never edit application code here.

## Output contract
Return `domains_written` (count of knowledge files created/updated) and `summary` (one line:
what was seeded and from where).
