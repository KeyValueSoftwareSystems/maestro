---
name: plan
description: Produce a high-level design (HLD) for a feature — frame the problem, weigh options with trade-offs, choose an approach, define non-functional requirements and risks, and write a standardized hld.md. Read-only (writes only the HLD doc). Front door for /plan.
allowed-tools: Read, Grep, Glob, Bash, Write, AskUserQuestion
tags: [sdlc, design, hld]
---

# plan — high-level design

Turn a feature request + requirement files into a **high-level design**: the shape of the solution, the
options considered, the chosen approach, and the risks — enough for a human to approve the
*direction*. This is a design artifact, not code — don't design APIs, schemas, or code here.

## Inputs
Your instructions name what to read — the requirement FOLDER — and the artifact path(s) to
write. **Read every file in the folder** as the feature requirement (it may hold a PRD, notes,
mockups, etc.). Standalone? read the requirement and write to a path you choose (and tell the user where).

## Steps
1. **Gather context** — read every file in `requirement_dir`, related ADRs, `CLAUDE.md`, and any existing design.
   Identify the users, the job-to-be-done, and hard constraints (deadlines, platforms,
   compliance, budget). **Then ground in the real code**: read the codebase map if one was
   provided (it enumerates the existing execution modes the feature must handle), and read the
   actual source of the flow you are extending — every mode/branch it runs in, not just the one
   the prompt names. Designing from the prompt alone is the failure mode this step prevents: an
   approach that only fits the happy path but breaks an existing mode (multi-turn, async, batch,
   streaming) is a wrong HLD. If no map was provided and the code is nontrivial, do this survey
   yourself before choosing an approach.
2. **Clarify unknowns** — list assumptions explicitly; ask the human when a business rule,
   SLA, or data-ownership question is genuinely ambiguous. Do not silently guess.
3. **Diverge** — generate 2–3 genuinely different approaches (delegating to the
   `brainstorming` skill if installed). Run a quick pre-mortem on each ("how would this
   fail?").
4. **Evaluate & choose** — score options against effort, risk, NFRs, and reversibility.
   Recommend one; say *why it wins* and what you're trading away.
5. **Sketch** — components, data flow, and the cross-repo boundary (which stacks change).
6. **Nail the NFRs and risks** — sections below.
7. **Write** the artifact (HLD + `open-questions.json`) and, if running
   interactively, resolve the open questions in a loop — see "Open-question loop".

## What to cover (standard HLD sections — write all)
1. **Context & problem** — what, why, who; link the requirement files.
2. **Goals / non-goals** — explicit scope boundaries.
3. **Options considered** — 2–3 approaches, each with trade-offs (cost, risk, effort, time-to-value).
4. **Chosen approach** — the recommendation and the reasoning.
5. **Architecture sketch** — components, data flow, boundaries, external dependencies.
6. **Non-functional requirements** — security & privacy (authz model, PII, threat surface),
   scale/throughput, availability/SLO, latency budget, cost, compliance/data residency.
7. **Data lifecycle** — what data is created/read/updated/deleted, retention, ownership,
   and any backfill/migration of existing data.
8. **Backward compatibility & migration** — impact on existing clients/data; additive vs breaking.
9. **Dependencies & sequencing** — other teams/services, feature flags, order of rollout.
10. **Rollout & backout** — flagging, phased rollout, metrics to watch, how to revert.
11. **Risks & mitigations** — top risks each with a mitigation and an owner.
12. **Open questions** — anything a human must resolve before LLD.

## Edge cases & failure modes to think through now
- Ambiguous or conflicting requirements; multiple stakeholders wanting different things.
- Greenfield vs brownfield (existing constraints, legacy data, in-flight migrations).
- Multi-tenant / data-isolation needs; regulated data (PII/PHI/PCI).
- Large existing dataset requiring backfill; zero-downtime migration.
- Third-party dependency risk (rate limits, outages, cost, lock-in).
- High-concurrency or spiky load; graceful degradation under partial failure.
- Reversibility: can we ship behind a flag and roll back cleanly?

## External skill (provision — ideation)
If the `brainstorming` skill (from the Superpowers pack) is installed, use it to diverge and
pressure-test — but **you remain responsible** for the coverage above. Whatever the external
skill does, ensure it produced: alternatives with trade-offs, surfaced assumptions, and a
pre-mortem. If it is not installed, do this yourself.
## Output — write these artifacts
Write two artifacts to the paths your instructions specify:
- the HLD with all sections above, including an "Open questions" section
  (human-readable prose).
- an `open-questions.json` — the machine-readable mirror of that section, conforming to
  `engine/schemas/open-questions.schema.json`. Each question carries `why` it matters
  and 2–4 suggested `options`. Validate it with
  `python3 engine/validate_open_questions.py <path>`.

## Open-question loop (interactive only)
When run standalone with `AskUserQuestion` available (a developer running `/plan`
in Claude Code), run the interactive open-question loop yourself; when run as an
orchestrated (non-interactive) step, just WRITE `open-questions.json` — the workflow's OQ loop
(script serve → human gate → record → refine) drives resolution.

If `AskUserQuestion` is available **and** `open-questions.json` has any `open`
questions, resolve them in a loop:

1. For each `open` question, ask via `AskUserQuestion` — offer its suggested
   `options` (the tool auto-adds **Other** for a custom answer), plus explicit
   **"You decide"** and **"Skip / defer"** choices.
2. Record the answer into `open-questions.json`:
   - a suggestion or Other → `status: resolved`, `resolution.kind`
     `picked`/`other`;
   - **You decide** → `status: resolved`, `resolution.kind: you-decide` (you pick
     a sensible default and record it in the HLD as a **stated assumption**);
   - **Skip / defer** → `status: deferred`, `resolution.kind: skip` (the question
     stays in the HLD "Open questions" section and does not block).
3. Fold every `resolved` answer into the HLD prose (mark it `folded`), then
   **re-derive** open questions — refinement often surfaces new ones; append them
   as new `open` entries.
4. Repeat from step 1 until no `open` questions remain (deferred ones may stay).

Keep `open-questions.json` valid at every step. When `AskUserQuestion` is not
available, just write the artifacts and stop — resolution happens downstream.

## Definition of done
Every section present; ≥2 options with trade-offs; NFRs and risks concrete (not "TBD");
open questions listed; **the chosen approach demonstrably handles every execution mode the
codebase map (or your own survey) enumerated** — if one mode can't be supported, that is
stated as an explicit scope constraint, not glossed over. Do not proceed to detailed design or
implementation — this artifact stops at the *direction*.

## Output contract
Return `hld_path` and `hld_summary` (2–3 sentences). When invoked in **refine mode**
(folding resolved open questions back into an existing HLD), return `refined_summary`
instead — a one-line note of what changed. Do **not** return open questions as a separate
structured output field — they live in the file (a prior attempt to return them as an agent
output failed schema validation). The file is the single source of truth; the HLD prose
section is its human mirror.
