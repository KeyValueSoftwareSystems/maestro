---
name: plan-brainstorm
description: Talk a feature or change through with the person before its plan is written — they open, the agent suggests, spots improvements and issues, and challenges with evidence, one topic per turn — then write short notes of the agreed direction, decisions and open points for the plan writer.
allowed-tools: Read, Grep, Glob, Write
tags: [sdlc, design, plan]
---

# Plan brainstorm

Think the change through with the person as a conversation, not a questionnaire. This skill runs
in the lead agent's context and talks to the person directly; never delegate the conversation.

## Read boundary

Read only the workflow-supplied PRD, decision log, architecture doc, codebase maps and earlier
brainstorm notes. Open a source file only to check a specific claim the conversation depends on.
Do not scan the repositories broadly.

## Conversation

1. Let the person open. Ask one short question — what they have in mind, or where they want to
   start — and wait. When earlier notes exist, recap them in two or three lines and ask whether
   to pick up from their open points. When there is feedback to address, start from it.
2. Respond to what they said. Suggest an approach, name an improvement or an issue you see, and
   challenge a weak idea with evidence (a line of code, a doc, a rule). Give a recommendation with
   its concrete consequence when they ask for one, or when a choice is genuinely open.
3. One topic per turn. Wait for the person's reply after every turn. Never answer for them or
   treat silence as agreement.
4. Cover what the plan needs, at the level the change needs: which repositories change and how,
   interfaces between them (with exact shapes when more than one repository is involved), data
   and migrations, infrastructure, risks, and what is out of scope. A small change needs a few
   turns, not a design review.
5. When the person says they are done, recap what was agreed and what stays open in a few lines,
   confirm it, then write the notes.

## Notes format

Three sections, plain and short:

- **Direction** — the agreed approach in a few sentences.
- **Decisions** — one line each: the decision, the person's reason, and the alternative turned
  down when there was one.
- **Open points** — what was not settled, or "None".

Record only what the person agreed to; a point you proposed and they did not accept is open. When
notes exist from an earlier pass, update them in place. When run standalone without a path, write
the notes to a sensible path you choose (and tell the person where).

## Standards

- Plain words, short turns: two to five sentences, no essays, no plan prose.
- Say why a topic matters in one sentence.
- Never reopen a decision the decision log already records unless the person does.

## Safety

Write only the notes file. Never write the plan, code, decision records or any other file.

## Output contract

Return `summary`: one plain sentence naming the agreed direction and how many points stay open.
The person reads `summary` as it is: write it as one plain sentence of the outcome, with no ids,
file paths or jargon; technical detail stays in the artifact.
