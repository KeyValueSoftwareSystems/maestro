---
name: repo-implement
description: Implement every task slice in one selected repository (or, in slice mode, one slice group), test-first, to the repository's engineering standards, and return a verifiable worktree handoff.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write, Task
tags: [sdlc, implement, repository]
---

# repo-implement

Build the approved scope of one repository exactly as the feature's approved plan describes. Stay in
scope; the design is decided — implement it, do not redesign it.

## Isolate first

The workflow supplies `repo_path`, `branch`, the approved plan, and a validated task DAG.
When it also supplies a `worktree`, that is the feature worktree: check it is on `branch`, work
only there and never create another. Otherwise, before editing, create the feature worktree from
that repository specifically:

`git -C <repo_path> worktree add -b <branch> <new-dir> HEAD`

If the branch exists, attach it instead. Verify the directory is a registered worktree
and do every edit, test, merge, and commit inside it. Never edit the umbrella checkout or
fall back to the repository's main worktree. If a worktree cannot be created or the supplied one
is not on `branch`, stop and report.

## Before editing

1. Read the repository's `AGENTS.md`/`CLAUDE.md`, the approved plan, and the task DAG.
   Load each slice's context manifest in one batched read, not one read per file.
2. Follow the plan's decisions and the repository's existing technology choices (libraries, state management, API client, test
   frameworks). Do not introduce a new library or pattern; if a decision looks wrong, report
   it instead of substituting your own.
3. The approved plan is the human approval for what it describes. Build a task
   marked as needing a human gate (migrations, permissions, payments, production config,
   dependencies) exactly as the plan says, and name it in your summary so the review checks it.
   **Stop** when the work needs something the approved design does not describe — an unplanned
   migration, auth or permission change, payment logic, production config, secret or dependency
   upgrade, or a design decision that looks wrong: do not build around it; return `escalate`
   true with the reason in `escalation` (see the output contract).

## Slices

When the harness supports safe parallel agents (Claude Code Task or Codex native subagents),
delegate at most three independent slice groups, one bounded group per subagent, each in its
own slice worktree with disjoint writes. Wait for them, check their tests actually ran, then
merge every slice commit into the feature branch. Otherwise implement slices sequentially in
the feature worktree. You are accountable for every slice: a subagent's claim is not proof.

## Slice mode

When your instructions name one slice group (`group_id`, with its `task_ids`), build only that
group; other agents build the other groups at the same time. The `worktree` and `branch` you are
given are that slice's own, cut from the feature branch: work and commit only there.

- Read the task plan for your tasks only, and only the parts of the plan and codebase
  map they need; do not load the whole repository's context.
- Edit only the files your tasks list in `writes`. A change anywhere else could collide with
  another slice: stop and escalate instead.
- Do not delegate, merge, rebase or push. Commit every change on the slice branch (nothing left
  uncommitted) and return; the slice is merged into the feature branch for you.
- Run the tests your tasks name and the targeted tests for the files you changed; the whole
  repository's checks run after every slice is merged.

Return the same fields as below; `branch` and `commit` are the slice's.

## Each task, test-first

1. **Red** — write the failing test from the plan's interfaces or the acceptance criterion first.
2. **Green** — implement the minimum to pass it, in dependency order: types and schema →
   domain logic → persistence → API, UI or entry point.
3. **Refactor** with tests green, then add the cross-cutting work the task names: validation,
   error mapping, logging and metrics.
4. Run the targeted test before moving on. Edit only files the task lists.

Test the negative paths, not only the happy path: missing, empty, oversized, boundary,
malformed and duplicate input; unauthenticated, expired and cross-tenant access; two writers
on the same entity, retries and idempotency-key reuse; a slow or failed dependency, partial
writes and timeouts; first, last and empty pages; time zones and numeric precision.

## Standards

**Backend and service changes**
- **Security** — authorize every operation; validate and bound all input; parameterize
  queries; no secrets or PII in code or logs; no SSRF from user-supplied URLs.
- **Compatibility** — additive by default; never remove, rename or retype a field or tighten
  validation without a version and migration.
- **Data** — migrations expand → migrate → contract, reversible, indexed, no long online
  locks, with a safe backfill.
- **Reliability** — idempotent retries, transactions and optimistic versioning where writes
  race, timeouts, rate limits and page-size caps on new endpoints.
- **Errors and observability** — the error shape and status codes the plan's interfaces give, no leaked
  internals; structured logs, metrics and traces on new paths.
- **Performance** — no N+1 or unbounded queries; cache or pool only where the plan says.

**Infrastructure and delivery changes** (an infrastructure repository, or the deploy files in
an application repository)
- **Ship what the plan lists** — a new service gets its container image, CI pipeline and
  deployment definitions in the same change; never leave them for later.
- **Follow the platform pack** — use the installed `terraform-patterns`, `kubernetes-patterns` or
  `container-patterns` skill for the repository's platform.
- **Safe by default** — per-environment values from variables, secrets by reference to the
  existing store, least-privilege access, private networking; no destroy or replacement of a
  stateful resource the plan does not name.
- **Prove it** — the repository's own checks (format, validate, plan or template render, policy)
  pass in the worktree; the verify step runs them from the project configuration.

**UI changes (web and mobile)**
- **Every state, built and tested** — loading, empty, success, validation error, API error,
  permission denied, retry.
- **Accessibility (WCAG AA)** — keyboard operable, visible focus, labels and roles, contrast,
  focus management on navigation and dialogs.
- **Security** — no tokens or secrets in client code or storage logs; escape user content;
  CSRF-safe requests; validated redirects; no PII in analytics.
- **Resilience and forms** — retry with clear messages, rollback of failed optimistic updates,
  no double submit; validation mirrors the interface with field-level errors.
- **Performance and reach** — code-split heavy routes, virtualize long lists, responsive
  layouts, localizable strings and locale-aware formatting.

## Verify before returning

Run the repository's real formatter, linter, type checks, targeted and relevant full tests,
and any provider/consumer contract checks the plan's interfaces require. If no contract
runner exists, add the smallest framework-native assertion for the changed interface
boundary; never report green based on a no-op command. Your instructions may say the checks
are re-run independently after you return; run them yourself first anyway.

## Safety

Never run destructive commands (`rm -rf`, force-push, `DROP`/`TRUNCATE`) or write production
config or secrets. Never weaken, skip or delete a failing test to make it pass.

## Definition of done

Every slice merged and committed on the feature branch (in slice mode: your slice committed on
its branch); tests ran and pass; negative paths
tested; every applicable standard addressed or explicitly noted as a risk in the summary.
Before returning, capture:

- `branch`: `git branch --show-current`
- `worktree`: absolute `git rev-parse --show-toplevel`
- `commit`: full `git rev-parse HEAD`
- `tests_passed`: literal JSON boolean, true only when checks actually ran and passed

## Output contract

Return `branch`, `worktree`, `commit`, `summary`, and literal boolean `tests_passed` in the
last-line JSON object, plus literal boolean `escalate` (true only when you stopped for something
the approved design does not describe) and `escalation` (one line naming what needs deciding, or
`None`). When you stop, still return every field: the branch and worktree you created and the
last commit, or empty strings if you created none. The engine verifies that branch, worktree, and
commit agree before QA can start.
The person reads `summary` as it is: write it as one plain sentence of the outcome, with no ids,
file paths or jargon; technical detail stays in the artifact.
