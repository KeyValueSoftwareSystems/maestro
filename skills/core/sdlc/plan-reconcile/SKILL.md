---
name: plan-reconcile
description: Compare a feature's approved plan with what was actually delivered — the commits in each repository and the drift report — and propose the final plan that records what was built, plus a short plain-language list of the differences. Changes only what the commits evidence. Use when a feature is archived, or to bring a plan up to date with its code.
allowed-tools: Read, Grep, Glob, Bash, Write
tags: [sdlc, design, plan]
---

# Plan reconcile

A feature's plan is kept as the record of what was built. Code sometimes ends up a little
different from the plan that was approved: an endpoint gained a field, a migration was split, a
repository was not needed after all. Find those differences and propose the plan that describes
the delivered code, so a person can choose which version is kept.

## Grounding

Read what your instructions name: the approved plan, the delivery manifest (each repository's
branch, worktree and exact commit), and the drift check's report and findings when they exist.

- **Start from the drift report.** It already compared the code with the plan at release; each
  finding with its evidence is a candidate difference. Confirm it in the diff, do not redo the
  whole comparison.
- **Then read the diffs** of each repository from where its branch left the main line to the
  listed commit, in its listed worktree, for what the drift check did not cover or settled after.
- A **difference** is something the plan states that the delivered code does not do, or a
  material change the code makes that the plan does not mention: an interface shape, a decision,
  a data or migration change, infrastructure, a repository added to or dropped from the change,
  an acceptance criterion delivered somewhere else.
- **Not a difference:** detail the plan left open, naming and file layout inside a component the
  plan names, refactors with no visible effect, tests. A short plan leaves much open.

## Proposed final plan

Copy the approved plan and apply only the differences you found, each as a targeted edit in the
section it belongs to. Keep the same template, title, sections and order; keep every line the
code does not contradict exactly as it was. Set the header's `Status:` to `completed` (add
`· Status: completed` to the header when it has none). When there are no differences, the
proposed plan is the approved plan with only that header change.

Never invent: every edit must be evidenced by a commit in the diff (or a drift finding you
confirmed in it). When you cannot tell whether the code or the plan is right, leave the plan
line as it is and say so in the change list.

## Change list

Write the change list your instructions name, for a person deciding whether to accept the update:
a heading, then one plain line per difference — what the plan said, what was built, and where
(repository and short commit). No JSON, no diff hunks. When there are none, write one line saying
the delivered code matches the plan.

## Revision

When your instructions carry the person's feedback on an earlier proposal, apply it: drop,
reword or add the differences they name (an added one still needs evidence in the commits), and
rewrite both files.

## Standalone use

When a person invokes this skill directly, their message is the brief: take the plan and the
branches or commits from it, write the proposed plan and the change list to paths you choose,
and tell the person where. Never overwrite the approved plan itself.

## Standards

- Plain, skimmable English in the change list; the plan keeps its own technical register.
- The smallest edit that makes the plan true to the code.

## Safety

Read-only against code, branches and the approved plan. Write only the proposed plan and the
change list your instructions name.

## Output contract

Return `changed` (true when at least one difference was found, else false) and `summary`: one
plain sentence for the person naming the differences (or saying the code matches the plan).
