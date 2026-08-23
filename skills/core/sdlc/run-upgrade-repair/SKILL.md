---
name: run-upgrade-repair
description: Convert legacy PRD and HLD documents into current concise structures while preserving every existing decision and adding no new product or architecture content.
allowed-tools: Read, Write, Edit, Bash
tags: [sdlc, design, migration]
---

# Legacy design structure conversion

Convert supplied legacy PRD and HLD artifacts to the requested current document contracts. The
source decisions are authoritative; this skill changes organization and wording only where needed
for the current validator.

## Method

1. Read the upgrade manifest, immutable legacy copies, current PRD/HLD copies, and deferred-question
   ledger.
2. Build a compact decision inventory before editing: product scope and acceptance, non-goals,
   constraints, architecture ownership and boundaries, data flow, security/failure behavior,
   migration/rollout, risks, and open questions.
3. Map every inventoried fact into exactly one current section. Keep acceptance identifiers only in
   acceptance criteria and preserve their meaning.
4. Remove only repetition, obsolete revision history, and excess explanation. Do not remove a
   unique requirement or decision to meet brevity limits; compress it instead.
5. Run the supplied validators. Repair only named structural, metadata, ordering, duplication, or
   brevity defects.

## Standards

- Use plain, skimmable technical English and short bullets or tables where they reduce repetition.
- Preserve every settled decision exactly in meaning, including decisions that seem unusual.
- Keep implementation-level schema/route detail in repository LLDs, not the HLD.
- Preserve explicit unknowns in the deferred-question ledger; never manufacture an answer.
- Add no migration commentary to the converted documents.

## Safety

- Edit only the supplied current PRD and HLD paths.
- Never edit immutable legacy copies, workflow state, approval receipts, source code, or LLDs.
- Stop rather than inventing content when an exact current section cannot be populated from the
  legacy documents.

## Output contract

Return `summary` with a short factual conversion and validation result. Never return document text.
