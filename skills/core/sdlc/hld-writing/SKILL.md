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

Render decisions by `source`. `accepted-proposal`, `chosen-alternative`, `user-answer`, `evidence` (settled by the cited
source), and
`user-raised` are confirmed. State an `assumption` as the chosen direction marked unverified, and
list the risk of it being wrong under Delivery and risks. A `deferred` decision is not settled: a
non-blocking one goes to Open questions and the deferred-question ledger; a blocking one belongs in
the post-check, never in the design body. The confirmed `kind: direction` decision is the shape the
user agreed to; the HLD must not depart from it. Where a decision records a chosen or rejected
alternative, Key decisions names the alternative and why it lost.

## Required HLD shape

Start with one concise level-1 title containing `HLD`, the workflow-supplied feature slug, and
`Status: Ready for review`. Use these exact level-2 headings in this order:

1. `Decision summary`
2. `Context and scope`
3. `Proposed design`
4. `Interfaces`
5. `Key decisions and trade-offs`
6. `Delivery and risks`
7. `Open questions`

When the workspace defines infrastructure (your instructions supply its level: `containers` or
`iac`), add `Infrastructure and operations` right after `Interfaces`. It lists each infrastructure
change the feature makes — deployment and runtime, scaling (with the numbers that meet the
requirement's targets), data stores, messaging, networking, config and secrets, observability,
rollout — one bullet or table row each, or says `None` when the feature changes no infrastructure.
Omit the section when the workspace defines no infrastructure.

Put a Mermaid diagram (` ```mermaid `) in `Proposed design` whenever the feature crosses
repositories or changes infrastructure: components and their owners, the main request and event
flows, and the data stores. Keep it to what this feature touches.

Consult the `architecture-patterns` skill for each pattern you choose, and the infrastructure pack
for each detected platform (`terraform-patterns`, `kubernetes-patterns`, `container-patterns`) when
it is installed. Name the need next to every pattern you add.

Decision summary contains five to eight short bullets. Context states only what the reader needs to
understand the direction; do not repeat the PRD feature inventory. Interfaces lists each call or
event that crosses a repository boundary, one bullet or table row each: the operation or event
name, its owner and caller, whether it is a synchronous call or an asynchronous event, and the data
it carries in words — no field lists. Say `None` when the feature changes no interface between
repositories; a separate contract step defines the listed interfaces in detail. Proposed design names ownership,
boundaries, the main data/control flow, and relevant execution modes. Key decisions put the chosen
direction first, followed by its reason and consequence. Delivery and risks contains only concrete
dependencies, migration, rollout/backout, security, privacy, reliability, performance, or
operational concerns that apply. When the requirement states non-functional targets, the design
must show how it meets each one (the mechanism, not a restatement of the number).

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

## Concision

Use the shortest wording that preserves the complete architectural direction. Remove repetition,
filler, and implementation detail that belongs in the LLD; prefer compact bullets, tables, or a
useful diagram when they improve scanning. There is no word-count target or ceiling. Never omit a
material decision, boundary, interaction, trade-off, risk, or necessary context merely to shorten
the HLD. Correctness and completeness take precedence over length.

## Conditional post-check

After writing, audit the complete direction once. Write the workflow-supplied post-question queue
using the same schema-version-2 contract as the HLD interview. Keep it empty when the design is
consistent and complete. If synthesis exposes a new blocking architectural gap, record only that
gap instead of guessing; the workflow will ask it and rerun this writer.

Write the workflow-supplied open-question ledger with only explicitly deferred LLD questions. It
uses the supplied open-question schema; final entries are `deferred`, never `open` or `resolved`.

## Validate before returning

Run every workflow-supplied validator. Repair deterministic structure, clarity, readability, or
ledger defects inside this call and validate again. Do not report success with a failing artifact.

## Repair mode

When validator feedback is supplied, change only the named defects. Preserve all confirmed
decisions and unrelated prose. Do not turn a narrow repair into a new architecture pass.

## Revision mode

When the workflow supplies reviewer feedback on an existing HLD, apply it as a targeted edit:
change only the sections the feedback affects, keep every other section, confirmed decision and
ID unchanged, and read only the sources the change needs. Do not regenerate the document. If the
feedback needs a new architecture decision that the confirmed decisions cannot settle, do not guess: leave the
document unchanged and report `needs_clarification` as true so the decision is clarified first.

**Resolving review findings.** When your instructions give a reviewer's findings file and a
resolutions path, answer every blocking finding whose status is `open` or `upheld`, and write
`{"schema_version": 1, "resolutions": [{"id", "resolution", "note"}]}`:

- `fixed` — make the targeted edit; the note says what changed;
- `contested` — the finding is wrong; the note gives the evidence (a requirement line, a confirmed
  decision, the code). A finding the reviewer already `upheld` cannot be contested again;
- `escalated` — it needs a person's decision (budget, product trade-off, ownership); the note
  states the decision exactly. Escalate instead of guessing.

## Safety

Write only the workflow-supplied HLD, deferred-question ledger, and post-question queue. Never edit
requirements, decision context, source code, codebase maps, or run state.

## Output contract

Return `hld_summary`: two short sentences stating the chosen direction and affected systems. Never
return document contents. In revision mode also return `needs_clarification`: true only
when the feedback needs an architecture decision that must be clarified first, else false.
