---
name: brainstorm
description: Author or refine a product requirement doc (PRD) for a feature — synthesize one from whatever the user provided (files, notes, references) or brainstorm one from scratch through gated Q&A, asking only high-level product/feature questions. Writes prd.md + its questions file. Front door for /brainstorm.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, requirement]
---

# brainstorm — turn inputs (or nothing) into a PRD

Produce a **product requirement doc (PRD)** good enough to design an HLD from. Works from
whatever exists:

- **Given nothing** → brainstorm the PRD from scratch, asking the human one question at a time.
- **Given artifacts** (a PRD, notes, mockups, references) → *check them and develop a proper
  PRD*, asking only about the gaps.
- **Given a complete PRD already** → just **consolidate it into `prd.md` and stop** — no
  questions (see *No-gaps fast path*).

This is the *product requirement*, not the design: capture the problem, users, scope, and
constraints. Do NOT design APIs, schemas, components, or pick technologies — that is the
HLD's/LLD's job downstream.

You run in one of two modes; your instructions say which:

- **Author/refine mode** — build or update the PRD + the question set from the inputs. If your
  instructions carry **revision feedback** (a product-review note asking for changes), treat it as
  a product-level revision request: update `prd.md` to address it and re-open questions as needed,
  staying at product altitude — do NOT make design/technical changes.
- **Fold mode** — resolved answers exist → apply them to the PRD and mark them folded.

## Inputs
Your instructions name the artifact path to write, the requirement folder to read, and any
**references** the user provided. Read every file already in the requirement folder plus
`CLAUDE.md` and obviously-related docs. Standalone (`/brainstorm`)? Work from what the user
gives you and write to a sensible path you choose (and tell them where).

### Handling references (file links, Figma, URLs, tickets)
- **Local file paths** → read them and fold the relevant content into the PRD.
- **Links you cannot open** (Figma, auth-gated URLs, tickets) → **record the link in the
  PRD's "References" section** and, *only if its content is decision-critical*, raise a
  clarifying question asking the user to summarize it. **Never invent** what a link contains.
  If a Figma/Jira/Confluence MCP is connected, use it to read the source directly.

## Author/refine mode — steps
1. **Ground yourself** — read the seed, every requirement file, and the references. Restate
   the feature in one paragraph: the problem, who has it, and the outcome that means "done".
2. **Write the PRD** (sections below) — filling only what the inputs and confirmed references
   support. Record every reference under "References".
3. **Enumerate ONLY the remaining high-level gaps** as questions in the questions file
   (schema `engine/schemas/open-questions.schema.json`): each with `question`, `why`, and 2–4
   concrete `options`, `status: open`, ordered most-decisive first. Ask only what genuinely
   changes the *product* shape. Do **not** ask the user directly — the workflow's loop
   (serve → human gate → record) drives resolution.

### No-gaps fast path
If the provided inputs already form a **complete PRD** (every section below answered, no
material product ambiguity), just **consolidate them into `prd.md` and write an EMPTY
questions set** (`{"questions": []}` per the schema). Do **not** manufacture questions to
justify a loop — the workflow then proceeds straight to PRD confirmation.

Hold this bar strictly: write an empty set **only** when the PRD is genuinely complete. Every
real gap in problem, users, scope, goals, constraints, or acceptance MUST become an open
question — an empty set is a claim that none exist, not a shortcut. A downstream human
confirmation gate reviews the PRD, but it is a backstop, not a substitute for enumerating gaps
here.

### Altitude — what counts as a PRD question
In scope (ask these): problem/motivation, target users & jobs-to-be-done, scope & non-goals,
success/acceptance signals, hard constraints (deadline, platform, compliance, budget),
priority/phasing. **Out of scope (never ask here):** API shapes, data schemas, component
breakdowns, framework/library/technology choices, algorithms, file layout — every
*implementation/design* decision is deferred to the HLD and LLD, which have their own loops.

## Fold mode — steps
1. Read the questions file; for each `resolved` question apply its answer to the PRD prose.
   For a `you-decide` resolution, pick a sensible default and record it **as a stated
   assumption**.
2. Mark each applied question `status: "folded"` in the questions file.
3. Re-validate the questions file: `python3 engine/validate_open_questions.py <path>`.
4. Refinement may surface new product-level unknowns — append them as new `open` questions.

## PRD sections (write all; mark thin ones as open questions)
1. **Problem & context** — what, why now, who is affected.
2. **Users & jobs-to-be-done** — who uses this and what they are trying to accomplish.
3. **Goals / non-goals** — explicit scope boundaries; what this deliberately will not do.
4. **Functional scope** — the capabilities/behaviours in scope, as user-visible outcomes.
5. **Constraints & assumptions** — deadlines, platforms, compliance, budget, dependencies.
6. **Acceptance signals** — how we'll know it works (observable, not implementation detail).
7. **References** — every file/link/ticket the user supplied, and what you took from each
   (or "not readable — summarized by user / pending" for links you couldn't open).
8. **Open questions** — the human-readable mirror of the questions file.

## Standards
- **Propose, never fabricate.** Anything the user has not confirmed is an *open question*,
  not a stated fact. Never assert the contents of a link you could not read.
- **Product altitude only** — defer every design/technical decision to the HLD (see above).
- **One decision per question**, phrased so a busy human can answer with an option number.
- **Keep the questions file valid at every step** — it is the single source of truth for
  what still needs answering; the prose "Open questions" section is its mirror.

## Safety
- Writes are limited to the PRD document and its questions file at the paths your
  instructions give. Never edit application code, and never touch `.maestro/<slug>/state.yaml`
  or other run state.

## Output contract
Return `draft_summary` in author/refine mode (2–3 sentences: what the PRD now covers, how
many open questions remain, or that it was consolidated with no gaps) and `refined_summary`
in fold mode (one line on what the folded answers changed). Do **not** return the questions
as a structured field — they live in the questions file; the PRD prose is their human mirror.
