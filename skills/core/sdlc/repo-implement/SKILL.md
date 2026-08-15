---
name: repo-implement
description: Implement every task slice in one selected repository and return a verifiable worktree handoff.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write, Task
tags: [sdlc, implement, repository]
---

# repo-implement

The workflow supplies `repo_path`, `branch`, the LLD, contract, and a validated task DAG.
Before editing, create the feature worktree from that repository specifically:

`git -C <repo_path> worktree add -b <branch> <new-dir> HEAD`

If the branch exists, attach it instead. Verify the new directory is a registered worktree
and do every edit, test, merge, and commit inside it. Never edit the umbrella checkout or
fall back to the repository's main worktree.

Read repo instructions and the task context manifest in batches. Implement all slices. When
the harness supports safe parallel agents, use at most three slice worktrees with disjoint
writes, then merge every slice commit into the feature branch. Otherwise implement slices
sequentially in the feature worktree. Honor human gates for auth, payments, migrations,
production config, secrets, and dependency upgrades. Never weaken a failing test.

Run the repository's real formatter/linter/type checks and targeted plus relevant full
tests, including provider/consumer contract checks required by the LLD or OpenAPI contract.
If no contract runner exists, add the smallest framework-native contract assertion needed
for the changed boundary; do not report green based on a no-op command. Commit the finished
state. Before returning, capture:

- `branch`: `git branch --show-current`
- `worktree`: absolute `git rev-parse --show-toplevel`
- `commit`: full `git rev-parse HEAD`
- `tests_passed`: literal JSON boolean, true only when checks actually ran and passed

Return those fields plus a short `summary` in the last-line JSON object. The engine verifies
that branch, worktree, and commit agree before QA can start.
