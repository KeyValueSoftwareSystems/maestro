---
name: repo-review
description: Review one repository's exact implementation worktree and commit against its LLD and contract.
allowed-tools: Read, Grep, Glob, Bash, Write, Task
tags: [sdlc, review, repository]
---

# repo-review

Review only the exact `worktree` and `commit` supplied by the workflow. First verify its HEAD
equals the supplied commit and its current branch equals the supplied branch. If either
differs, report a blocking integrity finding instead of reviewing another checkout.

Compare the complete diff to the repository's approved LLD, shared contract, codebase map,
and repo instructions. Cover correctness, security/authz, input bounds, error behavior,
compatibility, data migration safety, concurrency/idempotency, performance, observability,
and meaningful positive/negative tests as applicable to that repository's technology.
Findings require `file:line` evidence. A blocker or major finding makes `blocking=true`.
Review read-only; write the requested report artifact outside the product worktree.

Return `review_path`, literal boolean `blocking`, and a one-line `summary` as last-line JSON.
