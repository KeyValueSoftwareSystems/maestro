---
name: feature-impact
description: Assess which repositories an approved feature changes, and whether it changes an interface between repositories, stored data or infrastructure, from the PRD and the codebase maps. Read-only; writes a short structured impact assessment. Front door for /feature-impact.
allowed-tools: Read, Grep, Glob, Write
tags: [sdlc, design]
---

# feature-impact — what the feature touches

A quick, evidence-based read of where an approved feature lands in the code, before any design is
written. It decides nothing about the design; it states the blast radius so the right amount of
design follows. Minutes, not a design pass.

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
4. **When unsure, include** the repository and say why in its line; a missed repository costs more
   than one extra design.
5. **Follow the change scenarios**, when the workspace has them: a scenario whose `when_changing`
   names a file or symbol the feature changes adds every repository its `also_impacts` lands in,
   and its id goes in `scenarios`. Name the `INV-…` rules at risk in the affected repository's
   `change` line.

## Standards

- Every repository named is one the workspace has, spelled as its folder is.
- Evidence over guesses: each line points at the map entry or code that places the change there.
- No design: no endpoints, schemas or approaches — that is the HLD's and LLD's work.
- `scenarios` is optional: the change-scenario ids the feature triggers, or omit it when the
  workspace has none.

## Assessment format

```json
{"schema_version": 1,
 "repos": [{"name": "backend", "change": "store and expose ticket transfers"}],
 "interfaces_change": true,
 "data_migration": true,
 "infrastructure_change": false,
 "scenarios": ["CS-PL-01"],
 "summary": "one line"}
```

## Safety

Read-only. Write only the impact assessment.

## Output contract

Return `impact_summary` (one line: the repositories and any boundary change) and `repos_csv`
(the repository names, comma-separated).
