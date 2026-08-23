---
name: prd-interview
description: Clarify product intent before a PRD is written. Summarize maintained project context, confirm the feature goal, propose concise answers for every PRD area, and run a bounded Grill-style interview without scanning application code or drafting the PRD.
allowed-tools: Read, Grep, Glob
tags: [sdlc, requirement]
---

# PRD interview

Build shared understanding before prose. This skill runs in the lead agent's context so the
conversation stays warm; never delegate it to a worker.

## Read boundary

Read only paths explicitly supplied by the workflow, requirement files, explicit references,
root `AGENTS.md` / `CLAUDE.md`, and maintained summaries under `docs/` such as
`architecture.md`, `technical/`, and `functional/`. Never inspect application source, search
parent/home/Desktop directories, or widen the scan because a summary is missing. Say what is
unknown and ask.

## Modes

The served instruction selects one mode:

1. **Project context** — state what the product/system is and who it serves in at most 3 short
   sentences. Do not describe implementation details.
2. **Feature goal** — restate the requested outcome in at most 2 short sentences. Preserve the
   user's wording and scope; do not add capabilities.
3. **Section proposals** — produce one compact proposed answer for each requested PRD area.
   Use confirmed evidence only. Return an empty value when there is no grounded answer.
4. **Interview turn** — for the engine-served area, show the grounded proposal and ask whether
   it is correct. If there is no proposal, ask the smallest question that resolves the area.
   Use the Grill pattern: one decision at a time, recommended answer when grounded, accept,
   modify, or reject. Call `interview-record` only after the answer is clear.

## Interview areas

Cover every area exactly once unless the user corrects it: summary; problem and context; users
and jobs; goals and success signals; non-goals; functional scope; constraints and assumptions;
acceptance criteria; dependencies and risks; priorities and phasing; references. A proposal is
not a fact until the user confirms it.

## Standards

- Do not write or edit `prd.md` during this skill.
- Do not silently assume. Unknown means ask.
- State each idea once. Prefer bullets or one short paragraph.
- Do not ask technical-design questions; those belong to HLD/LLD.
- Do not re-ask an area already confirmed in the engine action.
- Keep the conversation moving; no essays between questions.

## Safety

Read-only. The engine owns durable interview state and writes the confirmed context artifact.

## Output contract

Depending on the served mode, return `project_context`, `feature_goal`, or these section proposal
fields: `problem_context`, `users_jobs`, `goals_success`, `non_goals`, `functional_scope`,
`constraints_assumptions`, `acceptance_criteria`, `dependencies_risks`, `priority_phasing`, and
`references`. Each value is a short scalar, never document contents.
