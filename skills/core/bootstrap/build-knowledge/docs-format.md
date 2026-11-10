<!-- docs-format v2. Maestro (skills/core/bootstrap/build-knowledge/docs-format.md) and
     dev-workspace-template (skills/workspace-index/docs-format.md) each ship this file so each
     works on its own. When the format changes, update both. -->

# Living docs format

One format for the workspace docs, whichever tool writes them: Maestro's `build-knowledge`
and `retrospect`, or the template's `workspace-index` when Maestro is not installed.
When Maestro is installed it is the only writer; the template hands off to `/build-knowledge`.

## Layout

Readers open the architecture first, then one domain, then one repo map. Nobody loads all of
`docs/`.

```
docs/
  architecture.md              # level 0: always read first, at most 200 lines
  technical/<domain>.md        # level 1: per-domain technical view
  functional/<domain>.md       # level 1: per-domain functional view
  codebase-maps/<name>.md      # level 2: one map per repo
  provenance.yaml              # written by tools, never by hand
```

`<name>` is the repo's folder under `codebase/` (in a single-repo workspace, the repo's own
folder name).

Token cost while **writing** does not matter: read every repo and doc you need to be accurate.
The size limits are for what **readers** load.

**Domains** are the bounded contexts the code is organised around (`auth`, `order-management`,
`payments`). Name them in kebab-case. A domain may span several repos. Do not name domains
after repos unless the repo really is one bounded context.

Write what the code **does today**, not plans. Describe contracts and intent; skip the
file-by-file detail the code already gives. Re-running refreshes in place: update existing
files, add files for new domains, keep human edits.

## `docs/architecture.md`

At most **200 lines**, whatever the repo count. Rewrite it after any repo or domain
change. It has these `##` sections:

1. A one-line note at the top telling readers to start here and open only what they need.
2. `## System`: 2–5 sentences.
3. `## Topology`: one or more ```` ```mermaid ```` diagrams with every service,
   component and datastore as a node and every connection as an edge labelled with its
   protocol. Keep labels short so it renders. Prefer a topology diagram plus a data-flow per
   critical path over one unreadable graph.

   ```mermaid
   graph LR
     FE[Web frontend] -->|REST/JSON| BE[Backend API]
     BE -->|SQL| DB[(Postgres)]
     BE -->|publish| Q[[order-events]]
     WORKER[Order worker] -->|subscribe| Q
   ```

4. `## Services`: one row per repo: name, kind, one-line purpose, link to its codebase map
   (`codebase-maps/<name>.md`).
5. `## How services connect`: per edge, the protocol (REST / gRPC / GraphQL / event or queue /
   shared DB), direction, sync or async, what data flows, and how calls are authenticated.
   Say which datastores each service owns.
6. `## Domains`: one row per domain: name, a link to `technical/<domain>.md`, a link to
   `functional/<domain>.md` (every domain file is listed, every listed
   file exists), and the repos involved.
7. `## Cross-cutting conventions`: short bullets for patterns shared across repos.

No per-repo detail beyond one line. With 30+ repos, group the services rows by domain.

## `docs/technical/<domain>.md`

- First line `# <domain>: Technical`.
- Then a line listing the repos involved (linked to their maps, `../codebase-maps/<name>.md`)
  and a link to
  `../functional/<domain>.md`.
- Then `##` sections (at least one): key modules and packages, data model and
  schemas, APIs exposed and consumed, storage, background jobs, build and test commands
  specific to the domain. Leave a section out only when the domain has nothing for it.

## `docs/functional/<domain>.md`

- First line `# <domain>: Functional`.
- Then the repos involved and a link to `../technical/<domain>.md`.
- Then `##` sections (at least one): what the domain does, business rules, primary
  user and actor flows (steps that cross services, in order, naming each service), notable
  edge cases.

Every domain has **both** files.

## `docs/codebase-maps/<name>.md`

The standing per-repo description a designer reads before changing that repo. One per repo.

- First line `# <name>: Codebase map`.
- `##` sections covering: entry points and key modules; how the repo is built, tested and
  run; the primary end-to-end flows and **every distinct execution mode** each runs in
  (single-turn or multi-turn, sync or async, batch or streaming, first request or idempotent
  retry, single- or multi-tenant…), what selects each mode and where it lives, cited to
  `file:line`; the data model, APIs exposed and consumed, the auth or guard pattern, the
  error envelope, and the conventions a change must respect.
- Read the repo's own `AGENTS.md` / `CLAUDE.md` / `.cursor/rules` first.
- **Never write or edit the marker line** `<!-- maestro-codebase-map commit=… updated=… -->`.
  A tool stamps it after you write: `codebase_scan.py record` in Maestro, `./scripts/index
  stamp <name>` in the template.

## `docs/provenance.yaml`

Shared by Maestro and the template. Written by `workspace_sync.py record-knowledge` when
Maestro is installed, otherwise by the `workspace-index` skill. Never edit it by hand
otherwise.

```yaml
# Auto-generated index provenance (Maestro + workspace-index). Do not edit manually.
schema_version: 1
indexed_at: "2026-10-08T13:00:00Z"
docs_sha256: "<sha256 of all docs/**/*.md>"   # filled by Maestro record-knowledge
evidence: docs/architecture.md
evidence_sha256: "<sha256 of evidence file>"
repos:
  - name: backend
    path: codebase/backend
    branch: main
    commit: abc1234def5678...
    indexed_at: "2026-10-08T13:00:00Z"
```

## Other folders under `docs/`

Anything else under `docs/` (for example `impact/`, `product/`, `prds/`) is owned by people
or by other steps. These writers leave it alone.
