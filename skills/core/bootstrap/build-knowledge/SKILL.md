---
name: build-knowledge
description: Scan the codebase and build the living-docs knowledge base (architecture.md, plus functional and technical docs per domain with rule, invariant and change-scenario IDs), the per-repo codebase maps, and seed cross-cutting review lessons. Front door for /build-knowledge.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [maestro, memory, bootstrap, docs]
---

# build-knowledge — build the codebase knowledge base from the code

Read the existing code and write a durable knowledge base under `docs/`: a top-level
**architecture.md**, and per domain a **functional** doc (business rules, states, terms) and a
**technical** doc (invariants, change scenarios, failure behaviour, gotchas). Future agents read
these before planning or changing anything, so they hold what the code cannot tell them cheaply.
Run once per workspace; re-runnable (refresh, don't duplicate).

## Inputs
Your instruction names the docs root, the code surface to read (the `codebase/` repos or the
single repo, their `AGENTS.md`/`CLAUDE.md`/`.cursor/rules`, existing `docs/`), and, when one was
extracted, a workspace inventory of endpoints, calls, events, jobs, tables and config.
Standalone with no paths given? Write to `docs/` and tell the user.

## Format
Every file follows **[docs-format.md](docs-format.md)** exactly: front-matter, IDs, anchors,
headings, table columns and budgets. The steps below say what to write; the format file says
how it must look. A checker enforces it; when your instruction includes its report, fix exactly
what it names.

## What you write, and what you never write
- **Write only judgement**: purpose and actors, business rules with their edge cases, states and
  flows, failure and concurrency behaviour, gotchas, known gaps, owned unknowns.
- **Never edit the team's rules.** Invariants and change scenarios belong to the project's
  people: `## Invariants and consistency` and `## Change scenarios` in a technical doc,
  `## Platform-wide invariants` in the architecture, and `docs/impact/side-effects.yaml`. Leave
  them exactly as they are (a new doc's say `None.`). What you find goes under
  `## Proposed rules and scenarios`, without an ID, for the team to accept. The engine restores
  any change to the team's content and sends its check report back to you.
- **Never write what the code already lists**: endpoints, events, jobs, tables, config keys,
  calls between repos, directory listings, build commands. A tool generates those into
  `docs/_generated/` and the `Cross-repo connections` block; refer to them, never copy them.
- **Never edit generated output**: anything under `docs/_generated/` or `docs/_index/`, any
  `generated:` block, `verified_at`, and the codebase-map marker line.
- **Never invent** an owner, reviewer, incident, ticket or number. When the code does not settle
  a fact, write an owned unknown: `Unknown. (ask: <who>, since <today>)`.

## Method
1. **Survey the code.** Per repo: entry points, flows, datastores, house style. Read each repo's
   `AGENTS.md`, `CLAUDE.md` or Cursor rules first, applying the instruction files that exist for
   the active host. Use the workspace inventory to see every endpoint, call, event, job and table
   without grepping for them.
2. **Identify the domains**: the bounded contexts the code is organised around, in kebab-case.
   Give each a short capital `id_prefix` (e.g. `PL` for `payment-links`) and its `code_roots`.
3. **Per domain, write two files** in the format:
   - `docs/functional/<domain>.md`: purpose and actors; glossary; business rules (`BR`), each
     with its edge and source; states and flows; open questions.
   - `docs/technical/<domain>.md`: failure, concurrency and idempotency; gotchas; known gaps;
     and the proposals: each invariant you find (what must always hold, the anchor that enforces
     it, the test that proves it) and each change scenario (changing this anchor also affects
     that). Leave the team's sections as they are and the `Cross-repo connections` section
     holding only its generated block markers.
   Read the code that enforces a rule before writing or proposing it. A rule you cannot point at
   code for is either an owned unknown or not a rule.
4. **Write `docs/architecture.md`**: system context and repos, the Domain map (a row per domain
   linking both files), cross-repo flows and contracts, conventions and boundaries, shared
   glossary; platform-wide invariants you find are proposals. Within budget.
5. **Refresh = keep IDs stable.** Update business-rule rows in place. A new rule takes the next
   free number (`python3 .maestro/engine/living_docs.py next <PREFIX>`). Never renumber or reuse
   an ID; a rule that no longer holds keeps its row as `Retired YYYY-MM-DD: <why>`. When changed
   code breaks one of the team's invariants or scenarios, propose the fix; never edit theirs.
6. **Seed cross-cutting review lessons (optional).** For recurring standards/pitfalls that
   belong to the corroborated-lesson store (not domain docs), also write an authoritative
   drop to the memory incoming path named in your instruction, as JSON:
   `{"slug": "bootstrap", "lessons": [{"domain": "backend-review", "key": "<kebab>",
   "text": "...", "authoritative": true}]}`. The engine renders these; you do not.

## Per-repo codebase map (the HLD's primary grounding)
For EACH repo — in an umbrella workspace, each repo under `codebase/`; single repo, the repo
itself — write **`docs/codebase-maps/<name>.md`** (`map_path` in the plan below gives each one) in
the shape docs-format.md gives: entry points and key modules; how the repo is built, tested and
run; the primary flows and **every distinct execution mode** each runs in and what selects it; the
data model, APIs, auth and error conventions — each pointed at as a `path · symbol` anchor, never
a line number.

Run `python3 .maestro/engine/codebase_scan.py plan` first to see which repos to map and their
scope — at bootstrap every repo is `full` (write the whole map); on a refresh a repo is
`incremental` (update only the areas its `changed_files` touch) or `current` (skip). Do **not**
write or edit the `<!-- maestro-codebase-map commit=… -->` marker line — the engine stamps the
commit after you write, and that recorded commit is what makes the next refresh incremental.
The maps are committed with the rest of `docs/`.

## Standards
- Document what the code **actually does today**, not aspirations. A wrong doc is worse than
  a missing one; a short doc of true facts beats a long one.
- Every row starts with its subject and reads on its own.
- Re-run = refresh: update existing files in place; add files for new domains; keep human edits.

## Safety
- Read-only against application code; write only the written docs (`docs/architecture.md`,
  `docs/functional/`, `docs/technical/`, `docs/codebase-maps/`) and the optional memory incoming
  drop named in your instruction. Never edit application code or generated files.

## Output contract
Return `domains_written` (count of domains documented), `architecture_path` (the
architecture.md you wrote), and `summary` (one line).
