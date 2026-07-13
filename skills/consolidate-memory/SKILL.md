---
name: consolidate-memory
description: Merge staged Maestro lessons into candidates, promote corroborated ones into trusted knowledge, and prune/cap the store. Front door for /consolidate-memory.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [maestro, memory, consolidation]
---

# consolidate-memory — the reduce step, with corroboration before promotion

Turn per-run staging drops into trusted domain knowledge, but only promote a lesson once
MULTIPLE runs corroborate it — never on the strength of one run.

## Inputs
Your instruction names the store paths (incoming, candidates, knowledge, index) and the
promotion threshold. Standalone? Operate on the memory store and tell the user what changed.

## Method
1. **Fold incoming into candidates.** For each lesson in the incoming drops, find its
   matching candidate (same claim + domain). If found, increment its observation count and
   append the new source slug — counting DISTINCT slugs only (a lesson repeated within one
   run counts once). If new, add it as a candidate with count 1. Then clear the incoming
   drops you folded.
2. **Promote the corroborated.** Any candidate seen in **>= threshold distinct slugs**
   (default **3**) graduates into the knowledge tier for its domain; remove it from
   candidates. Sub-threshold candidates stay and keep accruing.
3. **Prune & cap.** Dedup within knowledge; drop superseded or contradicted lessons; enforce
   a per-file size cap so injected knowledge stays small; age out candidates that have sat
   far below threshold for too long.
4. **Index.** Rewrite `index.md`.

## Standards
- Bootstrap-authored and human-authored knowledge lessons are authoritative — never demote
  or delete them for lacking a count.
- Favour a small, high-signal knowledge tier. Every promoted lesson is paid for in tokens on
  every future run that reads it.
- Never lower a lesson's count or fabricate corroboration.

## Safety
- You are the ONLY writer of the candidates and knowledge tiers. Do not edit run state or
  application code.

## Output contract
Return `promoted` (count promoted to knowledge this pass), `candidates` (count still staged),
and `summary` (one line).
