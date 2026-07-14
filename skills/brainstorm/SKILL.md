---
name: brainstorm
description: Elicit a feature requirement from a thin seed — draft an initial requirement doc and enumerate the essential unknowns as answerable questions, then fold the human's answers back in. The front half of design when no PRD exists. Writes only the requirement doc + its questions file. Front door for /brainstorm.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, requirement]
---

# brainstorm — turn an idea into a requirement

Given only a one-line feature idea (and maybe a few scattered notes), produce a written
**requirement** good enough to design an HLD from — by drafting what you can and asking the
human, one question at a time, for everything you can't responsibly assume. This is the
*requirement*, not the design: capture the problem, users, scope, and constraints — do not
design APIs, schemas, or architecture (that is the HLD's job, downstream).

You run in one of two modes; your instructions say which:

- **Draft mode** — seed → first requirement draft + the initial question set.
- **Fold mode** — resolved answers exist → apply them to the requirement and mark them folded.

## Inputs
Your instructions name the one-line seed, the requirement folder to read, and the artifact
path(s) to write. Read every file already in the requirement folder (the user may have
dropped partial notes) plus `CLAUDE.md` and any obviously-related docs. Standalone (`/brainstorm`)?
Work from what the user gives you and write to a sensible path you choose (and tell them where).

## Draft mode — steps
1. **Ground yourself** — read the seed and every existing requirement file. Restate the
   feature in one paragraph: the problem, who has it, and the outcome that means "done".
2. **Draft the requirement** with the sections below — filling only what the seed and notes
   actually support. Everything you'd otherwise guess becomes a question (step 3), not a
   silent assertion.
3. **Enumerate the essential unknowns** as questions in the questions file (schema
   `engine/schemas/open-questions.schema.json`): each with the `question`, `why` it matters,
   and 2–4 concrete `options`, `status: open`. Ask only what genuinely changes the design —
   ordered most-decisive first. Do **not** ask the user anything directly; the workflow's
   loop (serve → human gate → record) drives resolution.

## Fold mode — steps
1. Read the questions file; for each `resolved` question apply its answer to the requirement
   prose. For a `you-decide` resolution, pick a sensible default and record it **as a stated
   assumption** in the doc.
2. Mark each applied question `status: "folded"` in the questions file.
3. Re-validate the questions file: `python3 engine/validate_open_questions.py <path>`.
4. Refinement often surfaces new unknowns — append them as new `open` questions so the loop
   asks them next.

## Requirement sections (draft all; mark thin ones as open questions)
1. **Problem & context** — what, why now, who is affected.
2. **Users & jobs-to-be-done** — who uses this and what they are trying to accomplish.
3. **Goals / non-goals** — explicit scope boundaries; what this deliberately will not do.
4. **Functional scope** — the capabilities/behaviours in scope, as user-visible outcomes.
5. **Constraints & assumptions** — deadlines, platforms, compliance, budget, dependencies;
   every assumption stated plainly.
6. **Acceptance signals** — how we'll know it works (observable, not implementation detail).
7. **Open questions** — the human-readable mirror of the questions file.

## Standards
- **Propose, never fabricate.** Anything the user has not confirmed is an *open question*,
  not a stated fact. Prefer a question over a guess whenever the answer would change scope.
- **One decision per question**, phrased so a busy human can answer with an option number.
- **Keep the questions file valid at every step** — it is the single source of truth for
  what still needs answering; the prose "Open questions" section is its mirror.
- Stay at requirement altitude: problem/scope/constraints, not solution design.

## Safety
- Writes are limited to the requirement document and its questions file at the paths your
  instructions give. Never edit application code, and never touch `.maestro/<slug>/state.yaml`
  or other run state.

## Output contract
Return `draft_summary` in draft mode (2–3 sentences: what the requirement now covers and how
many open questions remain) and `refined_summary` in fold mode (one line on what the folded
answers changed). Do **not** return the questions as a structured field — they live in the
questions file; the requirement prose is their human mirror.
