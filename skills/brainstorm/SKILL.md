---
name: brainstorm
description: Talk an idea or change through with the user as a collaborative conversation — they lead, you suggest approaches, spot issues and challenge weak ideas with evidence, one topic per turn — until the direction is agreed. Use before writing a plan or design.
---

# Brainstorm

A conversation, not a questionnaire. Run it with the user directly; never hand it to a subagent
that cannot talk to them.

## Conversation

1. **Let them open.** Ask one short question — what they have in mind, or where to start — and
   wait. If there are earlier notes or feedback, recap them in two or three lines and start there.
2. **Respond.** Suggest an approach, name an improvement or a problem, and challenge a weak idea
   with evidence (a line of code, a doc, a constraint). When a choice is genuinely open, give a
   recommendation and its concrete consequence.
3. **One topic per turn**, two to five sentences. Wait for the reply. Never answer for the user or
   treat silence as agreement.
4. **Cover what the change needs**, at the depth it needs: where it goes, interfaces, data,
   infrastructure, risks, and what is out of scope. A small change needs a few turns.
5. **Close.** When the user says they are done, recap what was agreed and what is still open,
   and confirm it.

## Notes

If the caller gave a notes path, write the outcome there; otherwise keep it in the conversation
for whoever writes next. Three short sections:

- **Direction** — the agreed approach in a few sentences.
- **Decisions** — one line each: decision, reason, alternative turned down.
- **Open points** — what was not settled, or "None".

Record only what the user agreed to. A point you proposed that they did not accept is open.
