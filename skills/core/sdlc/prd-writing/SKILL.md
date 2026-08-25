---
name: prd-writing
description: Write or repair one final PRD from fully confirmed structured context in plain, skimmable technical English. Use only after the PRD interview is complete; never invent missing product decisions.
allowed-tools: Read, Write, Bash
tags: [sdlc, requirement]
---

# PRD writing

Turn the confirmed product inputs and decisions into the final PRD. This is a rendering step, not another
brainstorm. Write once in normal operation; repair only when deterministic validation names a
specific defect.

## Source of truth

Read the confirmed inputs and requirement paths supplied by the workflow. When the cumulative
decision artifact exists, its answers are authoritative; when it does not, no extra interview
decisions were needed. Do not scan the repository, reopen product decisions, add plausible
features, or infer technical design. If a required answer is absent, stop instead of filling space.

For a decision whose `source` is `user-answer`, use only its `answer`. Its unaccepted `proposal` is
context, not permission to complete a partial answer. Stop without writing if a `must_resolve` fact
is absent, a material value remains vague, or two confirmed decisions conflict.

## Required structure

Start with this compact document header:

```markdown
# <Concise feature name> — PRD

**Feature slug:** `<workflow-supplied slug>`
**Status:** Ready for review
```

Derive the feature name from the confirmed goal without adding scope. Do not add revision history,
decision IDs, authors, or decorative metadata.

Use these exact level-2 headings in this order:

1. `Summary`
2. `Problem and context`
3. `Users and jobs`
4. `Goals and success signals`
5. `Non-goals`
6. `Functional scope`
7. `Constraints and assumptions`
8. `Acceptance criteria`
9. `Dependencies and risks`
10. `Priorities and phasing`
11. `References`

Use identifiers only in `Acceptance criteria`. Write every criterion as a sequential observable
bullet beginning `AC-01:`, `AC-02:`, and so on. Do not put `B1`, `B2`, `FR-*`, `REQ-*`, question
IDs, or other traceability codes in any other section.

Before adding prose, create all eleven headings in the required order. Before completing, check
that every in-scope actor permission, state transition, limit, conflict, override, and recovery rule
from the confirmed decisions has an observable acceptance criterion. Non-goals do not need one.

## Plain technical English

- Put the decision or idea first.
- One idea per sentence; one topic per paragraph.
- Prefer short bullets for scope, non-goals, risks, and acceptance criteria.
- Use active voice and name who does what.
- Use concrete words. Avoid `leverage`, `facilitate`, `robust`, `seamless`, `ecosystem`, and
  other decorative language.
- Define a necessary technical term once. Cut terms the product reader does not need.
- Preserve the user's meaning and terminology.
- State each idea once. No recap paragraphs, filler, marketing claims, or repeated rationale.
- Expand only when precision would otherwise be lost.

## Word budgets

Summary: 120 words. Problem, users, goals, constraints, dependencies: 180 each. Non-goals,
priorities: 140 each. Functional scope: 300. Acceptance criteria: 260. References: 160. Whole
document: 1,800 words maximum. These are ceilings, not targets. Target no more than 70% of each
section ceiling on the first write so small edits cannot trigger a repair.

## Validate before returning

Run the workflow-supplied validator after writing. Allow its mechanical-fix mode to normalize line
wrapping and acceptance-criteria numbering. If it still reports a defect, repair only that defect
inside this same call and validate again. Do not return success with a failing artifact.

## Repair mode

When the workflow supplies validator feedback, change only the named defects. Do not rewrite
unrelated sections or make the document longer unless the missing precision requires it. Preserve
existing acceptance-criteria IDs when their meaning is unchanged; otherwise restore one unique,
gap-free `AC-01` sequence.

## Safety

Write only the workflow-supplied PRD artifact. Never edit requirements, confirmed context, code,
or run state.

## Output contract

Return `summary`: one short sentence stating that the final PRD was written or which validator
defects were repaired.
