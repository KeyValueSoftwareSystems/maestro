---
name: retrospect
description: Distill a finished Maestro run into durable, provenance-tagged lessons staged for consolidation. Front door for /retrospect.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [maestro, memory, retrospective]
---

# retrospect — turn one run's outcomes into lessons

Read a finished feature run and extract what future runs should know. You write ONLY the
per-run staging drop — never the trusted knowledge tier.

## Inputs
Your instruction names the run to read (its ledger + artifacts) and the single incoming file
to write. Standalone? Summarise to a path you choose and tell the user.

## Method
1. **Mine the ledger.** From the run's `state.yaml`: gate decisions and their
   feedback/guidance text (what a human overrode and why), per-step `visits`/`attempts`
   (loops that thrashed, steps that retried), failure reasons.
2. **Mine the artifacts.** Blocking review findings, QA failures, contract mismatches —
   especially anything that recurred.
3. **Write lessons**, bucketed by the consuming domain (which SDLC role would benefit). Each
   lesson: a short actionable claim + why. Tag provenance with this run's slug.
4. **Stage only.** Write to the incoming drop for this run. Do NOT touch the knowledge or
   candidates tiers — consolidation owns promotion.

## Standards
- A lesson is a repeatable pattern, not a one-off event narration. If it only makes sense for
  this feature, leave it out.
- Short scalars in the output; the lessons live in the file.

## Safety
- Read-only against the run; write only the single incoming file named in your instruction.

## Output contract
Return `incoming_path` (the file written), `lessons_count` (integer), and `summary` (one line).
