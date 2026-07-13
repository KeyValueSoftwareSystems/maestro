---
name: retrospect
description: Distill a finished Maestro run into structured, keyed lessons staged for the engine to consolidate. Front door for /retrospect.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [maestro, memory, retrospective]
---

# retrospect — turn one run's outcomes into staged lessons

Read a finished feature run and extract what future runs should know. You produce ONLY a
structured per-run drop; the **engine** (`mem_consolidate.py`) owns counting, corroboration,
promotion and rendering — none of that is your concern, so a replacement skill only has to
emit the same drop for the memory system to keep working.

## Inputs
Your instruction names the run to read (its ledger + artifacts) and the single incoming JSON
file to write. Standalone? Write to a path you choose and tell the user.

## Method
1. **Mine the ledger.** From the run's `state.yaml`: gate decisions and their
   feedback/guidance text (what a human overrode and why), per-step `visits`/`attempts`
   (loops that thrashed, steps that retried), failure reasons.
2. **Mine the artifacts.** Blocking review findings, QA failures, contract mismatches —
   especially anything that recurred.
3. **Emit a structured drop.** Write the incoming file named in your instruction as JSON:

   ```json
   {
     "slug": "<this run's slug>",
     "lessons": [
       {"domain": "backend-review", "key": "n-plus-one-list-endpoints",
        "text": "Check for per-row queries in loops before approving."}
     ]
   }
   ```

   - `domain` — the consuming SDLC role the lesson helps (`plan`, `backend-design`,
     `backend-review`, `architecture-review`, or `codebase` for cross-cutting facts).
   - `key` — a short, stable, kebab-case identifier for the *pattern*. Pick it so a DIFFERENT
     run observing the same pattern would choose the SAME key — that is how the engine
     corroborates across runs. Do not encode the slug or a date in the key.
   - `text` — one short, actionable sentence.
   - Do NOT set `authoritative` (that is for bootstrap). Do NOT write `knowledge/` or
     `candidates/` — the engine renders those.

## Standards
- A lesson is a repeatable pattern, not a one-off event narration. If it only makes sense for
  this feature, leave it out.
- Keep `text` short; injected knowledge is paid for in tokens on every future run.

## Safety
- Read-only against the run; write only the single incoming JSON file named in your instruction.

## Output contract
Return `incoming_path` (the JSON file written), `lessons_count` (integer), and `summary`
(one line).
