---
name: plan-writing
description: Write or narrowly revise a feature's plan — the one design document that says what changes, where and why — from an approved PRD and the brainstorm notes, in the exact major or minor template. Use after the brainstorm, or to apply review feedback to an existing plan.
allowed-tools: Read, Grep, Glob, Write, Bash
tags: [sdlc, design, plan]
---

# Plan writing

Write the shortest plan that lets a person approve the change and lets builders, reviewers and QA
work from it without a second design document. The plan is the only design document: there is no
separate high-level design, per-repository design or API contract.

## Grounding

Read the workflow-supplied PRD, brainstorm notes, decision log, architecture doc and the codebase
maps of the repositories the change touches. Open source only to place a change or confirm a shape.

- **Decisions** come from the brainstorm notes only. Do not add a decision the person did not
  agree to; an open point stays under Risks and open points.
- **Repositories** use the names the project configuration lists. A repository that does not exist
  yet is marked new (`yes` in the table, or `(new)` after its name in a minor header).
- **Acceptance coverage** maps every PRD acceptance criterion (AC-xx) to the repository and
  component that delivers it. Trace no criterion the PRD does not have.
- **Interfaces**: when more than one repository is involved, spell out the exact shapes — method
  and path (or event name), request and response fields with types, error cases and codes, and
  compatibility. Builders and QA read them here; nothing else defines them. One repository with no
  external change: write None.
- Cite the IDs of the business rules, invariants and change scenarios the change relies on or
  changes (e.g. PL-INV-001) where they apply, so later steps load exactly those rows.

## Templates

Use the template for the type your instructions name, exactly: the title, then the header line,
then the body. Replace every `<…>`.

**Major:**

```markdown
# <Feature> — plan
Type: major · Run: <slug> · PRD: <PRD path> · Status: active

## Summary
<2-4 lines: what changes and why>

## Decisions
- <decision> — <reason> — rejected: <alternative>

## Repositories
| repo | role in this change | new? |
|---|---|---|
| <repo> | <role> | no |

## Design
<per repository: modules or components touched, data model and migrations, key logic>

## Interfaces
<endpoint or event, request and response, errors, compatibility — or None>

## Infrastructure
<queues, config, deploy changes — or None>

## Risks and open points
<one line each — or None>

## Acceptance coverage
- AC-01 -> <repo> / <component>

## Out of scope
<what this change does not do>
```

Every section is present and non-empty; write None where nothing applies.

**Minor** — five to ten non-blank lines after the title, nothing else:

```markdown
# <Feature> — plan
Type: minor · Run: <slug> · Repositories: <repo>, <repo>
- Change: <what changes>
- Where: <module or file>
- Interface: <None, or the exact shape>
- Data: <None, or the change>
- Tests: <what proves it, by AC-xx>
- Risk: <the main risk, or None>
```

## Revision

When the workflow passes feedback on an existing plan, apply only that feedback as a targeted
edit: keep every other line, decision, repository and AC mapping unchanged. Do not rewrite the
plan, re-run the brainstorm or reopen a decision the feedback does not touch.

## Standalone use

When a person invokes this skill directly, their message is the whole brief: take the feature,
the PRD or requirement and the type from it, and write the plan to a sensible path you choose (and
tell the person where).

## Standards

- Plain, skimmable technical English; the shortest wording that keeps every decision and shape.
- No task lists, no code, no restating the PRD.
- Run the validator the workflow names and fix every issue it reports before completing.

## Safety

Write only the plan file. Never write code, the PRD, the brainstorm notes or decision records.

## Output contract

Return `summary`: one plain sentence saying what the plan changes and in which repositories.
The person reads `summary` as it is: write it as one plain sentence of the outcome, with no ids,
file paths or jargon; technical detail stays in the artifact.
