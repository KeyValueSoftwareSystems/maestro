---
name: lld-writing
description: Write or narrowly repair one buildable repository LLD from an approved HLD, confirmed repo decisions, and bounded code evidence, including an implementation-complete data model and a frontend-ready API/client contract in concise, skimmable technical English.
allowed-tools: Read, Grep, Glob, Write, Bash
tags: [sdlc, design, lld]
---

# LLD writing

Write the shortest implementation design that lets a developer build this repository's part without
rediscovering the seam or making correctness decisions. This is one repo's design, not architecture
brainstorming, another repo's design, a task dump, or implementation.

## Grounding

Read the approved parent HLD, confirmed LLD decisions, repository guidance, maintained codebase map,
relevant manifest, and the source/tests around the affected seam. Reuse files already inspected in
this lead session. Explore further only when a named design fact cannot be grounded otherwise.

Preserve PRD/HLD decisions. For `source: user-answer`, use only the stored answer. Stop rather than
guess if a blocking `must_resolve` fact remains absent or decisions conflict.

## Required document shape

Start with one concise level-1 title containing `LLD`, then these metadata lines:

- `**Parent feature:**` with the parent slug
- `**Repository:**` with the exact repository name
- `**Status:** Ready for review`

Use these exact level-2 headings in order:

1. `Change summary`
2. `Existing seam`
3. `Proposed changes`
4. `Data model and migrations`
5. `API and client contract`
6. `State and flows`
7. `Failure and operational behavior`
8. `Implementation sequence`
9. `Verification`

Change summary has four to seven short bullets. Existing seam identifies the current entry point,
responsible modules, conventions, and constraints with compact backticked path evidence. Proposed
changes maps areas to responsibilities and explains only non-obvious choices.

Data model and migrations is implementation-complete for every repository-owned store. Use compact
tables to define every changed entity, field type, nullability, default, primary/foreign key and
delete action; enumerate enum values, unique/check/exclusion constraints, indexes and the query each
index serves. State migration order, required extensions, compatibility/backfill behavior and safe
backout. If persistence does not change, write exactly `No repository-owned persistence change.`

API and client contract is the handoff between producers and consumers. For a backend or other API
producer, make it sufficient for frontend implementation without reading backend source or guessing
a field. Include:

- every added or changed operation with method/path or protocol operation, actor, authorization and
  purpose;
- all path, query, header and body inputs with type, required/null/default rules and validation;
- success status and the complete response shape with field types, nullability, enum values, units,
  timestamp/time-zone format, ordering and pagination;
- every expected failure with transport status, stable error code, trigger and required client
  reaction, including retry/refetch and idempotency behavior;
- cache invalidation, polling/realtime behavior, compatibility/versioning and feature-flag behavior
  when they affect a client; and
- a `### Frontend handoff` subsection naming the exact shared contract/schema/type location, its
  owner, and enough canonical fixtures or examples for a client to start before the backend lands.

For a client repository, define the same contract from the consumer side and name the generated or
shared source it trusts. If there is no externally consumed interface change, write exactly
`No externally consumed interface change.` Do not hide a required contract behind "existing
conventions"; restate every changed shape in this LLD.

State and flows defines ownership, lifecycle transitions, validation order, transactions,
concurrency and cross-repo ordering without implementation code. Failure and operational behavior
covers only applicable retry, security, privacy, performance, observability, rollout and backout
decisions not already fixed by the API error contract. Implementation sequence is a dependency-
ordered numbered list of verifiable increments, not a file inventory. Verification maps schema,
contract and behavior to the highest stable existing test seams, including contract tests that let
clients work independently.

All blocking implementation decisions must be resolved before this document. Never write `TBD`,
`TODO`, "decide later", or an open-questions section.

## Plain technical English

- Put the concrete change before its reason.
- Use active voice, short sentences, and repository terms found in code.
- Keep one idea per sentence and one topic per paragraph.
- Prefer tables for module mappings and contracts; use prose only for reasoning.
- Avoid filler, repeated HLD context, decorative adjectives, revision history, and generic claims.
- Use a diagram only when ordering cannot be understood from a short numbered flow.

Target 1,200–2,200 words and no more than 70% of each validator ceiling on the first write. Prefer
dense contract tables over explanatory prose; completeness means no missing decisions, not more
sentences.

## Conditional post-check

After writing, audit the connected design once. Write the supplied schema-version-2 post-question
queue empty when the LLD is complete. If synthesis exposes a genuinely new blocking repo gap, put
only that gap in the queue instead of guessing; the workflow asks it and reruns this writer.

## Contract notes

Return concise `contract_notes` only for facts another repository or the shared contract must
reconcile: an exposed/consumed operation, DTO, event, token, stable error, compatibility rule, or
ordering constraint. For an API producer, include every added or changed client-facing operation;
use `None` only when this repo truly adds no cross-repo contract fact.

## Validate and repair

Run every supplied validator. Repair deterministic structure, brevity, readability, or post-queue
defects inside the same call and validate again. In repair mode, change only named defects and
preserve all confirmed decisions and unrelated prose.

## Safety

Write only the supplied LLD and post-question queue. Never edit source, parent artifacts, codebase
maps, decision context, or state.

## Output contract

Return `lld_path` and `contract_notes`; never return document text.
