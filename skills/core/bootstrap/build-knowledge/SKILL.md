---
name: build-knowledge
description: Scan the codebase and build the living-docs knowledge base (architecture.md, plus one doc per domain in parts — summary, references, functional, technical, side effects, maintenance — with rule, invariant, side-effect and change-scenario IDs), the per-repo codebase maps, and seed cross-cutting review lessons. Front door for /build-knowledge.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [maestro, memory, bootstrap, docs]
---

# build-knowledge — build the codebase knowledge base from the code

Read the existing code and write a durable knowledge base under `docs/`: a top-level
**architecture.md**, and per domain one **`<domain>.md`**: a short summary and the documents it
relies on, then its functional part (rules, flows, states), technical part (architecture,
clients, invariants, failures, error codes, security), side effects on other domains, and
maintenance notes. Future agents read the summary, follow `depends_on` and the links to what is
related, and then read one part, so the doc holds what the code cannot tell them cheaply, each
fact once, and a link wherever a reader would otherwise search.
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

**Fix errors, not warnings.** Only an `ERROR` line fails the check. Warnings (`WARN`: a doc over
its token budget, anchors changed since `verified_at`, docs still `draft`) never do, and
`draft` is set by the engine. Do not reword docs to shave a budget, and do not re-verify anchors
the audit already covers. An error you cannot fix from `docs/` (for example R6, an app call no
repository serves, which needs a change to app code or to `docs.ignore_calls` in
`maestro.config.yaml`) is not yours: say so in your report instead of editing around it. Run the
checker once after your edits, not after each one; a run takes seconds to minutes.

## The team's own documents come first
People often drop their own documents into the workspace: a product spec, a domain write-up, an
exported wiki page. Your instruction lists them (any file under `docs/` that is not a living doc,
plus the ones the project configures). They outrank what you infer from the code:
- **Read them first**, and follow them: a business rule, term or flow they state is written as
  they state it, citing the document as its source. Never contradict one.
- **Where the code disagrees**, still follow the document. Add the difference to the domain's
  open questions and list it in the conflict file your instruction names, with what the
  document says, what the code does and the `repo · path · symbol` that shows it. A person
  decides; you never pick a side.
- **Add, never overwrite.** You may append to a team document (a missing detail, a cross-link).
  Never change or remove what it says, and never delete or rename it: the engine puts the
  original back and shows your version to a person as a proposal.

## What you write, and what you never write
- **Write only judgement**: the summary, references, purpose and actors, business rules with
  their edge cases, user flows, states, architecture notes, client behaviour, failure and
  concurrency behaviour, error codes, security notes, side effects on other domains, gotchas and
  open questions.
- **Never edit the team's rules.** Invariants and change scenarios belong to the project's
  people: `## Invariants` and `## Change scenarios` in a domain doc,
  `## Platform-wide invariants` in the architecture, and `docs/impact/side-effects.yaml`. Leave
  them exactly as they are (a new doc's say `None.`). What you find goes under
  `## Proposed rules and scenarios`, without an ID, for the team to accept. The engine restores
  any change to the team's content and sends its check report back to you.
- **Never write what the code already lists**: endpoints, events, jobs, tables, config keys,
  calls between repos, directory listings, build commands. A tool generates those into each
  domain doc's `Cross-repo connections` and `Inventory` blocks; refer to them, never copy them.
- **Never repeat a fact.** Each fact has one place (docs-format.md rule 8); everywhere else, cite
  its ID. An HTTP status lives only in Error codes, a config default only in the generated
  inventory, an effect on another domain only in its Outbound row ("see AUTH-SE-001"). A gotcha
  or failure bullet names the rule it protects; it does not restate it.
- **Link what is related.** Every document the domain relies on goes in References as a link;
  every other domain a flow hands over to or a side effect reaches is linked
  (`[notifications](notifications.md)`) and listed in `depends_on`. A reader should never have to
  search the repo for something the doc knows about.
- **Never edit generated output**: `docs/architecture.mmd`, `docs/code-to-facts.md`, any
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
3. **Per domain, write one file**, `docs/<domain>.md`, in the format's parts:
   - top: a 3–5 line Summary (what it owns, who uses it and where, its main methods, what it
     does not own and who does) and References (a link to every document it relies on);
     `depends_on` in the front-matter.
   - Part A, functional: purpose and actors; glossary; business rules (`BR`) with edge, status
     and source; user flows as numbered steps (screen → endpoint → result); states and
     transitions.
   - Part B, technical: architecture bullets; client behaviour (`CL`); failure, concurrency and
     idempotency; error codes with each client's handling; security notes.
   - Part C, side effects: one Outbound row (`SE`) per effect this domain has on another: the
     rule that triggers it, the target domain (linked), the exact event, endpoint or table, the
     target's rule, whether it is in the same transaction, and what is left behind on failure.
   - Part D, maintenance: gotchas (traps, known gaps, tech debt), open questions (with a named
     person and a date), and the proposals (each invariant you find: what must always hold, the
     anchor that enforces it, the test that proves it; each change scenario: changing this also
     needs that).
   Leave the team's sections (Invariants, Change scenarios) as they are, and Inbound,
   Cross-repo connections and Inventory holding only their generated block markers.
   Read the code that enforces a rule before writing or proposing it. A rule you cannot point at
   code for is either an open question or not a rule.
4. **Write `docs/architecture.md`**: system context and repos, the Domain map (a row per domain
   linking its doc), cross-repo flows and contracts, conventions and boundaries, shared
   glossary; platform-wide invariants you find are proposals. Within budget.
5. **Refresh = keep IDs stable.** Update rows in place. A new rule takes the next free number
   (`python3 .maestro/engine/living_docs.py next <PREFIX>`). Never renumber or reuse an ID; a
   business rule that no longer holds keeps its row with Status `removed`. When changed
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
  An older layout (`functional/` + `technical/`, or a domain doc without parts) is moved into
  this format by the engine before you start, every word kept; write the Summary and References
  it leaves empty. If you still find an old one, move its content into the parts as is.

## Safety
- Read-only against application code; write only the written docs (`docs/architecture.md`,
  `docs/<domain>.md`, `docs/codebase-maps/`), additions to the team's documents, the conflict
  file and the optional memory incoming drop named in your instruction. Never create other files
  under `docs/`, and never edit application code or generated files.

## Output contract
Return `domains_written` (count of domains documented), `architecture_path` (the
architecture.md you wrote), and `summary` (one line).
