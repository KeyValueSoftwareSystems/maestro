---
name: feature-impact
description: Assess which repositories an approved feature changes, record the design facts (how the interface between repositories and stored data change, infrastructure, older clients, the architecture questions still open), and list everything it touches (domains, tables, jobs, queues, endpoints and their consumers, rules, change scenarios), from the PRD and the codebase maps. Read-only; writes a structured impact assessment. Front door for /feature-impact.
allowed-tools: Read, Grep, Glob, Write
tags: [sdlc, design]
---

# feature-impact — what the feature touches

An evidence-based read of where an approved feature lands in the code, before any design is
written. It decides nothing about the design and gives no verdict on its size; it states the
facts the right amount of design follows from, and lists every item the design must then deal with. Most missed work is an item
nobody listed. Minutes, not a design pass.

## Inputs

Your instructions name the approved PRD and the impact assessment path. Read each repository's
codebase map (`docs/codebase-maps/<name>.md`), the workspace architecture summary when there is one, and
only the source needed to confirm where a behaviour lives. When the workspace has invariants
and change scenarios (the `## Invariants and consistency` and `## Change scenarios` sections of
`docs/technical/<domain>.md`, or `docs/impact/side-effects.yaml`), read those of the domains the
feature touches; without them, carry on as usual. Standalone? read the PRD the user names
and write the assessment to a path you choose (and tell the user where).

## Steps

1. **Trace each acceptance criterion** to the repository that must change for it to hold: the
   one that owns the screen, the endpoint, the job or the data. A repository the feature only
   reads from, unchanged, is not in scope.
2. **Name the change** in each repository in one line (what is added or changed, not how).
3. **Say what crosses a boundary**, as facts:
   - `interface_change` — `none`: no call or event between repositories changes. `lockstep`:
     several repositories change together but the wire format stays the same — same endpoints and
     events, same field names, types, required fields and enum members; a validation rule (length,
     range, pattern) or a behaviour behind the interface may change. `shape`: an endpoint, event,
     field or enum member is added, changed or removed.
   - `data_change` — `none`; `additive` (a nullable column, an optional field, nothing to
     backfill); `reshape` (a new entity or table, a type or key change, a backfill).
   - `infrastructure_change` — a new queue, bucket, service, or an environment variable owned by
     an infrastructure repository.
   - `compatibility_risk` — clients already deployed (old app versions, other teams' consumers)
     break if the repositories ship in the wrong order.
4. **List what it touches**, each item with a one-line `reason` and an `evidence` pointer (the map
   entry, doc section or `file:line` that shows it): the `domains` (a `docs/technical/<domain>.md` or
   `docs/functional/<domain>.md` page name), the `tables` read or written in a new way, the scheduled
   or background `jobs`, the `queues` or topics published or consumed (new or reused), the
   `endpoints` added, changed or newly called, each with its `consumers` (the app screens and
   clients that call it), the `<PREFIX>-INV-NNN` `rules` at risk, and the `<PREFIX>-CS-NNN`
   `scenarios` it triggers. Spell each name as the code or docs do; the designs are checked against
   these exact names.
5. **Follow the change scenarios**, when the workspace has them: a scenario whose `when_changing`
   names a file or symbol the feature changes adds every repository its `also_impacts` lands in,
   its id goes in `scenarios`, and its `also_impacts` items and invariants (`<PREFIX>-INV-NNN`) go in
   their lists.
6. **List the open decisions** — the questions the PRD and the code leave open — each with a
   `kind`, a one-line `question` and its `evidence`. An architecture document answers these kinds:
   - `placement` — which repository or service owns a new behaviour or data;
   - `integration` — a new service or third party, or how two parts talk (sync or async, push or pull);
   - `data-model` — a new entity, its ownership, or how data stays consistent across stores;
   - `interface` — the shape of a new or changed contract between repositories;
   - `quality` — a non-functional target (latency, scale, security) the current design does not
     already meet.
   A detailed per-repository plan answers these:
   - `rollout` — the order repositories ship in, old clients, a feature flag;
   - `detail` — a choice inside one repository (a library, a component, an error message).
   Do not turn an answered point into a question: when the PRD, the code or the docs already settle
   it, it is not open. When unsure whether an architecture question is open, list it with its kind.
   Give no size or verdict: how much design follows is decided from these facts, and how
   many repositories change is not one of them.

   Two examples. Shortening a one-time password from 5 to 4 digits: the backend generates it, web
   and mobile render the input boxes — `interface_change: lockstep` (still a string field, only its
   length rule changes), `data_change: none`, `compatibility_risk: true` (old app builds still show
   5 boxes), `open_decisions: [{kind: rollout, question: "Ship web and mobile before the backend
   switches to 4 digits?"}]`. Adding an enum member a client must render: `interface_change: shape`.
7. **When unsure, include** the repository or item and say why; a missed one costs more than one
   extra line of design.

## Standards

- Every repository named is one the workspace has, spelled as its folder is.
- Evidence over guesses: each line points at the map entry or code that places the change there.
- No design: no endpoints, schemas or approaches — that is the HLD's and LLD's work.
- The design facts (`interface_change`, `data_change`, `infrastructure_change`,
  `compatibility_risk`, `open_decisions`) are always present; `open_decisions` may be empty.
- Every item list is optional: omit one that has nothing in it. `rules` and `scenarios` name only ids the
  domain docs define; `domains` only pages that exist.

## Assessment format

```json
{"schema_version": 3,
 "repos": [{"name": "backend", "change": "store and expose ticket transfers"},
           {"name": "web", "change": "transfer screen"}],
 "interface_change": "shape",
 "data_change": "reshape",
 "infrastructure_change": false,
 "compatibility_risk": false,
 "open_decisions": [{"kind": "data-model", "question": "Does a pending transfer own the ticket or only reserve it?",
                     "evidence": "docs/technical/tickets.md#invariants-and-consistency"},
                    {"kind": "rollout", "question": "Ship the backend before the transfer screen?",
                     "evidence": "PRD AC-03"}],
 "summary": "one line",
 "domains": [{"name": "tickets", "reason": "transfers are a ticket lifecycle change",
              "evidence": "docs/technical/tickets.md"}],
 "tables": [{"name": "ticket_transfers", "reason": "new table", "evidence": "backend/docs/codebase-map.md#data"}],
 "jobs": [{"name": "transfer-expiry", "reason": "expires pending transfers", "evidence": "backend/jobs/expiry.go:12"}],
 "queues": [{"name": "notify.send", "reason": "reused to tell the recipient",
             "evidence": "backend/notify/send.go:30", "consumers": ["notifier"]}],
 "endpoints": [{"name": "POST /v1/tickets/{id}/transfers", "reason": "new", "evidence": "backend/docs/codebase-map.md#api",
                "consumers": ["web: TicketScreen", "mobile: TicketDetail"]}],
 "rules": [{"id": "TK-INV-001", "reason": "a ticket has one owner at a time", "evidence": "docs/technical/tickets.md"}],
 "scenarios": [{"id": "TK-CS-002", "reason": "changing ticket ownership", "evidence": "docs/impact/side-effects.yaml"}]}
```

## Safety

Read-only. Write only the impact assessment.

## Output contract

Return `impact_summary` (one line: the repositories, any boundary change and how many architecture
questions are open) and `repos_csv`
(the repository names, comma-separated).
