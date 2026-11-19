---
name: fix-proposal
description: Find the root cause of a triaged bug and propose the fix before any code is written — what is wrong and why, the change per repository, its impact on users, other features and data, the risks, and the tests that will prove it — in a short document a person approves. Writes no product code. Use after a bug is triaged (and reproduced, when it was).
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, bugfix, design]
---

# Fix proposal

A person approves the fix before anyone writes it. Give them what they need to say yes or no:
the cause, the change, who it affects and what could go wrong.

## Grounding

Read what your instructions name: the bug report, the mini PRD's acceptance criteria, the test
cases, the reproduction when there is one (its failing test is the best evidence), and the code in
the sandbox worktrees (the exact code the fix starts from).

## Root cause

Trace the behaviour from the symptom to the code that produces it. State the cause as a fact with
evidence (file, function, the condition that goes wrong), not a guess. When you cannot be sure,
say what you believe and what would confirm it. Distinguish a code defect from data,
configuration or environment problems; propose a code change only for a code defect.

## The proposal

Write it where your instructions say, short and plain:

```markdown
# <Bug in a few words> — fix proposal

## Cause
## Change
## Impact
## Risks
## Tests
```

- **Cause** — what is wrong and why, with the evidence.
- **Change** — per repository: the files or modules and what changes in them. The smallest change
  that restores the expected behaviours; no refactors or unrelated fixes.
- **Impact** — behaviour that changes for users (beyond the bug itself), other features or
  callers of the changed code, data or configuration changes (a migration, a flag, a setting).
  Write "None" for an empty part rather than leaving it out.
- **Risks** — what could break and how the tests or a rollout guard against it.
- **Tests** — the regression test (the reproduction's, when there is one) and which acceptance
  criteria each test proves.

The fix is held to this document: a change it does not name is escalated to a person, so name
every repository and area the fix needs.

## Revision

When your instructions carry the person's feedback on an earlier proposal, apply only that
feedback and keep the rest.

## Safety

Read-only on code and branches. Write only the proposal.

## Output contract

Return, each as one plain sentence for the person (no file paths or code): `summary` (the fix in
one line), `cause` (what is wrong and why), `change` (what will change, per repository), `impact`
(who and what is affected beyond the bug; "None" when nothing) and `risks` (what could go wrong;
"None" when nothing).
