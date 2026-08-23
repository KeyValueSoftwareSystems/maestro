---
name: prd-interview
description: Clarify product intent before a PRD is written. Summarize maintained project context, confirm the feature goal, generate feature-specific Grill questions, and resolve material behaviour and edge cases without scanning application code or drafting the PRD.
allowed-tools: Read, Grep, Glob, Write, Bash
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
3. **Grill queue** — read prior confirmed decisions when the supplied file exists. Generate the
   next JSON queue at the workflow-supplied artifact path and run the supplied validator. Use an
   empty `questions` array when no material ambiguity remains.
4. **Interview turn** — ask every question served in the current action together. Show each short
   reason and grounded recommendation. Let the user answer naturally, map only clear answers, and
   leave ambiguous items unresolved. Record all clear answers in one batch operation.

## Grill method

Ask about the feature, never the document structure. Derive each question from confirmed context,
requirements, references, revision feedback, and earlier answers.

- Resolve one material decision per question. Use a concrete actor, action, state, or failure
  scenario instead of broad prompts.
- Explain in one short sentence why the answer changes the product.
- Recommend an answer only when evidence supports it. A recommendation is not confirmed until the
  user accepts it.
- Challenge the happy path only through relevant lenses: permissions; lifecycle transitions;
  timing and limits; visible conflict/concurrency; cancellation, retry, and recovery; invalid or
  stale input; notifications and external effects; privacy and visibility; admin overrides;
  migration or compatibility; measurable success; and non-goals.
- Skip irrelevant lenses. Ask fewer questions as clarity increases. Never ask every category just
  to fill a checklist.
- Never repeat a confirmed decision. Never ask “what should this PRD section say?”

The queue JSON has `schema_version: 1` and `questions`. Each question has `id`, `title`,
`question`, `why`, and `proposal`. Keep IDs stable and feature-specific; they are internal and must
not appear in the PRD.

## Standards

- Do not write or edit `prd.md` during this skill.
- Do not silently assume. Unknown means ask.
- State each idea once. Prefer bullets or one short paragraph.
- Do not ask technical-design questions; those belong to HLD/LLD.
- Do not turn PRD headings into questions.
- Do not combine decisions with “and,” nested alternatives, or multiple question marks.
- Keep the conversation moving; no essays between questions.

## Safety

Write only the workflow-supplied question-queue artifact. The engine owns durable interview state
and writes the confirmed context artifact.

## Output contract

Depending on the served mode, return `project_context`, `feature_goal`, or `summary`. Each value is
a short scalar, never document contents.
