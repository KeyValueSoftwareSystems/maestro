---
name: bug-triage
description: Pin a bug down with the person as a conversation — what happens, what should happen, where, since when, and which repositories are affected — then write a short bug report and a mini PRD whose acceptance criteria are the expected behaviours the fix must restore. Use when a bug is reported and before anyone reproduces or fixes it.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, bugfix, requirements]
---

# Bug triage

Turn a bug report — a ticket, a message, a log, a sentence — into a description everyone agrees
on, before anyone looks for the cause. This skill runs in the lead agent's context and talks to
the person directly; never delegate the conversation.

## Read boundary

Read every file your instructions point to in the requirement folder (tickets, notes, logs,
screenshots' descriptions), the architecture doc and the codebase maps. Open source files only to
confirm which repository and module owns the behaviour; do not hunt for the cause here.

## Conversation

1. Recap what you already know in two or three lines (from the files, or the person's words)
   and ask the first open point. When there is feedback (the bug came back from a later step),
   start from it.
2. One question per turn, and wait for the reply. Never answer for the person or treat silence as
   agreement. Cover, at the depth the bug needs:
   - **Symptoms** — what the person sees: the screen, endpoint, job or message, with exact text or
     values when they have them.
   - **Expected vs actual** — what should happen instead. Each expected behaviour becomes one
     acceptance criterion, so make each one observable.
   - **Where and when** — steps to reproduce, data or account involved, environment, since when
     (a release, a deploy, a date), how often.
   - **Affected repositories** — name them with the names in the project configuration. Confirm
     with the person; propose from the architecture doc and maps.
   - **The branch** the bug was seen on (your instructions give it); note if the person says some
     repositories run another branch.
3. When the person asks to leave some repositories out (they lack the branch, or are not
   involved after all), drop them and say what that leaves.
4. Finish only when the person agrees the description is right. Then write both documents.

## Bug report

Write it where your instructions say, plain and short:

```markdown
# <Bug in a few words> — bug report

Branch: <branch> · Repositories: <repo>, <repo>

## Symptoms
## Expected behaviour
## Actual behaviour
## Steps to reproduce
## Notes
```

Notes holds since-when, frequency, data, links, and anything the person was unsure about.

## Mini PRD

Write the mini PRD where your instructions say, in the format of a PRD's minor profile: the
compact header (`# <Bug> — PRD`, `**Feature slug:** \`<slug>\``, `**Status:** Ready for review`),
then exactly `## Problem` (the bug in two to four lines), `## Acceptance criteria` (one
`AC-01:`-style bullet per expected behaviour, observable, in the person's terms) and
`## Out of scope` (what the fix does not change). No other sections. Run the validator your
instructions name and fix what it reports.

When both documents exist from an earlier pass, update them in place: keep every criterion ID
that still holds, change only what the conversation changed.

## Safety

Read-only on code and branches. Write only the two documents your instructions name.

## Output contract

Return `summary`: one plain sentence for the person saying what the bug is and what the fix must
restore; and `repos_csv`: the affected repositories, comma-separated, using the configured names
(for example `api,web`).
The person reads `summary` as it is: write it as one plain sentence of the outcome, with no ids,
file paths or jargon; technical detail stays in the artifact.
