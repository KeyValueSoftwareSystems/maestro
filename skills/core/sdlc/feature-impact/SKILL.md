---
name: feature-impact
description: Assess which repositories an approved feature changes, whether it changes an interface between repositories, stored data or infrastructure, and list everything it touches (domains, tables, jobs, queues, endpoints and their consumers, rules, change scenarios), from the PRD and the codebase maps. Read-only; writes a structured impact assessment. Front door for /feature-impact.
allowed-tools: Read, Grep, Glob, Write
tags: [sdlc, design]
---

# feature-impact — what the feature touches

An evidence-based read of where an approved feature lands in the code, before any design is
written. It decides nothing about the design; it states the blast radius so the right amount of
design follows, and lists every item the design must then deal with. Most missed work is an item
nobody listed. Minutes, not a design pass.

## Inputs

Your instructions name the approved PRD and the impact assessment path. Read each repository's
codebase map (`docs/codebase-map.md`), the workspace architecture summary when there is one, and
only the source needed to confirm where a behaviour lives. When the workspace has domain rules
and change scenarios (a `## Rules that must never break` section in `docs/functional/<domain>.md`,
or `docs/impact/side-effects.yaml`), read the rules and scenarios of the domains the feature
touches; without them, carry on as usual. Standalone? read the PRD the user names
and write the assessment to a path you choose (and tell the user where).

## Steps

1. **Trace each acceptance criterion** to the repository that must change for it to hold: the
   one that owns the screen, the endpoint, the job or the data. A repository the feature only
   reads from, unchanged, is not in scope.
2. **Name the change** in each repository in one line (what is added or changed, not how).
3. **Flag what crosses a boundary**: an added or changed call or event between repositories, a
   change to stored data's shape (a migration), or an infrastructure change (new queue, bucket,
   service, environment variable owned by an infrastructure repository).
4. **List what it touches**, each item with a one-line `reason` and an `evidence` pointer (the map
   entry, doc section or `file:line` that shows it): the `domains` (a `docs/functional/<domain>.md`
   page name), the `tables` read or written in a new way, the scheduled or background `jobs`, the
   `queues` or topics published or consumed (new or reused), the `endpoints` added, changed or
   newly called, each with its `consumers` (the app screens and clients that call it), the `INV-…`
   `rules` at risk, and the `CS-…` `scenarios` it triggers. Spell each name as the code or docs do;
   the designs are checked against these exact names.
5. **Follow the change scenarios**, when the workspace has them: a scenario whose `when_changing`
   names a file or symbol the feature changes adds every repository its `also_impacts` lands in,
   its id goes in `scenarios`, and its `also_impacts` items and rules go in their lists.
6. **Classify the size.** `minor`: a small, self-contained change a single repository's design can
   carry, with no real design decision left open (a label, a field, a validation, a small
   endpoint). `major`: anything that needs an architecture decision or a cross-repository design
   (a new service or integration, a changed interface, a migration, new infrastructure, several
   repositories changing together). A `minor` feature skips the high-level design, so when unsure
   say `major`.
7. **When unsure, include** the repository or item and say why; a missed one costs more than one
   extra line of design.

## Standards

- Every repository named is one the workspace has, spelled as its folder is.
- Evidence over guesses: each line points at the map entry or code that places the change there.
- No design: no endpoints, schemas or approaches — that is the HLD's and LLD's work.
- Every list is optional: omit one that has nothing in it. `rules` and `scenarios` name only ids the
  domain docs define; `domains` only pages that exist.

## Assessment format

```json
{"schema_version": 2,
 "repos": [{"name": "backend", "change": "store and expose ticket transfers"}],
 "interfaces_change": true,
 "data_migration": true,
 "infrastructure_change": false,
 "size": "major",
 "summary": "one line",
 "domains": [{"name": "tickets", "reason": "transfers are a ticket lifecycle change",
              "evidence": "docs/functional/tickets.md"}],
 "tables": [{"name": "ticket_transfers", "reason": "new table", "evidence": "backend/docs/codebase-map.md#data"}],
 "jobs": [{"name": "transfer-expiry", "reason": "expires pending transfers", "evidence": "backend/jobs/expiry.go:12"}],
 "queues": [{"name": "notify.send", "reason": "reused to tell the recipient",
             "evidence": "backend/notify/send.go:30", "consumers": ["notifier"]}],
 "endpoints": [{"name": "POST /v1/tickets/{id}/transfers", "reason": "new", "evidence": "backend/docs/codebase-map.md#api",
                "consumers": ["web: TicketScreen", "mobile: TicketDetail"]}],
 "rules": [{"id": "INV-TK-01", "reason": "a ticket has one owner at a time", "evidence": "docs/functional/tickets.md"}],
 "scenarios": [{"id": "CS-TK-02", "reason": "changing ticket ownership", "evidence": "docs/impact/side-effects.yaml"}]}
```

## Safety

Read-only. Write only the impact assessment.

## Output contract

Return `impact_summary` (one line: the size, the repositories and any boundary change) and `repos_csv`
(the repository names, comma-separated).
