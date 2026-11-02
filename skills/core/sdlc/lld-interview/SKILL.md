---
name: lld-interview
description: Clarify only material repository implementation decisions before the repository LLDs are written. Audit existing answers, inspect each bounded implementation seam, and ask feature-specific questions in grouped native popups.
allowed-tools: Read, Grep, Glob, Write, Bash
tags: [sdlc, design, lld]
---

# LLD interview

Resolve decisions that a developer cannot safely infer from the approved HLD and repository evidence.
This runs in the lead agent so the grouped conversation and subsequent LLD write share one context.
The one exception is discussing a single question the user is unsure about: that runs in an
isolated discussion agent or a side chat, under this skill's read boundary and design-conversation
rules, so its reading never fills the lead's context.

## Read boundary

Read the approved HLD, its deferred-question ledger, the contract when one exists, confirmed LLD
decisions, and, for each repository your instructions name, its guidance, maintained codebase map,
relevant manifest, and only source/tests around the seam this feature changes. Start from paths named
by the maps. Do not scan whole repositories. When several repositories are in scope, keep one queue:
prefix each question title with its repository, and ask a decision that spans repositories once.

## Decide from evidence before asking

Do not ask the user to choose a normal implementation detail when the repository already has a clear
convention. Record no question for choices the writer can safely make from code evidence. Ask only an
unresolved decision that materially changes correctness, compatibility, or the implementation seam:

- which existing module or extension seam owns ambiguous behavior;
- local state authority, lifecycle, validation, or migration where the HLD leaves alternatives;
- this repo's precise side of an API, event, navigation, storage, or background-work boundary;
- for an API-producing backend, unresolved persistence ownership or client-contract facts: entity
  relationships, destructive behavior, route/operation shape, complete DTOs, authorization, stable
  errors, pagination, time/enum representation, idempotency, refresh and shared-contract ownership;
- visible error, retry, concurrency, idempotency, offline, or recovery behavior;
- authorization, privacy, sensitive-data handling, or trust-boundary enforcement;
- backward compatibility, rollout, backout, or support for relevant execution modes;
- a verification seam when materially different choices change testability or delivery risk.

Do not reopen PRD, HLD or contract decisions. Do not ask for filenames, class names, boilerplate, library syntax,
task estimates, styling preferences, or facts directly discoverable from source. Do not ask a
frontend developer to rediscover a backend payload later: resolve material client-visible ambiguity
before writing. Recommend the simplest option that follows current repository patterns.

## Design conversation

The developer decides with you; do not just ask them to confirm.

- For a genuine trade-off, offer the recommendation plus up to two real `alternatives`
  (`{label, tradeoff}`) grounded in the code you inspected — name the seam or pattern each follows.
- When no other gap remains, ask one `kind: "direction"` question whose `proposal` (up to 150 words)
  summarises the intended change in each repository: the seam, data/state changes, its contract
  side, and failure handling. The queue cannot close until the latest direction is confirmed after every
  other decision; ask a fresh one (new ID) whenever later answers change it.
- When the user is unsure or asks back, show the evidence: the existing pattern, what each option
  changes, and the risk. If a fact belongs to someone else (another team, a vendor), say so.
- Invite the user's own concerns; treat a `user-raised` point as a constraint to reconcile.

## Answer audit

- Check every saved answer against its `must_resolve` facts and against code/HLD constraints.
- For `source: user-answer`, only `answer` is confirmed; proposal text is not. `chosen-alternative`
  and `accepted-proposal` are confirmed; `assumption` must be flagged as unverified; `deferred`
  settles nothing; `user-raised` is the user's own input. Build on a `discussion` summary.
- Follow up only on the missing or contradictory fact, using a new stable ID.
- A blocking repo decision cannot be deferred. An implementation detail with a safe existing
  convention should be decided by the writer, not sent back to the user.

## Queue contract

Write the supplied queue as schema version 2. Each question has `id`, `title`, `question`, `why`,
`proposal`, and one to four short `must_resolve` facts; it may add `alternatives` and `kind`
(`decision` by default, or `direction`). Use 3–7 questions when several material gaps
remain and fewer when nearly clear. An empty queue requires empty `audit.unresolved` and
`audit.contradictions`. Run the supplied validator before completing.

**One decision log, no repeats.** Your instructions may supply the feature's decision log (every
earlier stage's decisions) and this stage's decisions. Give every question a short kebab-case
`topic` naming what it decides. Never ask a topic already decided in either; to refine a recorded
answer, ask at most one follow-up with `follow_up_of: <that decision's id>`. Rephrasing a decided
question under a new id is still a repeat.

**Decide from evidence first.** Before asking, check the requirement, approved documents, code and
docs. A point they already settle is not a question: record it under the queue's `settled` array
as `{topic, title, decision, source}`, where `source` is the file that settles it
(`path`, `path#section` or `path:line`). The engine records it as an evidence-settled decision.

## Presentation

Collect each round through the workflow's native grouped popup. If the host limits popup size,
collect consecutive chunks without analyzing or writing between them. Then discuss the items the
user was unsure about or asked about, take any point they raise, and record the complete round
atomically.

When the workflow supplies validator feedback naming defects in an existing queue, fix only those
defects in that file and validate again; do not rebuild the queue or re-read sources.

## Safety

Write only the workflow-supplied question queue. Never edit the LLD, source, parent artifacts, or
state.

## Output contract

Return `summary`: one short sentence describing the queue or confirming the repo is clear.
