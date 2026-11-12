---
name: hld-brainstorm
description: Brainstorm a feature's high-level architecture with the user as an open conversation, then write short notes of the agreed direction, decisions and open points for the HLD writer. Use instead of a structured question interview when the user wants to think the design through together.
allowed-tools: Read, Grep, Glob, Write
tags: [sdlc, design, hld]
---

# HLD brainstorm

Think the architecture through with the user as a conversation, not a questionnaire. This skill
runs in the lead agent's context and talks to the user directly; never delegate the conversation.

## Read boundary

Read only the workflow-supplied requirement, decision log, architecture and technical docs,
codebase maps, and earlier brainstorm notes. Open a source file only to check a specific claim the
conversation depends on. Do not scan the repository broadly.

## Conversation

1. Open with a short proposed direction (owners, main flow, data authority) grounded in the
   requirement and docs, then name the two or three trade-offs that are genuinely open. When
   earlier notes exist, recap them in a few lines and pick up from their open points.
2. Let the user steer. Take one topic at a time; answer their questions, challenge weak ideas with
   evidence, and give a recommendation with its concrete consequences when they ask for one.
3. Wait for the user's reply after every turn. Never answer for them or treat silence as agreement.
4. Stay at HLD altitude: ownership, boundaries, cross-repo interaction, data, security, failure,
   infrastructure, rollout. Endpoint fields, table columns and file lists belong to the LLD.
5. When the user says they are done, recap what was agreed and what stays open in a few lines,
   confirm, then write the notes.

## Notes format

Three sections, plain and short:

- **Direction** — the agreed architecture in a few sentences.
- **Decisions** — one line each: the decision and the user's reason.
- **Open points** — what was not settled, or "None".

Record only what the user agreed to; a point you proposed and they did not accept is open. When
run standalone without a path, write the notes to a sensible path you choose (and tell the user
where).

## Standards

- Keep each turn short; no essays, no HLD prose.
- One topic per turn; say why it matters in a sentence.
- Never reopen a decision the decision log already records unless the user does.

## Safety

Write only the notes file. Never write the HLD, decision artifacts or any other file.

## Output contract

Return `summary`: one short sentence naming the agreed direction and how many points stay open.
