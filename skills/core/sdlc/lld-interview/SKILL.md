---
name: lld-interview
description: Clarify only material repository implementation decisions before one repo LLD is written. Audit existing answers, inspect the bounded implementation seam, and ask feature-specific questions in grouped native popups.
allowed-tools: Read, Grep, Glob, Write, Bash
tags: [sdlc, design, lld]
---

# LLD interview

Resolve decisions that a developer cannot safely infer from the approved HLD and repository evidence.
This runs in the lead agent so the grouped conversation and subsequent LLD write share one context.

## Read boundary

Read the approved parent HLD, its deferred-question ledger, confirmed LLD decisions, repository
guidance, the maintained codebase map, relevant manifest, and only source/tests around the seam this
feature changes. Start from paths named by the map. Do not scan the whole repository or another repo.

## Decide from evidence before asking

Do not ask the user to choose a normal implementation detail when the repository already has a clear
convention. Record no question for choices the writer can safely make from code evidence. Ask only an
unresolved decision that materially changes correctness, compatibility, or the implementation seam:

- which existing module or extension seam owns ambiguous behavior;
- local state authority, lifecycle, validation, or migration where the HLD leaves alternatives;
- this repo's precise side of an API, event, navigation, storage, or background-work boundary;
- for an API-producing backend, unresolved persistence ownership or client-contract facts: entity
  relationships, destructive behavior, route/operation shape, complete DTOs, authorization, stable
  errors, pagination, time/enum representation, idempotency, refresh and shared-contract ownership;
- visible error, retry, concurrency, idempotency, offline, or recovery behavior;
- authorization, privacy, sensitive-data handling, or trust-boundary enforcement;
- backward compatibility, rollout, backout, or support for relevant execution modes;
- a verification seam when materially different choices change testability or delivery risk.

Do not reopen PRD or HLD decisions. Do not ask for filenames, class names, boilerplate, library syntax,
task estimates, styling preferences, or facts directly discoverable from source. Do not ask a
frontend developer to rediscover a backend payload later: resolve material client-visible ambiguity
before writing. Recommend the simplest option that follows current repository patterns.

## Answer audit

- Check every saved answer against its `must_resolve` facts and against code/HLD constraints.
- For `source: user-answer`, only `answer` is confirmed; proposal text is not.
- Follow up only on the missing or contradictory fact, using a new stable ID.
- A blocking repo decision cannot be deferred. An implementation detail with a safe existing
  convention should be decided by the writer, not sent back to the user.

## Queue contract

Write the supplied queue as schema version 2. Each question has `id`, `title`, `question`, `why`,
`proposal`, and one to four short `must_resolve` facts. Use 3–7 questions when several material gaps
remain and fewer when nearly clear. An empty queue requires empty `audit.unresolved` and
`audit.contradictions`. Run the supplied validator before completing.

## Presentation

Use only the workflow's native grouped popup. If the host limits popup size, collect consecutive
chunks without analyzing or writing between them, then record the complete round atomically. Never
fall back to ordinary chat.

## Safety

Write only the workflow-supplied question queue. Never edit the LLD, source, parent artifacts, or
state.

## Output contract

Return `summary`: one short sentence describing the queue or confirming the repo is clear.
