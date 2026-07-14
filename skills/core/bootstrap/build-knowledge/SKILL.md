---
name: build-knowledge
description: Scan the codebase and build a structured living-docs knowledge base (technical + functional per domain, plus an architecture diagram), and seed cross-cutting review lessons. Front door for /build-knowledge.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [maestro, memory, bootstrap, docs]
---

# build-knowledge — build the codebase knowledge base from the code

Read the existing code and write a durable, human-facing knowledge base under `docs/`:
per-domain **technical** and **functional** docs, plus a top-level **architecture.md** that
shows how the services connect. This is committed documentation the whole team (and future
Maestro runs) reads. Run once per workspace; re-runnable (refresh, don't duplicate).

## Inputs
Your instruction names the docs root to write under and the code surface to read (the
`codebase/` repos or the single repo, their `CLAUDE.md`/`.cursor/rules`, existing `docs/`).
Standalone with no paths given? Write to `docs/` and tell the user.

## Method
1. **Survey the code.** Per repo: entry points, build/test/run commands, directory layout,
   house style, dependencies, datastores. Read each repo's `CLAUDE.md`/rules first.
2. **Identify the domains** — the bounded contexts / feature areas the code is organised
   around (e.g. `auth`, `order-management`, `catalog`, `payments`). Use kebab-case names.
3. **Per domain, write two files:**
   - `docs/technical/<domain>.md` — the technical view: key modules/packages, data model &
     schemas, the APIs it exposes and consumes, storage, background jobs, and the
     build/test commands specific to it.
   - `docs/functional/<domain>.md` — the functional view: what the domain does, the business
     rules, the primary user/actor flows, and notable edge cases.
4. **Write `docs/architecture.md`** — the whole-system view:
   - One or more **Mermaid** diagrams (```mermaid fenced blocks) showing every service/
     component as a node and every connection as an edge.
   - **How the services connect** — for each edge: the protocol (REST / gRPC / GraphQL /
     event/queue / shared DB), direction, sync vs async, what data flows, and how calls are
     authenticated between services. Call out the datastores each service owns.
   Example shape (derive the real one from the code):
   ```mermaid
   graph LR
     FE[Web frontend] -->|REST/JSON| BE[Backend API]
     BE -->|SQL| DB[(Postgres)]
     BE -->|gRPC| PAY[Payments svc]
     BE -->|publish| Q[[order-events]]
     WORKER[Order worker] -->|subscribe| Q
   ```
5. **Seed cross-cutting review lessons (optional).** For recurring standards/pitfalls that
   belong to the corroborated-lesson store (not domain docs), also write an authoritative
   drop to the memory incoming path named in your instruction, as JSON:
   `{"slug": "bootstrap", "lessons": [{"domain": "backend-review", "key": "<kebab>",
   "text": "...", "authoritative": true}]}`. The engine renders these; you do not.

## Standards
- Document what the code **actually does today**, not aspirations. A wrong doc is worse than
  a missing one.
- Keep Mermaid node/edge labels short; the diagram must render. Prefer a couple of focused
  diagrams (service topology, and a data-flow per critical path) over one unreadable graph.
- Re-run = refresh: update existing domain files in place; add files for new domains; keep
  human edits.

## Safety
- Read-only against application code; write only under the docs root (and the optional memory
  incoming drop) named in your instruction. Never edit application code here.

## Output contract
Return `domains_written` (count of domains documented), `architecture_path` (the
architecture.md you wrote), and `summary` (one line).
