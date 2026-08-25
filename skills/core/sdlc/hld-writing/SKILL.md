---
name: hld-writing
description: Write or narrowly repair one decision-focused HLD from an approved PRD, maintained architecture context, and confirmed technical decisions in plain, skimmable technical English.
allowed-tools: Read, Grep, Glob, Write, Bash
tags: [sdlc, design, hld]
---

# HLD writing

Write the shortest high-level design that lets an approver accept the architectural direction and
lets LLD authors continue without rediscovering system responsibilities or major trade-offs. This
is architecture synthesis, not brainstorming and not detailed implementation design.

## Grounding

Read the workflow-supplied requirements, confirmed architecture decisions, maintained codebase
maps, relevant project guidance, and only the source details needed to close a gap in those maps.
The approved PRD owns product behavior. The decision artifact owns clarified architecture choices.

For `source: user-answer`, use only the stored `answer`; never complete it from proposal text. Stop
instead of writing if a blocking `must_resolve` fact is absent or confirmed decisions conflict.

## Required HLD shape

Start with one concise level-1 title containing `HLD`, the workflow-supplied feature slug, and
`Status: Ready for review`. Use these exact level-2 headings in this order:

1. `Decision summary`
2. `Context and scope`
3. `Proposed design`
4. `Key decisions and trade-offs`
5. `Delivery and risks`
6. `Open questions`

Decision summary contains five to eight short bullets. Context states only what the reader needs to
understand the direction; do not repeat the PRD feature inventory. Proposed design names ownership,
boundaries, the main data/control flow, and relevant execution modes. Key decisions put the chosen
direction first, followed by its reason and consequence. Delivery and risks contains only concrete
dependencies, migration, rollout/backout, security, privacy, reliability, performance, or
operational concerns that apply.

Open questions says `None` when nothing is explicitly deferred. If the user deliberately deferred
a non-blocking choice to LLD, list it briefly and mirror it in the workflow-supplied deferred-question
ledger. Resolved questions belong in the design body, not in this section.

## High-level boundary

Include responsibilities, domain ownership, major state, trust boundaries, system interactions,
failure strategy, and material trade-offs. Exclude endpoint field lists, complete schemas, table
columns, class or file touch lists, library-specific code, and implementation task sequences. Those
belong to LLD.

## Plain technical English

- Put the decision before its explanation.
- Use active voice, short sentences, and concrete nouns and verbs.
- Keep one idea per sentence and one topic per paragraph.
- Prefer bullets for summaries and repeated facts; use prose for reasoning.
- Define a necessary term once and use it consistently.
- Avoid decorative words such as `robust`, `seamless`, `scalable`, `leverage`, and `facilitate`
  unless followed by a measurable meaning.
- Do not narrate research, restate the same decision, add filler, or include a revision log.
- Add a diagram only when it makes a multi-system flow clearer than short prose.

## Size targets

The workflow validator supplies hard ceilings. Target no more than 70% of each ceiling on the first
write. A normal HLD should remain roughly 700–1,400 words; complexity may justify less or more, but
template completion does not.

## Conditional post-check

After writing, audit the complete direction once. Write the workflow-supplied post-question queue
using the same schema-version-2 contract as the HLD interview. Keep it empty when the design is
consistent and complete. If synthesis exposes a new blocking architectural gap, record only that
gap instead of guessing; the workflow will ask it and rerun this writer.

Write the workflow-supplied open-question ledger with only explicitly deferred LLD questions. It
uses the supplied open-question schema; final entries are `deferred`, never `open` or `resolved`.

## Validate before returning

Run every workflow-supplied validator. Repair deterministic structure, brevity, readability, or
ledger defects inside this call and validate again. Do not report success with a failing artifact.

## Repair mode

When validator feedback is supplied, change only the named defects. Preserve all confirmed
decisions and unrelated prose. Do not turn a narrow repair into a new architecture pass.

## Safety

Write only the workflow-supplied HLD, deferred-question ledger, and post-question queue. Never edit
requirements, decision context, source code, codebase maps, or run state.

## Output contract

Return `hld_summary`: two short sentences stating the chosen direction and affected systems. Never
return document contents.
