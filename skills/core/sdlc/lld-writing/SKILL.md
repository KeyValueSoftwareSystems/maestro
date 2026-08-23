---
name: lld-writing
description: Write or narrowly repair one buildable repository LLD from an approved HLD, confirmed repo decisions, and bounded code evidence in concise, skimmable technical English.
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
4. `Interfaces, state, and flows`
5. `Failure and operational behavior`
6. `Implementation sequence`
7. `Verification`

Change summary has four to seven short bullets. Existing seam identifies the current entry point,
responsible modules, conventions, and constraints with compact backticked path evidence. Proposed
changes maps areas to responsibilities and explains only non-obvious choices. Interfaces, state, and
flows defines precise local and cross-repo behavior, validation, ownership, ordering, and relevant
data shapes without code listings. Failure and operational behavior covers only applicable error,
retry, concurrency, security, privacy, performance, observability, rollout, and backout decisions.
Implementation sequence is a dependency-ordered numbered list of verifiable increments, not a file
inventory. Verification maps behavior to the highest stable existing test seams.

All blocking implementation decisions must be resolved before this document. Never write `TBD`,
`TODO`, "decide later", or an open-questions section.

## Plain technical English

- Put the concrete change before its reason.
- Use active voice, short sentences, and repository terms found in code.
- Keep one idea per sentence and one topic per paragraph.
- Prefer tables for module mappings and contracts; use prose only for reasoning.
- Avoid filler, repeated HLD context, decorative adjectives, revision history, and generic claims.
- Use a diagram only when ordering cannot be understood from a short numbered flow.

Target 800–1,600 words and no more than 70% of each validator ceiling on the first write.

## Conditional post-check

After writing, audit the connected design once. Write the supplied schema-version-2 post-question
queue empty when the LLD is complete. If synthesis exposes a genuinely new blocking repo gap, put
only that gap in the queue instead of guessing; the workflow asks it and reruns this writer.

## Contract notes

Return concise `contract_notes` only for facts another repository or the shared contract must
reconcile: an exposed/consumed operation, event, token, error, compatibility rule, or ordering
constraint. Use `None` when this repo adds no cross-repo contract fact.

## Validate and repair

Run every supplied validator. Repair deterministic structure, brevity, readability, or post-queue
defects inside the same call and validate again. In repair mode, change only named defects and
preserve all confirmed decisions and unrelated prose.

## Safety

Write only the supplied LLD and post-question queue. Never edit source, parent artifacts, codebase
maps, decision context, or state.

## Output contract

Return `lld_path` and `contract_notes`; never return document text.
