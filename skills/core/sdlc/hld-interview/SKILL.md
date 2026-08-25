---
name: hld-interview
description: Clarify material architecture decisions before an HLD is finalized. Generate feature-specific technical Grill questions, audit prior answers and contradictions, and collect grouped answers without drafting design prose.
allowed-tools: Read, Grep, Glob, Write, Bash
tags: [sdlc, design, hld]
---

# HLD interview

Resolve architectural direction before prose. This skill runs in the lead agent's context so
questions remain connected to the approved product decisions; never delegate the conversation.

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

## Answer audit

A saved answer is not automatically complete.

- Compare it with every `must_resolve` fact attached to its question.
- For `source: user-answer`, treat only `answer` as confirmed; unaccepted proposal text is not a
  decision.
- Compare decisions for conflicting ownership, authority, state boundaries, timing, failure
  behavior, or execution-mode assumptions.
- Follow up only on the missing or conflicting fact and use a new stable ID.
- Treat concrete product rules from the PRD as constraints, not questions to reopen.
- A user may explicitly defer a non-blocking implementation choice to LLD. Preserve that answer;
  never describe a blocking architectural decision as safe to defer.

## Queue contract

Write the workflow-supplied queue as `schema_version: 2` with `questions` and `audit`. Each question
has `id`, `title`, `question`, `why`, `proposal`, and one to four short `must_resolve` facts.
`audit.unresolved` and `audit.contradictions` name why another round exists. Both arrays are empty
only when the queue is empty and the architecture is clear enough to write. Run the supplied
validator before completing.

## Interview presentation

When the workflow serves a question batch, use only the requested native popup. If the host limits
questions per popup, collect consecutive chunks without analyzing or recording between them, then
record the complete round atomically. Do not fall back to ordinary chat.

## Standards

- One material decision per question; one question mark.
- State why it matters in one short sentence.
- Prefer a concrete recommendation over an abstract menu.
- Never ask questions derived from HLD headings.
- Never draft or edit the HLD in this skill.
- Keep the exchange short; no essays between rounds.

## Safety

Write only the workflow-supplied question queue. The engine owns durable interview state and the
cumulative decision artifact.

## Output contract

Return `summary`: one short sentence describing the prepared architecture question queue or that
the architecture audit is clear.
