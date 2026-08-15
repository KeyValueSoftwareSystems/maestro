---
name: plan
description: Produce a concise, decision-focused high-level design (HLD) for a feature. Ground the direction in requirements and the existing system, record only material trade-offs, and write a developer-readable hld.md. Read-only except for the HLD and open-question artifacts. Front door for /plan.
allowed-tools: Read, Grep, Glob, Bash, Write, AskUserQuestion
tags: [sdlc, design, hld]
---

# plan — high-level design

Write the shortest HLD that lets a human confidently approve the architectural direction and lets
downstream LLD and implementation agents continue without rediscovering or re-deciding that
direction. The document explains what changes, why this direction was chosen, how the main parts
interact, and which material risks or questions remain. It is not a transcript of the design process
and it does not contain file-level implementation, API field lists, schemas, or code.

## Inputs and grounding

Your instructions name the requirement folder and artifact paths. Read every requirement file,
related ADRs, and relevant project guidance. Then read each affected repo's maintained
`docs/codebase-map.md` (umbrella: `codebase/<repo>/docs/codebase-map.md`; single repo:
`./docs/codebase-map.md`). Treat the map as the baseline for existing modules, flows, and execution
modes. Inspect source only when a decision depends on detail the map does not establish.

Use the project's established domain terms consistently. If two sources use conflicting terms,
state the ambiguity as an open question instead of alternating between them.

## Process

1. Extract the problem, scope, hard constraints, affected systems, ownership boundaries, and
   decisions an approver or downstream design agent must understand. Do not repeat the PRD's feature
   inventory.
2. Check the proposed direction against every relevant existing execution mode. If a mode is not
   supported, make that an explicit scope constraint.
3. Choose the simplest direction that satisfies the requirements. Discuss alternatives only for a
   material decision with a genuine trade-off; do not invent alternatives to fill a template.
4. Apply the relevance test to every possible detail: include it only when it changes the
   architecture, approval decision, delivery plan, or material risk. Otherwise omit it.
5. Surface unresolved business rules, ownership, security, data, or compatibility decisions in the
   HLD and `open-questions.json`.
6. Edit once for the reader: lead with the decision, remove repeated context and process narration,
   and make every paragraph earn its place.

## HLD shape

Use these core sections in this order:

1. **Decision summary** — five to eight bullets covering the problem, chosen direction, affected
   systems and responsibilities, key constraint, and most important consequence.
2. **Context and scope** — only the current behavior, users, goals, non-goals, and constraints needed
   to understand this design.
3. **Proposed design** — responsibilities, boundaries, and the main data or control flow. Add a
   diagram only when it communicates the flow more clearly than a short paragraph.
4. **Key decisions and trade-offs** — one compact entry per material decision: decision, reason,
   and consequence. Include rejected alternatives only when the choice was real and future readers
   would otherwise revisit it.
5. **Delivery and risks** — only relevant migration, compatibility, rollout/backout, security,
   privacy, reliability, performance, compliance, dependency, or operational concerns. Group
   related concerns; do not create empty subsections.
6. **Open questions** — unresolved questions that could change the approved direction. If none
   remain, say `None`.

The first four sections are always useful. Within **Delivery and risks**, omit concerns that do not
apply; never add `n/a` headings or generic assurances.

## Writing contract

- Write for an engineer or technical approver who will scan before reading deeply.
- Put the conclusion before its supporting detail. Use active voice, short sentences, specific
  nouns and verbs, and one idea per paragraph.
- Prefer bullets for summaries and a table for repeated mappings or decision comparisons. Use prose
  for reasoning that would be distorted by a table.
- Define a domain term once, then use the same term everywhere.
- State concrete behavior and consequences. Delete filler such as "robust", "seamless",
  "scalable", or "follows best practices" unless the document gives a measurable meaning.
- Do not restate the PRD, narrate research, show a checklist, or include code and file touch lists.
- Aim for 700–1,400 words for a normal feature. Complexity can justify more; template completeness
  cannot. Never remove a material decision merely to hit the target.

## Revision mode

Review feedback is an instruction to rewrite the artifact, not content for the artifact. Apply the
feedback silently so the HLD reads as one current design. Do not include revision history, reviewer
commentary, phrases such as "based on feedback", or descriptions of what changed. Keep a rejected
approach only when it remains a useful architectural trade-off.

## Output artifacts

Write:

- the HLD at the requested path; and
- `open-questions.json`, mirroring the HLD's **Open questions** section and conforming to
  `engine/schemas/open-questions.schema.json`. Each question includes why it matters and two to four
  useful options. Validate it with
  `python3 engine/validate_open_questions.py <path>`.

## Open-question loop (standalone only)

In an orchestrated step, write the artifacts and stop; the workflow serves and records answers. In
standalone mode with `AskUserQuestion`, present the open questions together when the interface
permits, including `You decide` and `Skip / defer` choices.

Record picked or custom answers as resolved, `You decide` as a documented assumption, and skipped
answers as deferred. Fold resolved answers into the relevant design section, not into a revision
log. Re-derive the remaining questions and keep the JSON valid until no open questions remain.

## Definition of done

The direction is understandable from the summary; every statement needed for approval is grounded;
the proposed design covers all relevant execution modes; material trade-offs and risks are concrete;
the HLD and question JSON agree; and irrelevant template sections are absent. A downstream LLD agent
can proceed without re-deciding system responsibilities, boundaries, or the chosen direction. Stop
at architectural direction—do not proceed into detailed design or implementation.

## Output contract

Return `hld_path` and `hld_summary` in two or three sentences. In refine mode, return
`refined_summary` as a one-line description for the workflow; do not put that description in the
HLD. Questions live in the artifacts rather than a separate structured output field.
