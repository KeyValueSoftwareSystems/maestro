---
name: hld-interview
description: Clarify material architecture decisions before an HLD is finalized. Generate feature-specific technical Grill questions, audit prior answers and contradictions, and collect grouped answers without drafting design prose.
allowed-tools: Read, Grep, Glob, Write, Bash
tags: [sdlc, design, hld]
---

# HLD interview

Resolve architectural direction before prose. This skill runs in the lead agent's context so
questions remain connected to the approved product decisions; never delegate the conversation.
The one exception is discussing a single question the user is unsure about: that runs in an
isolated discussion agent or a side chat, under this skill's read boundary and design-conversation
rules, so its reading never fills the lead's context.

## Read boundary

Read only workflow-supplied requirements, decision artifacts, revision feedback, project guidance,
maintained codebase maps, and source files whose detail is necessary for a material decision the
maps do not settle. Do not scan application source broadly or search outside the repository.

## Architecture Grill

Ask only decisions that change the approved direction or what a downstream LLD must respect:

- system and repository ownership;
- service, module, and trust boundaries;
- source of truth and major data lifecycle;
- cross-repository control or data flow;
- authentication, authorization, privacy, and sensitive-data exposure;
- failure, recovery, idempotency, concurrency, and relevant execution modes;
- compatibility, migration, rollout, backout, and material operational trade-offs.

Do not ask about PRD scope already settled. Do not ask for endpoint fields, table columns, class or
file names, library syntax, task breakdowns, or other LLD choices. Recommend the simplest direction
grounded in the approved requirement and existing architecture.

## Design conversation

Architecture is decided with the user, not announced to them.

- For every genuine trade-off, offer the recommendation plus up to two real `alternatives`
  (`{label, tradeoff}`) with their concrete consequences — cost, coupling, failure behavior,
  migration risk. Never invent a straw option to make the recommendation look good.
- When no other gap remains, ask one `kind: "direction"` question. Its `proposal` (up to 150 words)
  summarises the intended architecture — owners, boundaries, main flow, and the key trade-offs
  taken — so the user confirms, challenges, or discusses the whole shape before prose is written.
  The queue cannot close until the latest direction is confirmed after every other decision; ask a
  fresh direction (new ID) whenever later answers change it.
- When the user is unsure or asks back, explain the reasoning, compare options, and answer from
  the requirements, maintained maps, and the specific source that settles it. Say what you
  checked. If a fact belongs to someone else, offer a working assumption or deferral.
- Invite the user's own concerns; treat a `user-raised` point as a constraint to reconcile.

## Answer audit

A saved answer is not automatically complete.

- Compare it with every `must_resolve` fact attached to its question.
- For `source: user-answer`, treat only `answer` as confirmed; unaccepted proposal text is not a
  decision. `chosen-alternative` and `accepted-proposal` are confirmed; `assumption` is a working
  answer to flag as unverified; `deferred` settles nothing; `user-raised` is the user's own input.
  Build on a `discussion` summary instead of re-asking what was explored.
- A deferred blocking decision must be re-asked with sharper options; a deferred non-blocking one
  goes to LLD.
- Compare decisions for conflicting ownership, authority, state boundaries, timing, failure
  behavior, or execution-mode assumptions.
- Follow up only on the missing or conflicting fact and use a new stable ID.
- Treat concrete product rules from the PRD as constraints, not questions to reopen.
- A user may explicitly defer a non-blocking implementation choice to LLD. Preserve that answer;
  never describe a blocking architectural decision as safe to defer.

## Queue contract

Write the workflow-supplied queue as `schema_version: 2` with `questions` and `audit`. Each question
has `id`, `title`, `question`, `why`, `proposal`, and one to four short `must_resolve` facts; it may
add `alternatives` and `kind` (`decision` by default, or `direction`).
`audit.unresolved` and `audit.contradictions` name why another round exists. Both arrays are empty
only when the queue is empty and the architecture is clear enough to write. Run the supplied
validator before completing.

## Interview presentation

When the workflow serves a question batch, collect it through the requested native popup. If the
host limits questions per popup, collect consecutive chunks without analyzing or recording between
them. Then discuss the items the user was unsure about or asked about, take any point they raise,
and record the complete round atomically.

## Standards

- One material decision per question; one question mark.
- State why it matters in one short sentence.
- Prefer a concrete recommendation with real alternatives over an abstract menu.
- Never ask questions derived from HLD headings.
- Never draft or edit the HLD in this skill.
- Keep each turn short and let the user steer; no essays between rounds.

When the workflow supplies validator feedback naming defects in an existing queue, fix only those
defects in that file and validate again; do not rebuild the queue or re-read sources.

## Safety

Write only the workflow-supplied question queue. The engine owns durable interview state and the
cumulative decision artifact.

## Output contract

Return `summary`: one short sentence describing the prepared architecture question queue or that
the architecture audit is clear.
