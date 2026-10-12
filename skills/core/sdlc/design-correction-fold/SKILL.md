---
name: design-correction-fold
description: Apply human-approved corrections to final design-document copies with minimal, validated edits and no unrelated rewriting.
allowed-tools: Read, Grep, Glob, Write, Edit, Bash
tags: [sdlc, design, archive]
---

# Design correction fold

Apply an authoritative set of approved corrections to supplied final design copies. This is a
targeted archival edit, not another product or architecture design pass.

## Method

1. Read the supplied correction context, fold plan, and only the affected final document copies.
2. Map each correction to the narrowest affected section. If a correction spans layers, update only
   the statements that would otherwise contradict it.
3. Preserve confirmed wording, document structure, identifiers, tables, and unrelated sections.
4. Keep prose concise and skimmable. Prefer replacing a contradicted sentence or table row over
   adding an explanatory paragraph.
5. Run every supplied structural validator for changed PRD, HLD, and LLD copies.
6. Write the requested machine-readable fold report with every correction ID and changed path.

## Standards

- Approved corrections override conflicting base text.
- Do not introduce new requirements, decisions, alternatives, history, or commentary.
- Never mark unresolved content as resolved through inference.
- Do not renumber acceptance criteria unless the correction explicitly changes acceptance scope.
- A correction that affects no text is still an error; do not claim a no-op as folded.

## Safety

- Edit only the supplied final-copy directory and requested report artifact.
- Never edit original approved artifacts, source code, workflow state, or approval receipts.
- Do not weaken security, privacy, failure, or verification requirements to make documents agree.

## Output contract

Return `summary` with a short factual description of the corrected copies. Never return document
content.
