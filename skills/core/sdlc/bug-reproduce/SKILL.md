---
name: bug-reproduce
description: Reproduce a reported bug in a sandbox — against the running app when one is up, otherwise with a test alone — then pin it with a committed regression test that fails because of the bug, and write a short reproduction report naming the branch and commit of every repository. Changes no product code. Use after a bug is triaged and before its fix is proposed.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write
tags: [sdlc, bugfix, qa]
---

# Bug reproduce

Show that the bug is real, on the code the fix will start from, and leave a test that proves it.

## Grounding

Read what your instructions name: the bug report (symptoms, expected vs actual, steps), the mini
PRD's acceptance criteria (the expected behaviours), and the sandbox record — each repository's
worktree, fix branch, commit and the base it was built from. Work only in those worktrees.

## Steps

1. **Against the running app** (your instructions say whether the engine started one): follow the
   report's steps with the tools at hand — HTTP requests, the CLI, a browser automation the
   repository already has, database queries. Record exactly what you sent and what came back.
   Do not start, stop or reconfigure the environment yourself.
2. **Pin it with a test.** In the repository that owns the behaviour, write the smallest
   regression test that fails because of the bug and will pass once the expected behaviour is
   restored. Use the repository's own test framework and conventions; add no framework or
   dependency. Run it and confirm it fails for the right reason (the assertion on the expected
   behaviour, not a setup error).
   With no running app, this test is the reproduction.
3. **Commit the test** on the worktree's fix branch (`test: reproduce <bug in a few words>`).
   Change no product code, and never weaken or delete an existing test.
4. **Not reproduced?** Say so honestly: what you tried, what happened instead, and what might
   explain it (data, configuration, a repository on a different base). Do not commit a test that
   passes; leave the worktree clean.

## Reproduction report

Write it where your instructions say:

- **Result** — reproduced or not, in one line.
- **Code under test** — per repository: branch, commit (short) and the base it came from. Call
  out a repository that is not on the bug's branch (it fell back to another one): the running app
  mixes versions, which can hide the bug or show a different one.
- **Steps and observations** — what you did, expected vs observed, with exact values.
- **Failing test** — file, test name, the command that runs it, and the failure message.

## Safety

No product code changes, no destructive commands, no production data or credentials. Write only
the regression test (committed on the fix branch) and the report.

## Output contract

Return `reproduced` — the literal JSON boolean `true` only when you saw the bug happen (in the
app or in the failing test), else `false` — and `summary`: one plain sentence for the person on
what you saw and the test that now proves it (or why it did not reproduce).
The person reads `summary` as it is: write it as one plain sentence of the outcome, with no ids,
file paths or jargon; technical detail stays in the artifact.
